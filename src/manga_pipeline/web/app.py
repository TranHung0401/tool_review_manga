"""FastAPI application for Manga Video Pipeline Local Web Dashboard."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel

from manga_pipeline.connectors.local_folder import LocalFolderConnector
from manga_pipeline.core.anchors import AnchorStore
from manga_pipeline.core.hardware import detect_hardware
from manga_pipeline.core.layout_resolve import layout_overrides_hash, resolve_layout
from manga_pipeline.core.reconcile import ImageSourceChangedError, reconcile_layout
from manga_pipeline.core.schemas.artifact_layout import LayoutArtifact
from manga_pipeline.core.schemas.artifact_ocr import OcrArtifact
from manga_pipeline.core.schemas.artifact_script import ScriptArtifact
from manga_pipeline.core.schemas.artifact_tts import TtsArtifact
from manga_pipeline.core.schemas.project_schema import (
    ChapterLayoutOverrides,
    MergeOverride,
    ProjectSchema,
    StoryMetadata,
    TextOverride,
    UserPanelOverride,
)
from manga_pipeline.engines.layout.manga_image_translator import MangaImageTranslatorLayoutEngine
from manga_pipeline.engines.ocr.manga_ocr_engine import MangaOcrEngine
from manga_pipeline.engines.protocols import LayoutRequest, OcrRequest, ScriptRequest, TtsRequest
from manga_pipeline.engines.script.manual_import import ManualScriptEngine
from manga_pipeline.engines.script.translate_engine import TranslateScriptEngine
from manga_pipeline.engines.tts.providers import TtsProviderRegistry
from manga_pipeline.pipeline.sync import apply_resync, apply_sync_policy, compute_resync_diff
from manga_pipeline.render.capcut_exporter import CapCutProjectExporter
from manga_pipeline.render.ffmpeg_renderer import FFmpegRenderer
from manga_pipeline.render.plan import RenderPlan
from manga_pipeline.render.srt_exporter import SRTExporter


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    """Lifespan context manager to handle Windows asyncio socket connection reset cleanly."""
    loop = asyncio.get_running_loop()
    default_handler = loop.get_exception_handler()

    def _silence_win_conn_reset(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        exc = context.get("exception")
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError)):
            return
        if isinstance(exc, OSError) and getattr(exc, "winerror", None) in (10053, 10054):
            return
        if default_handler:
            default_handler(loop, context)
        else:
            loop.default_exception_handler(context)

    loop.set_exception_handler(_silence_win_conn_reset)
    yield


def create_app(project_dir: Path | None = None) -> FastAPI:
    """Factory creating configured FastAPI app for the pipeline dashboard."""
    p_dir = project_dir or Path(".")
    app = FastAPI(title="Manga Video Pipeline Dashboard", version="1.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)

    def _get_project() -> ProjectSchema:
        p_file = p_dir / "project.json"
        if not p_file.exists():
            proj = ProjectSchema(story=StoryMetadata(title="Manga Story", chapters=[]))
            with open(p_file, "w", encoding="utf-8") as f:
                f.write(proj.model_dump_json(indent=2))
            return proj
        with open(p_file, encoding="utf-8") as f:
            return ProjectSchema.model_validate_json(f.read())

    def _save_project(proj: ProjectSchema) -> None:
        p_file = p_dir / "project.json"
        with open(p_file, "w", encoding="utf-8") as f:
            f.write(proj.model_dump_json(indent=2))

    @app.get("/api/project")
    def get_project() -> dict[str, Any]:
        """Return project state."""
        return _get_project().model_dump()

    @app.get("/api/chapters")
    def list_chapters() -> list[dict[str, Any]]:
        """List chapters and page counts."""
        proj = _get_project()
        chapters_data = []
        for ch in proj.story.chapters:
            pages_dir = p_dir / "pages" / ch
            if not pages_dir.exists():
                pages_dir = p_dir / "tests" / "fixtures" / ch / "pages"

            pages = []
            if pages_dir.exists():
                pages = [
                    f.name
                    for f in sorted(pages_dir.iterdir())
                    if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
                ]

            artifacts_status = proj.active_artifacts.get(ch, {})
            video_path = p_dir / "renders" / f"{ch}.mp4"
            chapters_data.append(
                {
                    "id": ch,
                    "pages_count": len(pages),
                    "pages": pages,
                    "artifacts": artifacts_status,
                    "has_render": video_path.exists(),
                    "render_url": f"/media/renders/{ch}.mp4" if video_path.exists() else None,
                }
            )
        return chapters_data

    class ImportRequest(BaseModel):
        chapter_id: str
        source_path: str

    @app.post("/api/import")
    def import_chapter(req: ImportRequest) -> dict[str, Any]:
        """Import manga pages from local directory."""
        connector = LocalFolderConnector()
        src_path = Path(req.source_path)
        if not src_path.exists():
            raise HTTPException(status_code=400, detail=f"Đường dẫn {src_path} không tồn tại")

        try:
            res = connector.import_chapter(req.chapter_id, src_path, p_dir)
            return {
                "chapter_id": res.chapter_id,
                "pages_imported": len(res.pages),
                "source_type": res.source_type,
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/api/upload-chapter/{chapter_id}")
    async def upload_chapter_pages(
        chapter_id: str,
        files: list[UploadFile] = File(...),
    ) -> dict[str, Any]:
        """Upload image files directly to pages/{chapter_id}."""
        if not files:
            raise HTTPException(status_code=400, detail="Vui lòng chọn ít nhất 1 file ảnh")

        dest_dir = p_dir / "pages" / chapter_id
        dest_dir.mkdir(parents=True, exist_ok=True)

        saved_files = []
        for file in files:
            if not file.filename:
                continue
            ext = Path(file.filename).suffix.lower()
            if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            dest_path = dest_dir / file.filename
            content = await file.read()
            with open(dest_path, "wb") as f:
                f.write(content)
            saved_files.append(file.filename)

        if not saved_files:
            raise HTTPException(status_code=400, detail="Không tìm thấy file ảnh hợp lệ (.png, .jpg, .jpeg, .webp)")

        # Register chapter in project.json
        proj = _get_project()
        if chapter_id not in proj.story.chapters:
            proj.story.chapters.append(chapter_id)
            _save_project(proj)

        return {
            "chapter_id": chapter_id,
            "pages_uploaded": len(saved_files),
            "files": sorted(saved_files),
        }

    @app.get("/api/artifacts/{chapter_id}/{stage}")
    def get_artifact(chapter_id: str, stage: str, version: int = Query(1)) -> dict[str, Any]:
        """Fetch raw artifact JSON for a specific stage."""
        art_path = p_dir / "artifacts" / f"{stage}.{chapter_id}.v{version}.json"
        if not art_path.exists():
            raise HTTPException(status_code=404, detail=f"Artifact {art_path.name} not found")
        with open(art_path, encoding="utf-8") as f:
            return (
                dict(LayoutArtifact.model_validate_json(f.read()).model_dump())
                if stage == "layout"
                else dict(OcrArtifact.model_validate_json(f.read()).model_dump())
                if stage == "ocr"
                else dict(ScriptArtifact.model_validate_json(f.read()).model_dump())
                if stage == "script"
                else dict(TtsArtifact.model_validate_json(f.read()).model_dump())
            )

    class RunStageRequest(BaseModel):
        chapter_id: str
        pages_path: str | None = None
        voice: str = "vi-VN-HoaiMyNeural"
        script_mode: str = "manual_script"  # manual_script | translate
        glossary: dict[str, str] = {}
        target_language: str = "vi"

    def _write_artifact_atomically(path: Path, json_str: str) -> None:
        """Write artifact safely directly to file with retry on Windows."""
        path.parent.mkdir(parents=True, exist_ok=True)
        import time
        for _attempt in range(5):
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(json_str)
                    f.flush()
                return
            except OSError:
                time.sleep(0.1)

    def _latest_artifact_version(stage: str, chapter_id: str) -> int:
        """Find highest existing artifact version for stage/chapter (0 if none)."""
        artifacts_dir = p_dir / "artifacts"
        if not artifacts_dir.exists():
            return 0
        best = 0
        prefix = f"{stage}.{chapter_id}.v"
        for f in artifacts_dir.glob(f"{stage}.{chapter_id}.v*.json"):
            try:
                best = max(best, int(f.name[len(prefix):-5]))
            except ValueError:
                continue
        return best

    def _safe_load_artifact(path: Path, model_cls: Any) -> Any:
        """Load artifact safely; returns None if file is missing, empty, or invalid."""
        if not path.exists() or path.stat().st_size == 0:
            return None
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return None
                return model_cls.model_validate_json(content)
        except Exception:
            return None

    @app.post("/api/run/{stage}")
    def run_stage(stage: str, req: RunStageRequest) -> dict[str, Any]:
        """Run single pipeline stage or run_all."""
        chapter_id = req.chapter_id
        project = _get_project()
        store = AnchorStore(project)
        artifacts_dir = p_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        pages_dir = Path(req.pages_path) if req.pages_path else (p_dir / "pages" / chapter_id)
        if not pages_dir.exists():
            pages_dir = p_dir / "tests" / "fixtures" / chapter_id / "pages"

        if stage in {"layout", "run_all"}:
            if not pages_dir.exists():
                raise HTTPException(status_code=400, detail=f"Thư mục ảnh {pages_dir} không tồn tại. Vui lòng nhập ảnh trước.")
            pages_list = [
                f
                for f in sorted(pages_dir.iterdir())
                if f.is_file() and f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
            ]
            if not pages_list:
                raise HTTPException(status_code=400, detail=f"Không tìm thấy file ảnh nào trong {pages_dir}")
            engine = MangaImageTranslatorLayoutEngine()
            layout_res = engine.detect(LayoutRequest(chapter_id=chapter_id, pages=pages_list))
            l_path = artifacts_dir / f"layout.{chapter_id}.v1.json"
            _write_artifact_atomically(l_path, layout_res.artifact.model_dump_json(indent=2))
            for p in layout_res.artifact.panels:
                if not store.find_by_ai_id(p.id, kind="panel"):
                    store.create_anchor("panel", p.id)
                for tr in p.text_regions:
                    if not store.find_by_ai_id(tr.id, kind="text"):
                        store.create_anchor("text", tr.id)
            if chapter_id not in project.active_artifacts:
                project.active_artifacts[chapter_id] = {}
            project.active_artifacts[chapter_id]["layout"] = 1
            _save_project(project)

        if stage in {"ocr", "run_all"}:
            l_path = artifacts_dir / f"layout.{chapter_id}.v1.json"
            layout_art = _safe_load_artifact(l_path, LayoutArtifact)
            if not layout_art:
                if not pages_dir.exists():
                    raise HTTPException(status_code=400, detail=f"Thư mục ảnh {pages_dir} không tồn tại.")
                pages_list = [
                    f
                    for f in sorted(pages_dir.iterdir())
                    if f.is_file() and f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
                ]
                engine = MangaImageTranslatorLayoutEngine()
                layout_res = engine.detect(LayoutRequest(chapter_id=chapter_id, pages=pages_list))
                layout_art = layout_res.artifact
                _write_artifact_atomically(l_path, layout_art.model_dump_json(indent=2))
                for p in layout_art.panels:
                    if not store.find_by_ai_id(p.id, kind="panel"):
                        store.create_anchor("panel", p.id)
                    for tr in p.text_regions:
                        if not store.find_by_ai_id(tr.id, kind="text"):
                            store.create_anchor("text", tr.id)

            # Pre-OCR mandatory workflow: OCR runs on the RESOLVED layout
            # (auto-detect + user layout overrides: delete/merge/draw/reorder)
            resolved_layout = resolve_layout(layout_art, project, chapter_id)
            ocr_engine = MangaOcrEngine()
            ocr_res = ocr_engine.extract(
                OcrRequest(chapter_id=chapter_id, layout_artifact=resolved_layout, pages_dir=pages_dir)
            )
            ocr_res.artifact.depends_on.layout_overrides_hash = layout_overrides_hash(
                project.layout_overrides.get(chapter_id)
            )
            o_path = artifacts_dir / f"ocr.{chapter_id}.v1.json"
            _write_artifact_atomically(o_path, ocr_res.artifact.model_dump_json(indent=2))
            project.active_artifacts[chapter_id]["ocr"] = 1
            _save_project(project)

        if stage in {"script", "run_all"}:
            o_path = artifacts_dir / f"ocr.{chapter_id}.v1.json"
            ocr_art = _safe_load_artifact(o_path, OcrArtifact)
            if not ocr_art:
                l_path = artifacts_dir / f"layout.{chapter_id}.v1.json"
                layout_art = _safe_load_artifact(l_path, LayoutArtifact)
                if not layout_art:
                    pages_list = [
                        f
                        for f in sorted(pages_dir.iterdir())
                        if f.is_file() and f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
                    ]
                    layout_res = MangaImageTranslatorLayoutEngine().detect(LayoutRequest(chapter_id=chapter_id, pages=pages_list))
                    layout_art = layout_res.artifact
                    _write_artifact_atomically(l_path, layout_art.model_dump_json(indent=2))
                ocr_res = MangaOcrEngine().extract(OcrRequest(chapter_id=chapter_id, layout_artifact=layout_art, pages_dir=pages_dir))
                ocr_art = ocr_res.artifact
                _write_artifact_atomically(o_path, ocr_art.model_dump_json(indent=2))

            if req.script_mode == "translate":
                script_engine: Any = TranslateScriptEngine()
                script_res = script_engine.produce(
                    ScriptRequest(
                        chapter_id=chapter_id,
                        mode="translate",
                        ocr_artifact=ocr_art,
                        target_language=req.target_language,
                        glossary=req.glossary,
                    )
                )
            else:
                script_engine = ManualScriptEngine()
                script_res = script_engine.produce(
                    ScriptRequest(chapter_id=chapter_id, mode="manual_script", ocr_artifact=ocr_art)
                )
            s_path = artifacts_dir / f"script.{chapter_id}.v1.json"
            _write_artifact_atomically(s_path, script_res.artifact.model_dump_json(indent=2))
            for u in script_res.artifact.units:
                if not store.find_by_ai_id(u.id, kind="unit"):
                    store.create_anchor("unit", u.id)
            project.active_artifacts[chapter_id]["script"] = 1
            _save_project(project)

        if stage in {"tts", "run_all"}:
            s_path = artifacts_dir / f"script.{chapter_id}.v1.json"
            script_art = _safe_load_artifact(s_path, ScriptArtifact)
            if not script_art:
                raise HTTPException(status_code=400, detail="Chưa có kịch bản. Hãy chạy Tạo Kịch Bản trước.")

            # Apply user overrides to script units before speech synthesis
            store = AnchorStore(project)
            for unit in script_art.units:
                anchor = store.find_by_ai_id(unit.id, kind="unit")
                if anchor and anchor in project.overrides:
                    override_val = project.overrides[anchor].text
                    if override_val is not None:
                        unit.text = override_val

            # Immutable artifacts: every TTS re-run writes a NEW version.
            next_version = _latest_artifact_version("tts", chapter_id) + 1
            registry = TtsProviderRegistry()
            tts_res = registry.synthesize(
                TtsRequest(
                    chapter_id=chapter_id,
                    script_artifact=script_art,
                    audio_output_dir=p_dir / "audio",
                    artifact_version=next_version,
                    voice_ref=req.voice,
                )
            )
            t_path = artifacts_dir / f"tts.{chapter_id}.v{next_version}.json"
            _write_artifact_atomically(t_path, tts_res.artifact.model_dump_json(indent=2))
            # Snapshot rule: only auto-activate + sync on FIRST version.
            # Later versions wait for explicit user Resync (see /api/resync).
            if next_version == 1:
                project.active_artifacts[chapter_id]["tts"] = 1
                apply_sync_policy(project, chapter_id, tts_res.artifact)
            _save_project(project)

        if stage in {"render", "run_all"}:
            l_path = artifacts_dir / f"layout.{chapter_id}.v1.json"
            active_tts_v = project.active_artifacts.get(chapter_id, {}).get("tts", 1)
            t_path = artifacts_dir / f"tts.{chapter_id}.v{active_tts_v}.json"
            l_art = _safe_load_artifact(l_path, LayoutArtifact)
            t_art = _safe_load_artifact(t_path, TtsArtifact)

            if not l_art or not t_art:
                raise HTTPException(status_code=400, detail="Cần hoàn thành Layout và TTS trước khi Render video.")

            # Sync policy: duration = max(min_duration, audio + padding)
            if not project.sequence.video_tracks or not project.sequence.audio_tracks:
                apply_sync_policy(project, chapter_id, t_art)

            _save_project(project)

            l_art = resolve_layout(l_art, project, chapter_id)
            plan = RenderPlan.from_project(chapter_id, project, l_art, t_art)
            renderer = FFmpegRenderer()
            out_mp4 = p_dir / "renders" / f"{chapter_id}.mp4"
            renderer.render(plan, p_dir, out_mp4)

        return {"status": "success", "stage": stage, "chapter_id": chapter_id}

    class OverridePayload(BaseModel):
        text: str
        reviewed: bool = True

    class BatchOverridesPayload(BaseModel):
        overrides: dict[str, str]

    @app.post("/api/overrides")
    def batch_update_overrides(payload: BatchOverridesPayload) -> dict[str, Any]:
        """Batch save user overrides."""
        proj = _get_project()
        for anchor_id, text in payload.overrides.items():
            proj.overrides[anchor_id] = TextOverride(text=text, reviewed=True)
        _save_project(proj)
        return {"status": "success", "count": len(payload.overrides)}

    @app.post("/api/overrides/{anchor_id}")
    def update_override(anchor_id: str, payload: OverridePayload) -> dict[str, Any]:
        """Save a user override for a specific anchor."""
        proj = _get_project()
        proj.overrides[anchor_id] = TextOverride(text=payload.text, reviewed=payload.reviewed)
        _save_project(proj)
        return {"status": "success", "anchor_id": anchor_id, "override": payload.model_dump()}

    @app.post("/api/export/{chapter_id}")
    def export_chapter(chapter_id: str) -> dict[str, Any]:
        """Export SRT subtitle + audio folder + cropped panels for CapCut assembly.

        Output: exports/{chapter_id}/subtitles.srt + panels/ + audio/ + pages/ + export_report.json
        """
        artifacts_dir = p_dir / "artifacts"
        l_path = artifacts_dir / f"layout.{chapter_id}.v1.json"
        s_path = artifacts_dir / f"script.{chapter_id}.v1.json"
        t_path = artifacts_dir / f"tts.{chapter_id}.v1.json"

        if not s_path.exists():
            raise HTTPException(status_code=400, detail="Script artifact missing. Run Script stage first.")
        if not t_path.exists():
            raise HTTPException(status_code=400, detail="TTS artifact missing. Run TTS stage first.")

        l_art = _safe_load_artifact(l_path, LayoutArtifact)
        with open(s_path, encoding="utf-8") as f:
            script_art = ScriptArtifact.model_validate_json(f.read())
        with open(t_path, encoding="utf-8") as f:
            tts_art = TtsArtifact.model_validate_json(f.read())

        # Resolve pages dir
        pages_dir = p_dir / "pages" / chapter_id
        if not pages_dir.exists():
            pages_dir = p_dir / "tests" / "fixtures" / chapter_id / "pages"
        if not pages_dir.exists():
            pages_dir = None  # type: ignore[assignment]

        exporter = SRTExporter(p_dir)
        report = exporter.export(
            chapter_id,
            script_art,
            tts_art,
            pages_dir=pages_dir,
            project=_get_project(),
            layout_art=l_art,
        )
        return report

    @app.get("/api/grid-data/{chapter_id}")
    def get_grid_data(chapter_id: str) -> dict[str, Any]:
        """Return aggregated, unified row data for the Data Grid."""
        proj = _get_project()
        store = AnchorStore(proj)
        artifacts_dir = p_dir / "artifacts"

        l_path = artifacts_dir / f"layout.{chapter_id}.v1.json"
        o_path = artifacts_dir / f"ocr.{chapter_id}.v1.json"
        s_path = artifacts_dir / f"script.{chapter_id}.v1.json"
        t_path = artifacts_dir / f"tts.{chapter_id}.v1.json"

        l_art = LayoutArtifact.model_validate_json(l_path.read_text(encoding="utf-8")) if l_path.exists() else None
        o_art = OcrArtifact.model_validate_json(o_path.read_text(encoding="utf-8")) if o_path.exists() else None
        s_art = ScriptArtifact.model_validate_json(s_path.read_text(encoding="utf-8")) if s_path.exists() else None
        t_art = TtsArtifact.model_validate_json(t_path.read_text(encoding="utf-8")) if t_path.exists() else None

        # Build lookup maps
        ocr_texts_by_panel: dict[str, list[str]] = {}
        if o_art:
            for op in o_art.panels:
                ocr_texts_by_panel[op.id] = [t.original for t in op.texts if t.original]

        tts_by_unit: dict[str, dict[str, Any]] = {}
        if t_art:
            for tc in t_art.clips:
                tts_by_unit[tc.unit_id] = {
                    "file": tc.file,
                    "duration_ms": tc.duration_ms,
                }

        # Build script units by panel
        script_by_panel: dict[str, list[Any]] = {}
        if s_art:
            for u in s_art.units:
                script_by_panel.setdefault(u.panel_id, []).append(u)

        # Video clip template mapping
        clip_templates: dict[str, str] = {}
        for v_track in proj.sequence.video_tracks:
            for v_clip in v_track.clips:
                tpl = v_clip.visual_effects.get("template_ref", "")
                if tpl:
                    clip_templates[v_clip.panel_ref] = tpl

        rows: list[dict[str, Any]] = []
        if l_art and l_art.panels:
            for idx, lp in enumerate(l_art.panels):
                panel_anchor = store.find_by_ai_id(lp.id, kind="panel") or f"pa_{idx+1:06d}"
                anchor_entry = proj.anchors.get(panel_anchor)
                if anchor_entry and anchor_entry.retired:
                    continue

                page_image = lp.source.image
                page_filename = Path(page_image).name

                # OCR Text
                ocr_list = ocr_texts_by_panel.get(lp.id, [])
                ocr_text = " \n".join(ocr_list) if ocr_list else ""

                # Script Unit & Text
                units = script_by_panel.get(lp.id, [])
                script_anchor = "sa_unknown"
                script_unit_id = ""
                script_text = ""
                is_overridden = False

                if units:
                    primary_unit = units[0]
                    script_unit_id = primary_unit.id
                    script_anchor = store.find_by_ai_id(primary_unit.id, kind="unit") or f"sa_{idx+1:06d}"
                    script_text = primary_unit.text
                    if script_anchor in proj.overrides and proj.overrides[script_anchor].text is not None:
                        script_text = str(proj.overrides[script_anchor].text)
                        is_overridden = True
                else:
                    script_anchor = f"sa_{idx+1:06d}"
                    script_text = f"Lời dẫn chuyện cho khung tranh {lp.reading_order}."

                # Audio Clip
                audio_info = tts_by_unit.get(script_unit_id, {})
                audio_file = audio_info.get("file", "")
                audio_duration = audio_info.get("duration_ms", 0)

                # Templates
                kf_template = clip_templates.get(panel_anchor, "tpl_slow_zoom")
                in_out_template = "fade"

                rows.append({
                    "row_index": idx,
                    "panel_anchor": panel_anchor,
                    "panel_id": lp.id,
                    "page_file": page_filename,
                    "page_image": page_image,
                    "bbox": lp.source.bbox,
                    "reading_order": lp.reading_order,
                    "ocr_text": ocr_text,
                    "script_anchor": script_anchor,
                    "script_unit_id": script_unit_id,
                    "script_text": script_text,
                    "is_overridden": is_overridden,
                    "audio_file": audio_file,
                    "audio_duration_ms": audio_duration,
                    "has_audio": bool(audio_file),
                    "keyframe_template": kf_template,
                    "in_out_template": in_out_template,
                    "locked": anchor_entry.locked if anchor_entry else False,
                })

        return {
            "chapter_id": chapter_id,
            "total_rows": len(rows),
            "rows": rows,
            "active_artifacts": proj.active_artifacts.get(chapter_id, {}),
            "templates": list(proj.animation_templates.keys()) or ["tpl_slow_zoom", "tpl_zoom_in", "tpl_zoom_out", "tpl_pan_left", "tpl_pan_right"],
        }

    class BulkEffectsPayload(BaseModel):
        chapter_id: str
        panel_anchors: list[str]
        keyframe_template: str | None = None
        in_out_template: str | None = None

    @app.post("/api/effects/bulk-apply")
    def bulk_apply_effects(payload: BulkEffectsPayload) -> dict[str, Any]:
        """Bulk assign animation templates or in/out effects to selected panel anchors."""
        proj = _get_project()
        modified_count = 0
        target_anchors = set(payload.panel_anchors)

        for track in proj.sequence.video_tracks:
            for clip in track.clips:
                if not target_anchors or clip.panel_ref in target_anchors:
                    if payload.keyframe_template:
                        clip.visual_effects["template_ref"] = payload.keyframe_template
                    if payload.in_out_template:
                        clip.visual_effects["in_out"] = payload.in_out_template
                    modified_count += 1

        _save_project(proj)
        return {"status": "success", "modified_clips": modified_count}

    class PanelReorderPayload(BaseModel):
        chapter_id: str
        ordered_anchors: list[str]

    @app.post("/api/panels/reorder")
    def reorder_panels(payload: PanelReorderPayload) -> dict[str, Any]:
        """Reorder panels sequence."""
        proj = _get_project()
        anchor_order = {a: idx + 1 for idx, a in enumerate(payload.ordered_anchors)}

        # Update sequence order
        if proj.sequence.video_tracks:
            track = proj.sequence.video_tracks[0]
            track.clips.sort(key=lambda c: anchor_order.get(c.panel_ref, 999))
            # Recalculate start times
            cursor = 0
            for c in track.clips:
                c.start_ms = cursor
                cursor += c.duration_ms

        _save_project(proj)
        return {"status": "success", "total_reordered": len(payload.ordered_anchors)}

    # ------------------------------------------------------------------
    # Layout Editor (Sprint 2) — delete / merge / draw / reading order.
    # All operations write layout_overrides in project.json (anchor refs only);
    # the AI layout artifact stays immutable.
    # ------------------------------------------------------------------

    def _chapter_overrides(proj: ProjectSchema, chapter_id: str) -> ChapterLayoutOverrides:
        if chapter_id not in proj.layout_overrides:
            proj.layout_overrides[chapter_id] = ChapterLayoutOverrides()
        return proj.layout_overrides[chapter_id]

    class DeletePanelsPayload(BaseModel):
        chapter_id: str
        panel_anchors: list[str]

    @app.post("/api/layout/delete-panels")
    def layout_delete_panels(payload: DeletePanelsPayload) -> dict[str, Any]:
        """Mark panels as deleted (pre-OCR layout editing)."""
        proj = _get_project()
        ov = _chapter_overrides(proj, payload.chapter_id)
        for a in payload.panel_anchors:
            if not a.startswith("pa_"):
                raise HTTPException(status_code=400, detail=f"'{a}' không phải anchor pa_...")
            if a not in ov.deleted_panels:
                ov.deleted_panels.append(a)
        _save_project(proj)
        return {"status": "success", "deleted_panels": ov.deleted_panels}

    class MergePanelsPayload(BaseModel):
        chapter_id: str
        into: str
        from_anchors: list[str]

    @app.post("/api/layout/merge-panels")
    def layout_merge_panels(payload: MergePanelsPayload) -> dict[str, Any]:
        """Merge panels into a target panel (union bbox at resolve time)."""
        proj = _get_project()
        ov = _chapter_overrides(proj, payload.chapter_id)
        ov.merged.append(MergeOverride(into=payload.into, **{"from": payload.from_anchors}))
        _save_project(proj)
        return {"status": "success", "merged": [m.model_dump(by_alias=True) for m in ov.merged]}

    class DrawPanelPayload(BaseModel):
        chapter_id: str
        image: str
        bbox: list[int]
        reading_order: int

    @app.post("/api/layout/draw-panel")
    def layout_draw_panel(payload: DrawPanelPayload) -> dict[str, Any]:
        """Add a user hand-drawn panel (locked anchor, never auto-remapped)."""
        if len(payload.bbox) != 4:
            raise HTTPException(status_code=400, detail="bbox phải là [x, y, w, h]")
        proj = _get_project()
        store = AnchorStore(proj)
        from manga_pipeline.core.ids import panel_id as _make_pid

        ai_id = _make_pid(payload.image, payload.bbox)
        anchor = store.create_anchor("panel", ai_id, locked=True)
        ov = _chapter_overrides(proj, payload.chapter_id)
        ov.user_panels.append(
            UserPanelOverride(
                anchor=anchor,
                source={"image": payload.image, "bbox": payload.bbox},  # type: ignore[arg-type]
                reading_order=payload.reading_order,
                locked=True,
            )
        )
        _save_project(proj)
        return {"status": "success", "anchor": anchor, "ai_id": ai_id}

    class ReadingOrderPayload(BaseModel):
        chapter_id: str
        orders: dict[str, int]

    @app.post("/api/layout/reading-order")
    def layout_reading_order(payload: ReadingOrderPayload) -> dict[str, Any]:
        """Override panel reading order (pa_ anchor -> new order)."""
        proj = _get_project()
        ov = _chapter_overrides(proj, payload.chapter_id)
        ov.reading_order_overrides.update(payload.orders)
        _save_project(proj)
        return {"status": "success", "reading_order_overrides": ov.reading_order_overrides}

    @app.get("/api/layout/resolved/{chapter_id}")
    def get_resolved_layout(chapter_id: str) -> dict[str, Any]:
        """Return the resolved layout (AI layout + user overrides applied)."""
        proj = _get_project()
        l_path = p_dir / "artifacts" / f"layout.{chapter_id}.v1.json"
        l_art = _safe_load_artifact(l_path, LayoutArtifact)
        if not l_art:
            raise HTTPException(status_code=404, detail="Chưa có layout artifact.")
        resolved = resolve_layout(l_art, proj, chapter_id)
        _save_project(proj)  # resolve may update user panel anchor mappings
        return resolved.model_dump()

    # ------------------------------------------------------------------
    # Import Layer + Reconcile (Sprint 2) — anchor remap + orphaned UI
    # ------------------------------------------------------------------

    class ReconcilePayload(BaseModel):
        chapter_id: str
        new_version: int
        mode: str = "guided"  # guided | merge | reset

    @app.post("/api/reconcile/layout")
    def reconcile_layout_api(payload: ReconcilePayload) -> dict[str, Any]:
        """Explicit import of a new layout artifact version through reconcile.

        Anchors are remapped (exact ID -> IoU >= 0.6); unmatched anchors go to
        the orphaned list — overrides/clips attached to them are never lost.
        """
        proj = _get_project()
        store = AnchorStore(proj)
        artifacts_dir = p_dir / "artifacts"

        new_path = artifacts_dir / f"layout.{payload.chapter_id}.v{payload.new_version}.json"
        new_art = _safe_load_artifact(new_path, LayoutArtifact)
        if not new_art:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy {new_path.name}")

        old_version = proj.active_artifacts.get(payload.chapter_id, {}).get("layout", 0)
        old_art = None
        if old_version:
            old_path = artifacts_dir / f"layout.{payload.chapter_id}.v{old_version}.json"
            old_art = _safe_load_artifact(old_path, LayoutArtifact)

        try:
            result = reconcile_layout(
                old_art,
                new_art,
                store,
                proj.layout_overrides.get(payload.chapter_id),
                mode=payload.mode,  # type: ignore[arg-type]
            )
        except ImageSourceChangedError as e:
            return {
                "status": "requires_confirmation",
                "detail": str(e),
                "hint": "Gọi lại với mode='merge' để giữ anchors orphaned, hoặc mode='reset' để retire.",
            }

        proj.active_artifacts.setdefault(payload.chapter_id, {})["layout"] = payload.new_version
        _save_project(proj)
        return {
            "status": "success",
            "matched_exact": result.matched_exact,
            "remapped": [
                {"anchor": a, "old_id": o, "new_id": n, "iou": round(i, 3)}
                for a, o, n, i in result.remapped
            ],
            "orphaned": result.orphaned,
            "new_anchors": result.new_anchors,
            "warnings": result.warnings,
        }

    @app.get("/api/anchors/orphaned")
    def list_orphaned_anchors() -> dict[str, Any]:
        """Surface orphaned anchors (with attached overrides) for the review UI."""
        proj = _get_project()
        artifacts_dir = p_dir / "artifacts"
        live_ids: set[str] = set()
        for f in artifacts_dir.glob("layout.*.json") if artifacts_dir.exists() else []:
            art = _safe_load_artifact(f, LayoutArtifact)
            if art:
                live_ids.update(p.id for p in art.panels)
                for p in art.panels:
                    live_ids.update(tr.id for tr in p.text_regions)

        orphaned = []
        for aid, entry in proj.anchors.items():
            if entry.retired or entry.locked:
                continue
            if entry.kind == "panel" and live_ids and entry.current not in live_ids:
                orphaned.append(
                    {
                        "anchor": aid,
                        "kind": entry.kind,
                        "current": entry.current,
                        "history": entry.history,
                        "has_override": aid in proj.overrides,
                    }
                )
        return {"orphaned": orphaned, "total": len(orphaned)}

    class RemapAnchorPayload(BaseModel):
        anchor_id: str
        new_ai_id: str

    @app.post("/api/anchors/remap")
    def remap_anchor(payload: RemapAnchorPayload) -> dict[str, Any]:
        """Manually remap an orphaned anchor to a new AI ID (user decision)."""
        proj = _get_project()
        store = AnchorStore(proj)
        try:
            store.update_current(payload.anchor_id, payload.new_ai_id)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        _save_project(proj)
        return {"status": "success", "anchor": payload.anchor_id, "current": payload.new_ai_id}

    @app.post("/api/anchors/{anchor_id}/retire")
    def retire_anchor(anchor_id: str) -> dict[str, Any]:
        """Retire an anchor (never deleted — overrides remain recoverable)."""
        proj = _get_project()
        store = AnchorStore(proj)
        try:
            store.retire(anchor_id)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        _save_project(proj)
        return {"status": "success", "anchor": anchor_id, "retired": True}

    # ------------------------------------------------------------------
    # Timeline Resync (Sprint 4) — diff review + explicit confirmation
    # ------------------------------------------------------------------

    @app.get("/api/resync/{chapter_id}/diff")
    def resync_diff(chapter_id: str, version: int = Query(...)) -> dict[str, Any]:
        """Preview timeline changes if the given TTS version were applied."""
        proj = _get_project()
        t_path = p_dir / "artifacts" / f"tts.{chapter_id}.v{version}.json"
        t_art = _safe_load_artifact(t_path, TtsArtifact)
        if not t_art:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy {t_path.name}")
        return compute_resync_diff(proj, chapter_id, t_art).to_dict()

    class ResyncApplyPayload(BaseModel):
        chapter_id: str
        version: int

    @app.post("/api/resync/apply")
    def resync_apply(payload: ResyncApplyPayload) -> dict[str, Any]:
        """User-confirmed Resync: update duration snapshots + re-layout starts."""
        proj = _get_project()
        t_path = p_dir / "artifacts" / f"tts.{payload.chapter_id}.v{payload.version}.json"
        t_art = _safe_load_artifact(t_path, TtsArtifact)
        if not t_art:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy {t_path.name}")
        proj, diff = apply_resync(proj, payload.chapter_id, t_art)
        _save_project(proj)
        return {"status": "success", "applied": diff.to_dict()}

    # ------------------------------------------------------------------
    # CapCut Project Export (Sprint 3)
    # ------------------------------------------------------------------

    @app.post("/api/export-capcut/{chapter_id}")
    def export_capcut_project(chapter_id: str, capcut_version: str = Query("5.9.0")) -> dict[str, Any]:
        """Export a CapCut PC draft bundle from the deterministic RenderPlan."""
        proj = _get_project()
        artifacts_dir = p_dir / "artifacts"
        l_art = _safe_load_artifact(artifacts_dir / f"layout.{chapter_id}.v1.json", LayoutArtifact)
        active_tts_v = proj.active_artifacts.get(chapter_id, {}).get("tts", 1)
        t_art = _safe_load_artifact(artifacts_dir / f"tts.{chapter_id}.v{active_tts_v}.json", TtsArtifact)
        if not l_art:
            raise HTTPException(status_code=400, detail="Cần chạy Layout trước khi export CapCut.")

        if t_art and (not proj.sequence.video_tracks or not proj.sequence.audio_tracks):
            apply_sync_policy(proj, chapter_id, t_art)
            _save_project(proj)

        resolved = resolve_layout(l_art, proj, chapter_id)
        plan = RenderPlan.from_project(chapter_id, proj, resolved, t_art)
        exporter = CapCutProjectExporter(p_dir / "exports", capcut_version=capcut_version)
        return exporter.export(plan, project_dir=p_dir)

    # ------------------------------------------------------------------
    # Hardware & TTS providers info
    # ------------------------------------------------------------------

    @app.get("/api/hardware")
    def hardware_info() -> dict[str, Any]:
        """Detected hardware profile (NVENC, VRAM, RAM, gpu_layers auto)."""
        return detect_hardware().to_dict()

    @app.get("/api/tts/providers")
    def tts_providers() -> dict[str, Any]:
        """List registered TTS providers (multi-provider adapter)."""
        return {"providers": TtsProviderRegistry().providers(), "default": "edge", "fallback": "local-silence"}

    class SettingsPayload(BaseModel):
        capcut_dir: str | None = None
        capcut_drafts: str | None = None
        crop_margin: int | None = None

    @app.post("/api/settings")
    def update_settings(payload: SettingsPayload) -> dict[str, Any]:
        """Update system settings."""
        proj = _get_project()
        if payload.capcut_drafts:
            proj.settings.directories["capcut_drafts"] = payload.capcut_drafts
        _save_project(proj)
        return {"status": "success", "settings": proj.settings.model_dump()}

    @app.get("/media/{file_path:path}")
    def serve_media(file_path: str) -> FileResponse:
        """Stream local media files (images, WAV, MP4)."""
        target_file = (p_dir / file_path).resolve()
        if not target_file.exists():
            target_file = (p_dir / "tests" / "fixtures" / file_path).resolve()
        if not target_file.exists() and file_path.startswith("pages/"):
            parts = Path(file_path).parts
            if len(parts) >= 3:
                ch_id = parts[1]
                filename = parts[2]
                target_file = (p_dir / "tests" / "fixtures" / ch_id / "pages" / filename).resolve()

        if not target_file.exists():
            raise HTTPException(status_code=404, detail=f"File {file_path} not found")
        return FileResponse(str(target_file))

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        """Handle favicon.ico requests cleanly with 204 No Content."""
        return Response(status_code=204)

    @app.get("/", response_class=HTMLResponse)
    def serve_dashboard() -> HTMLResponse:
        """Serve Dashboard UI."""
        index_file = static_dir / "index.html"
        if not index_file.exists():
            return HTMLResponse("<h1>Dashboard loading...</h1>")
        return HTMLResponse(index_file.read_text(encoding="utf-8"))

    return app
