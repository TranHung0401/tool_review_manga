"""Manga to Video Pipeline CLI interface."""

from pathlib import Path

import typer
from rich.console import Console

from manga_pipeline.core.anchors import AnchorStore
from manga_pipeline.core.reconcile import reconcile_layout
from manga_pipeline.core.schemas.artifact_layout import LayoutArtifact
from manga_pipeline.core.schemas.artifact_ocr import OcrArtifact
from manga_pipeline.core.schemas.artifact_script import ScriptArtifact
from manga_pipeline.core.schemas.artifact_tts import TtsArtifact
from manga_pipeline.core.schemas.project_schema import (
    AudioClip,
    AudioTrack,
    ProjectSchema,
    StoryMetadata,
    VideoClip,
    VideoTrack,
)
from manga_pipeline.engines.layout.manga_image_translator import MangaImageTranslatorLayoutEngine
from manga_pipeline.engines.ocr.manga_ocr_engine import MangaOcrEngine
from manga_pipeline.engines.protocols import LayoutRequest, OcrRequest, ScriptRequest, TtsRequest
from manga_pipeline.engines.script.manual_import import ManualScriptEngine
from manga_pipeline.engines.tts.edge_tts_engine import EdgeTtsEngine
from manga_pipeline.pipeline.jobs import JobRunner
from manga_pipeline.render.ffmpeg_renderer import FFmpegRenderer
from manga_pipeline.render.plan import RenderPlan

app = typer.Typer(help="Manga/Comic to Video Batch Pipeline CLI")
console = Console()


def _load_project(project_file: Path) -> ProjectSchema:
    if project_file.exists():
        with open(project_file, encoding="utf-8") as f:
            return ProjectSchema.model_validate_json(f.read())
    return ProjectSchema(story=StoryMetadata(title="Manga Story", chapters=[]))


def _save_project(project: ProjectSchema, project_file: Path) -> None:
    project_file.parent.mkdir(parents=True, exist_ok=True)
    with open(project_file, "w", encoding="utf-8") as f:
        f.write(project.model_dump_json(indent=2))


@app.command()
def layout(
    chapter_id: str = typer.Argument(..., help="Chapter ID e.g. ch01"),
    pages_dir: Path = typer.Option(..., "--pages", "-p", help="Directory containing page images"),
    project_dir: Path = typer.Option(Path("."), "--project-dir", help="Project root directory"),
) -> None:
    """Run layout detection batch stage."""
    console.print(f"[bold blue]Running Layout detection for {chapter_id}...[/bold blue]")
    pages = sorted(list(pages_dir.glob("*.png")) + list(pages_dir.glob("*.jpg")) + list(pages_dir.glob("*.jpeg")))
    if not pages:
        console.print(f"[bold red]No image files found in {pages_dir}[/bold red]")
        raise typer.Exit(1)

    engine = MangaImageTranslatorLayoutEngine()
    req = LayoutRequest(chapter_id=chapter_id, pages=pages)
    result = engine.detect(req)

    # Save artifact atomically
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifacts_dir / f"layout.{chapter_id}.v1.json"
    tmp_path = artifacts_dir / f"layout.{chapter_id}.v1.json.tmp"

    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(result.artifact.model_dump_json(indent=2))
    JobRunner.atomic_finalize_artifact(tmp_path, artifact_path)

    # Reconcile with project anchors
    project_file = project_dir / "project.json"
    project = _load_project(project_file)
    if chapter_id not in project.story.chapters:
        project.story.chapters.append(chapter_id)

    store = AnchorStore(project)
    reconcile_layout(None, result.artifact, store)
    project.active_artifacts[chapter_id] = project.active_artifacts.get(chapter_id, {})
    project.active_artifacts[chapter_id]["layout"] = 1
    _save_project(project, project_file)

    console.print(
        f"[bold green][OK] Layout artifact generated:[/] {artifact_path} ({len(result.artifact.panels)} panels)"
    )


@app.command()
def ocr(
    chapter_id: str = typer.Argument(..., help="Chapter ID"),
    project_dir: Path = typer.Option(Path("."), "--project-dir", help="Project root directory"),
) -> None:
    """Run OCR extraction batch stage."""
    console.print(f"[bold blue]Running OCR for {chapter_id}...[/bold blue]")
    layout_file = project_dir / "artifacts" / f"layout.{chapter_id}.v1.json"
    if not layout_file.exists():
        console.print(f"[bold red]Layout artifact {layout_file} not found. Run layout first.[/bold red]")
        raise typer.Exit(1)

    with open(layout_file, encoding="utf-8") as f:
        layout_artifact = LayoutArtifact.model_validate_json(f.read())

    engine = MangaOcrEngine()
    req = OcrRequest(
        chapter_id=chapter_id,
        layout_artifact=layout_artifact,
        pages_dir=project_dir / "pages",
        cleaned_dir=project_dir / "cleaned",
    )
    result = engine.extract(req)

    # Save artifact
    artifacts_dir = project_dir / "artifacts"
    artifact_path = artifacts_dir / f"ocr.{chapter_id}.v1.json"
    tmp_path = artifacts_dir / f"ocr.{chapter_id}.v1.json.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(result.artifact.model_dump_json(indent=2))
    JobRunner.atomic_finalize_artifact(tmp_path, artifact_path)

    project_file = project_dir / "project.json"
    project = _load_project(project_file)
    project.active_artifacts[chapter_id]["ocr"] = 1
    _save_project(project, project_file)

    console.print(f"[bold green][OK] OCR artifact generated:[/] {artifact_path}")


@app.command()
def script(
    chapter_id: str = typer.Argument(..., help="Chapter ID"),
    script_file: Path | None = typer.Option(None, "--file", "-f", help="Script text file"),
    project_dir: Path = typer.Option(Path("."), "--project-dir", help="Project root directory"),
) -> None:
    """Run Script production stage (manual import)."""
    p_dir = project_dir if isinstance(project_dir, Path) else Path(".")
    s_file = script_file if isinstance(script_file, Path) else None

    console.print(f"[bold blue]Producing Script for {chapter_id}...[/bold blue]")
    ocr_file = p_dir / "artifacts" / f"ocr.{chapter_id}.v1.json"
    if not ocr_file.exists():
        console.print(f"[bold red]OCR artifact {ocr_file} not found. Run ocr first.[/bold red]")
        raise typer.Exit(1)

    with open(ocr_file, encoding="utf-8") as f:
        ocr_artifact = OcrArtifact.model_validate_json(f.read())

    engine = ManualScriptEngine()
    req = ScriptRequest(
        chapter_id=chapter_id,
        mode="manual_script",
        ocr_artifact=ocr_artifact,
        source_file=s_file,
    )
    result = engine.produce(req)

    artifacts_dir = p_dir / "artifacts"
    artifact_path = artifacts_dir / f"script.{chapter_id}.v1.json"
    tmp_path = artifacts_dir / f"script.{chapter_id}.v1.json.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(result.artifact.model_dump_json(indent=2))
    JobRunner.atomic_finalize_artifact(tmp_path, artifact_path)

    # Register unit anchors into project
    project_file = p_dir / "project.json"
    project = _load_project(project_file)
    store = AnchorStore(project)
    for unit in result.artifact.units:
        if not store.find_by_ai_id(unit.id, kind="unit"):
            store.create_anchor("unit", unit.id)

    project.active_artifacts[chapter_id]["script"] = 1
    _save_project(project, project_file)

    console.print(
        f"[bold green][OK] Script artifact generated:[/] {artifact_path} ({len(result.artifact.units)} units)"
    )


@app.command()
def tts(
    chapter_id: str = typer.Argument(..., help="Chapter ID"),
    voice: str = typer.Option("vi-VN-HoaiMyNeural", "--voice", "-v", help="TTS Voice reference"),
    project_dir: Path = typer.Option(Path("."), "--project-dir", help="Project root directory"),
) -> None:
    """Run TTS Speech Synthesis stage."""
    p_dir = project_dir if isinstance(project_dir, Path) else Path(".")
    voice_str = voice if isinstance(voice, str) else "vi-VN-HoaiMyNeural"

    console.print(f"[bold blue]Synthesizing speech for {chapter_id} with voice {voice_str}...[/bold blue]")
    script_file = p_dir / "artifacts" / f"script.{chapter_id}.v1.json"
    if not script_file.exists():
        console.print(f"[bold red]Script artifact {script_file} not found. Run script first.[/bold red]")
        raise typer.Exit(1)

    with open(script_file, encoding="utf-8") as f:
        script_artifact = ScriptArtifact.model_validate_json(f.read())

    engine = EdgeTtsEngine()
    req = TtsRequest(
        chapter_id=chapter_id,
        script_artifact=script_artifact,
        audio_output_dir=p_dir / "audio",
        artifact_version=1,
        voice_ref=voice_str,
    )
    result = engine.synthesize(req)

    artifacts_dir = p_dir / "artifacts"
    artifact_path = artifacts_dir / f"tts.{chapter_id}.v1.json"
    tmp_path = artifacts_dir / f"tts.{chapter_id}.v1.json.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(result.artifact.model_dump_json(indent=2))
    JobRunner.atomic_finalize_artifact(tmp_path, artifact_path)

    project_file = p_dir / "project.json"
    project = _load_project(project_file)
    project.active_artifacts[chapter_id]["tts"] = 1
    _save_project(project, project_file)

    console.print(
        f"[bold green][OK] TTS artifact generated:[/] {artifact_path} ({len(result.artifact.clips)} audio clips)"
    )


@app.command()
def render(
    chapter_id: str = typer.Argument(..., help="Chapter ID"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output MP4 file path"),
    project_dir: Path = typer.Option(Path("."), "--project-dir", help="Project root directory"),
) -> None:
    """Render final MP4 video via RenderPlan and FFmpeg."""
    p_dir = project_dir if isinstance(project_dir, Path) else Path(".")
    out_mp4 = output if isinstance(output, Path) else (p_dir / "renders" / f"{chapter_id}.mp4")

    console.print(f"[bold blue]Rendering MP4 for {chapter_id}...[/bold blue]")
    project_file = p_dir / "project.json"
    project = _load_project(project_file)

    layout_file = p_dir / "artifacts" / f"layout.{chapter_id}.v1.json"
    tts_file = p_dir / "artifacts" / f"tts.{chapter_id}.v1.json"

    layout_artifact = None
    if layout_file.exists():
        with open(layout_file, encoding="utf-8") as f:
            layout_artifact = LayoutArtifact.model_validate_json(f.read())

    tts_artifact = None
    if tts_file.exists():
        with open(tts_file, encoding="utf-8") as f:
            tts_artifact = TtsArtifact.model_validate_json(f.read())

    # Build sequence in project if not populated
    store = AnchorStore(project)
    panel_anchors = list(store.get_by_kind("panel").keys())
    unit_anchors = list(store.get_by_kind("unit").keys())

    if not project.sequence.video_tracks and panel_anchors:
        vclips = [VideoClip(panel_ref=pa, start_ms=i * 3000, duration_ms=3000) for i, pa in enumerate(panel_anchors)]
        project.sequence.video_tracks = [VideoTrack(clips=vclips)]

    if not project.sequence.audio_tracks and unit_anchors:
        aclips = [
            AudioClip(audio_ref=sa, start_ms=i * 3000, synced_duration_ms=2500) for i, sa in enumerate(unit_anchors)
        ]
        project.sequence.audio_tracks = [AudioTrack(clips=aclips)]

    plan = RenderPlan.from_project(chapter_id, project, layout_artifact, tts_artifact)

    renderer = FFmpegRenderer()
    final_mp4 = renderer.render(plan, p_dir, out_mp4)

    console.print(f"[bold green][OK] Successfully rendered MP4:[/] {final_mp4}")


@app.command()
def ui(
    port: int = typer.Option(8000, "--port", "-p", help="Port to run Dashboard on"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host address"),
    project_dir: Path = typer.Option(Path("."), "--project-dir", help="Project root"),
) -> None:
    """Launch local Manga Pipeline Web Dashboard."""
    import asyncio
    import sys

    import uvicorn

    from manga_pipeline.web.app import create_app

    # On Windows, use SelectorEventLoopPolicy or suppress benign socket reset exceptions
    if sys.platform == "win32":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except Exception:
            pass

    p_dir = project_dir if isinstance(project_dir, Path) else Path(".")
    web_app = create_app(p_dir)
    console.print(f"[bold green]Starting Manga Pipeline Dashboard at http://{host}:{port}...[/bold green]")
    uvicorn.run(web_app, host=host, port=port, log_level="info")


@app.command()
def run_all(
    chapter_id: str = typer.Argument(..., help="Chapter ID e.g. ch01"),
    pages_dir: Path = typer.Option(..., "--pages", "-p", help="Directory containing pages"),
    script_file: Path | None = typer.Option(None, "--script", "-s", help="Optional script file"),
    output_mp4: Path | None = typer.Option(None, "--output", "-o", help="Output MP4 path"),
    project_dir: Path = typer.Option(Path("."), "--project-dir", help="Project root"),
) -> None:
    """Execute complete end-to-end pipeline Spike: Layout -> OCR -> Script -> TTS -> MP4."""
    console.print(f"[bold yellow]=== STARTING END-TO-END PIPELINE SPIKE FOR {chapter_id} ===[/bold yellow]")
    layout(chapter_id=chapter_id, pages_dir=pages_dir, project_dir=project_dir)
    ocr(chapter_id=chapter_id, project_dir=project_dir)
    script(chapter_id=chapter_id, script_file=script_file, project_dir=project_dir)
    tts(chapter_id=chapter_id, voice="vi-VN-HoaiMyNeural", project_dir=project_dir)
    render(chapter_id=chapter_id, output=output_mp4, project_dir=project_dir)
    console.print(f"[bold green]=== END-TO-END SPIKE COMPLETE FOR {chapter_id} ===[/bold green]")


if __name__ == "__main__":
    app()
