"""SRT subtitle exporter — fallback CapCut-ready output (architecture.md §8).

Exports:
- exports/{chapter_id}/subtitles.srt   — SRT file from script+TTS timings
- exports/{chapter_id}/panels/          — CROPPED individual panel images (for 1:1 CapCut timeline pairing)
- exports/{chapter_id}/audio/           — copied WAV clips (numbered sequentially)
- exports/{chapter_id}/pages/           — source images (optional)
- exports/{chapter_id}/export_report.json

Usage: SRTExporter(project_dir).export(chapter_id, script_art, tts_art, layout_art=layout_art)
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from manga_pipeline.core.anchors import AnchorStore
from manga_pipeline.core.schemas.artifact_layout import LayoutArtifact
from manga_pipeline.core.schemas.artifact_script import ScriptArtifact
from manga_pipeline.core.schemas.artifact_tts import TtsArtifact
from manga_pipeline.core.schemas.project_schema import ProjectSchema


def _ms_to_srt_time(ms: int) -> str:
    """Convert milliseconds to SRT timestamp HH:MM:SS,mmm."""
    h = ms // 3_600_000
    ms %= 3_600_000
    m = ms // 60_000
    ms %= 60_000
    s = ms // 1_000
    ms %= 1_000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class SRTExporter:
    """Export SRT subtitle + audio + cropped panels bundle from TTS, Script and Layout artifacts."""

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir

    def export(
        self,
        chapter_id: str,
        script_art: ScriptArtifact,
        tts_art: TtsArtifact,
        pages_dir: Path | None = None,
        project: ProjectSchema | None = None,
        layout_art: LayoutArtifact | None = None,
    ) -> dict[str, Any]:
        """
        Build exports/{chapter_id}/ bundle:
          - subtitles.srt
          - panels/ (cropped individual panel images numbered 001_panel.png, 002_panel.png...)
          - audio/  (copied WAV clips, both original and numbered 001_audio.wav...)
          - pages/  (source full-page images)
          - export_report.json

        Returns export_report dict.
        """
        export_dir = self.project_dir / "exports" / chapter_id
        export_dir.mkdir(parents=True, exist_ok=True)

        audio_out = export_dir / "audio"
        audio_out.mkdir(exist_ok=True)

        panels_out = export_dir / "panels"
        panels_out.mkdir(exist_ok=True)

        # Build unit_id → text map and unit_id → panel_id map from script
        unit_texts: dict[str, str] = {}
        unit_panel_ids: dict[str, str] = {}
        store = AnchorStore(project) if project else None
        for u in script_art.units:
            text_val = u.text
            if project and store:
                anchor = store.find_by_ai_id(u.id, kind="unit")
                if anchor and anchor in project.overrides:
                    override_val = project.overrides[anchor].text
                    if override_val is not None:
                        text_val = override_val
            unit_texts[u.id] = text_val
            if u.panel_id:
                unit_panel_ids[u.id] = u.panel_id

        # Build panel_id → panel object map from layout_art
        panel_map: dict[str, Any] = {}
        if layout_art:
            for p in layout_art.panels:
                panel_map[p.id] = p

        # Cache opened PIL images to avoid re-opening the same page multiple times
        opened_images: dict[str, Image.Image] = {}

        def _get_page_image(image_path_str: str) -> Image.Image | None:
            if image_path_str in opened_images:
                return opened_images[image_path_str]
            candidates = [
                self.project_dir / image_path_str,
                self.project_dir / "pages" / chapter_id / Path(image_path_str).name,
                self.project_dir / "tests" / "fixtures" / chapter_id / "pages" / Path(image_path_str).name,
            ]
            if pages_dir:
                candidates.append(pages_dir / Path(image_path_str).name)
            for cand in candidates:
                if cand.exists():
                    try:
                        img = Image.open(cand).convert("RGB")
                        opened_images[image_path_str] = img
                        return img
                    except Exception:
                        pass
            return None

        # Build SRT entries, crop panels, and copy audio clips
        srt_lines: list[str] = []
        cursor_ms = 0
        copied_audio: list[str] = []
        cropped_panels: list[str] = []
        paired_items: list[dict[str, Any]] = []

        for idx, clip in enumerate(tts_art.clips, start=1):
            start_ms = cursor_ms
            end_ms = cursor_ms + clip.duration_ms
            text = unit_texts.get(clip.unit_id, f"[unit: {clip.unit_id}]")

            srt_lines.append(str(idx))
            srt_lines.append(f"{_ms_to_srt_time(start_ms)} --> {_ms_to_srt_time(end_ms)}")
            srt_lines.append(text)
            srt_lines.append("")  # blank separator

            cursor_ms = end_ms

            # 1. Audio file copying & sequential numbering
            src_audio = self.project_dir / clip.file
            if not src_audio.exists():
                src_audio = self.project_dir / "tests" / "fixtures" / clip.file
            audio_seq_name = f"{idx:03d}_audio.wav"
            if src_audio.exists():
                # Copy original name and sequence name
                dst_audio = audio_out / src_audio.name
                shutil.copy2(src_audio, dst_audio)
                dst_seq_audio = audio_out / audio_seq_name
                shutil.copy2(src_audio, dst_seq_audio)
                copied_audio.append(audio_seq_name)

            # 2. Panel image cropping (1:1 with clip / subtitle)
            panel_seq_name = f"{idx:03d}_panel.png"
            panel_id = unit_panel_ids.get(clip.unit_id)
            panel_obj = panel_map.get(panel_id) if panel_id else None
            # If no direct unit panel mapping, fallback to index-based panel if available
            if not panel_obj and layout_art and idx - 1 < len(layout_art.panels):
                panel_obj = layout_art.panels[idx - 1]

            if panel_obj:
                img = _get_page_image(panel_obj.source.image)
                if img:
                    [x, y, pw, ph] = panel_obj.source.bbox
                    # Clamp bounding box within image boundaries
                    iw, ih = img.size
                    x1 = max(0, min(x, iw - 1))
                    y1 = max(0, min(y, ih - 1))
                    x2 = max(x1 + 10, min(x + pw, iw))
                    y2 = max(y1 + 10, min(y + ph, ih))
                    crop_img = img.crop((x1, y1, x2, y2))
                    dst_panel = panels_out / panel_seq_name
                    crop_img.save(dst_panel, format="PNG")
                    cropped_panels.append(panel_seq_name)

            paired_items.append({
                "index": idx,
                "panel_image": f"panels/{panel_seq_name}",
                "audio_file": f"audio/{audio_seq_name}",
                "duration_ms": clip.duration_ms,
                "timestamp": f"{_ms_to_srt_time(start_ms)} --> {_ms_to_srt_time(end_ms)}",
                "text": text,
            })

        # Close all cached images
        for img in opened_images.values():
            img.close()

        # Write SRT
        srt_path = export_dir / "subtitles.srt"
        srt_path.write_text("\n".join(srt_lines), encoding="utf-8")

        # Copy original source pages as reference
        copied_pages: list[str] = []
        pages_out = export_dir / "pages"
        if pages_dir and pages_dir.exists():
            pages_out.mkdir(exist_ok=True)
            for img_file in sorted(pages_dir.iterdir()):
                if img_file.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                    shutil.copy2(img_file, pages_out / img_file.name)
                    copied_pages.append(img_file.name)

        # Export report
        report = {
            "status": "success",
            "chapter_id": chapter_id,
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "srt_file": str(srt_path.relative_to(self.project_dir)),
            "total_duration_ms": cursor_ms,
            "clips_count": len(tts_art.clips),
            "panels_cropped": len(cropped_panels),
            "audio_copied": len(copied_audio),
            "pages_copied": len(copied_pages),
            "export_dir": str(export_dir),
            "items": paired_items,
            "capcut_instructions": (
                "HƯỚNG DẪN DỰNG CAPCUT CỰC NHANH (1:1 PAIRING):\n"
                "1. Mở CapCut PC → New Project.\n"
                "2. Kéo toàn bộ ảnh trong thư mục 'panels/' (001_panel.png, 002_panel.png...) thả vào Timeline Video.\n"
                "3. Kéo toàn bộ âm thanh trong thư mục 'audio/' (001_audio.wav, 002_audio.wav...) thả vào Timeline Audio.\n"
                "4. Import file 'subtitles.srt' vào CapCut (Text → Local Captions → Import SRT).\n"
                "👉 Toàn bộ Khung tranh cắt nhỏ, Âm thanh và Phụ đề đã được khớp thứ tự 1:1 từ đầu đến cuối!"
            ),
        }
        report_path = export_dir / "export_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        return report
