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
from manga_pipeline.core.schemas.artifact_layout import LayoutArtifact
from manga_pipeline.core.schemas.artifact_ocr import OcrArtifact
from manga_pipeline.core.schemas.artifact_script import ScriptArtifact
from manga_pipeline.core.schemas.artifact_tts import TtsArtifact
from manga_pipeline.core.schemas.project_schema import (
    AudioClip,
    AudioTrack,
    ProjectSchema,
    StoryMetadata,
    TextOverride,
    VideoClip,
    VideoTrack,
)
from manga_pipeline.engines.layout.manga_image_translator import MangaImageTranslatorLayoutEngine
from manga_pipeline.engines.ocr.manga_ocr_engine import MangaOcrEngine
from manga_pipeline.engines.protocols import LayoutRequest, OcrRequest, ScriptRequest, TtsRequest
from manga_pipeline.engines.script.manual_import import ManualScriptEngine
from manga_pipeline.engines.tts.edge_tts_engine import EdgeTtsEngine
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
            raise HTTPException(status_code=400, detail=str(e))

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

    def _write_artifact_atomically(path: Path, json_str: str) -> None:
        """Write artifact safely directly to file with retry on Windows."""
        path.parent.mkdir(parents=True, exist_ok=True)
        import time
        for attempt in range(5):
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(json_str)
                    f.flush()
                return
            except OSError:
                time.sleep(0.1)

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

            ocr_engine = MangaOcrEngine()
            ocr_res = ocr_engine.extract(
                OcrRequest(chapter_id=chapter_id, layout_artifact=layout_art, pages_dir=pages_dir)
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

            tts_engine = EdgeTtsEngine()
            tts_res = tts_engine.synthesize(
                TtsRequest(
                    chapter_id=chapter_id,
                    script_artifact=script_art,
                    audio_output_dir=p_dir / "audio",
                    artifact_version=1,
                    voice_ref=req.voice,
                )
            )
            t_path = artifacts_dir / f"tts.{chapter_id}.v1.json"
            _write_artifact_atomically(t_path, tts_res.artifact.model_dump_json(indent=2))
            project.active_artifacts[chapter_id]["tts"] = 1
            _save_project(project)

        if stage in {"render", "run_all"}:
            l_path = artifacts_dir / f"layout.{chapter_id}.v1.json"
            t_path = artifacts_dir / f"tts.{chapter_id}.v1.json"
            l_art = _safe_load_artifact(l_path, LayoutArtifact)
            t_art = _safe_load_artifact(t_path, TtsArtifact)

            if not l_art or not t_art:
                raise HTTPException(status_code=400, detail="Cần hoàn thành Layout và TTS trước khi Render video.")

            panel_anchors = list(store.get_by_kind("panel").keys())
            unit_anchors = list(store.get_by_kind("unit").keys())

            if not project.sequence.video_tracks and panel_anchors:
                vclips = [
                    VideoClip(panel_ref=pa, start_ms=i * 3000, duration_ms=3000)
                    for i, pa in enumerate(panel_anchors)
                ]
                project.sequence.video_tracks = [VideoTrack(clips=vclips)]

            if not project.sequence.audio_tracks and unit_anchors:
                aclips = [
                    AudioClip(audio_ref=sa, start_ms=i * 3000, synced_duration_ms=2500)
                    for i, sa in enumerate(unit_anchors)
                ]
                project.sequence.audio_tracks = [AudioTrack(clips=aclips)]

            _save_project(project)

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
