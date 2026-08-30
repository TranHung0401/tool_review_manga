"""CapCut Project Exporter (Sprint 3 — CapCutProjectAdapter).

Serializes a deterministic RenderPlan into a CapCut PC draft bundle.

Risk clauses from architecture.md are honoured:
- The internal CapCut PC format is version-specific and undocumented. This
  adapter is built against fixtures observed from real CapCut PC drafts
  (draft_content.json + draft_meta_info.json) and pins the versions it was
  validated against in ``SUPPORTED_CAPCUT_VERSIONS``.
- Target versions outside the pinned list produce a warning and best-effort
  output.
- Effects that cannot be mapped to CapCut vocabulary degrade gracefully and
  are listed in ``export_report.json``; the FFmpeg MP4 + SRT path remains the
  always-available fallback.
- CapCut format changes are absorbed HERE — never in RenderPlan or core.
"""

import json
import uuid
from pathlib import Path
from typing import Any

from manga_pipeline.render.plan import RenderPlan, RenderPlanVideoClip

# Neutral effect vocabulary -> CapCut animation identifiers.
# Built from fixture drafts; anything absent degrades with a report entry.
_CAPCUT_IN_ANIMATION_MAP: dict[str, dict[str, Any]] = {
    "fade": {"name": "渐显", "effect_id": "faded_in", "duration_scale": 1.0},
    "slide_left": {"name": "向左滑动", "effect_id": "slide_left_in", "duration_scale": 1.0},
    "slide_right": {"name": "向右滑动", "effect_id": "slide_right_in", "duration_scale": 1.0},
}

_CAPCUT_KEYFRAME_SUPPORTED = {"zoom_in", "zoom_out", "pan", "static"}


def _us(ms: int) -> int:
    """CapCut drafts use microseconds."""
    return int(ms) * 1000


def _cc_uuid() -> str:
    return str(uuid.uuid4()).upper()


class CapCutProjectExporter:
    """Serializes deterministic RenderPlan to CapCut PC project bundles."""

    SUPPORTED_CAPCUT_VERSIONS = ["5.0.0", "5.1.0", "5.9.0"]
    DRAFT_FORMAT_VERSION = "110.0.0"

    def __init__(self, output_dir: Path, capcut_version: str = "5.9.0"):
        self.output_dir = output_dir
        self.capcut_version = capcut_version

    # ------------------------------------------------------------------
    def export(self, plan: RenderPlan, project_dir: Path | None = None) -> dict[str, Any]:
        """Export RenderPlan as a CapCut draft bundle + export report.

        Output layout::

            {output_dir}/{chapter_id}_capcut/
            ├── draft_content.json      # tracks / segments / materials
            ├── draft_meta_info.json    # bundle metadata
            └── export_report.json      # mapping results + degradations
        """
        bundle_dir = self.output_dir / f"{plan.chapter_id}_capcut"
        bundle_dir.mkdir(parents=True, exist_ok=True)

        warnings: list[str] = []
        degraded_effects: list[dict[str, Any]] = []

        if self.capcut_version not in self.SUPPORTED_CAPCUT_VERSIONS:
            warnings.append(
                f"CapCut version '{self.capcut_version}' is not in pinned supported list "
                f"{self.SUPPORTED_CAPCUT_VERSIONS}. Export is best-effort; "
                "verify the draft opens correctly."
            )

        video_materials: list[dict[str, Any]] = []
        audio_materials: list[dict[str, Any]] = []
        video_segments: list[dict[str, Any]] = []
        audio_segments: list[dict[str, Any]] = []
        mapped_effects = 0
        total_effects = 0

        base = project_dir.resolve() if project_dir else Path(".")

        for clip in plan.video_clips:
            material_id = _cc_uuid()
            src = str(base / clip.source_image) if clip.source_image else ""
            video_materials.append(
                {
                    "id": material_id,
                    "type": "photo",
                    "path": src,
                    "duration": 10800000000,
                    "width": clip.source_bbox[2] if clip.source_bbox else 1920,
                    "height": clip.source_bbox[3] if clip.source_bbox else 1080,
                    "crop": {
                        "upper_left_x": clip.source_bbox[0] if clip.source_bbox else 0,
                        "upper_left_y": clip.source_bbox[1] if clip.source_bbox else 0,
                        "lower_right_x": (clip.source_bbox[0] + clip.source_bbox[2]) if clip.source_bbox else 1920,
                        "lower_right_y": (clip.source_bbox[1] + clip.source_bbox[3]) if clip.source_bbox else 1080,
                    },
                }
            )

            segment: dict[str, Any] = {
                "id": _cc_uuid(),
                "material_id": material_id,
                "source_timerange": {"start": _us(clip.in_point_ms), "duration": _us(clip.duration_ms)},
                "target_timerange": {"start": _us(clip.start_ms), "duration": _us(clip.duration_ms)},
                "extra_material_refs": [],
                "clip": {
                    "scale": {"x": clip.transform.scale_start, "y": clip.transform.scale_start},
                    "transform": {"x": 0.0, "y": 0.0},
                },
                "animations": [],
                "keyframes": [],
            }

            # Keyframe transform (zoom/pan) mapping
            if clip.transform.type not in _CAPCUT_KEYFRAME_SUPPORTED:
                total_effects += 1
                degraded_effects.append(
                    {
                        "clip_id": clip.clip_id,
                        "effect": clip.transform.type,
                        "reason": "keyframe type has no CapCut mapping; exported as static",
                    }
                )
            elif clip.transform.type != "static":
                total_effects += 1
                mapped_effects += 1
                segment["keyframes"] = self._build_scale_keyframes(clip)

            # In/out animation mapping
            for eff in clip.visual_effects:
                total_effects += 1
                mapping = _CAPCUT_IN_ANIMATION_MAP.get(eff.effect_type)
                if mapping:
                    mapped_effects += 1
                    segment["animations"].append(
                        {
                            "id": _cc_uuid(),
                            "name": mapping["name"],
                            "effect_id": mapping["effect_id"],
                            "type": "in",
                            "duration": _us(eff.duration_ms),
                        }
                    )
                else:
                    degraded_effects.append(
                        {
                            "clip_id": clip.clip_id,
                            "effect": eff.effect_type,
                            "reason": "no CapCut animation mapping; dropped in export",
                        }
                    )

            video_segments.append(segment)

        for a_clip in plan.audio_clips:
            material_id = _cc_uuid()
            src = str(base / a_clip.audio_file) if a_clip.audio_file else ""
            audio_materials.append(
                {
                    "id": material_id,
                    "type": "extract_music",
                    "path": src,
                    "duration": _us(a_clip.duration_ms),
                }
            )
            audio_segments.append(
                {
                    "id": _cc_uuid(),
                    "material_id": material_id,
                    "source_timerange": {"start": 0, "duration": _us(a_clip.duration_ms)},
                    "target_timerange": {"start": _us(a_clip.start_ms), "duration": _us(a_clip.duration_ms)},
                }
            )

        draft_content = {
            "version": self.DRAFT_FORMAT_VERSION,
            "app_version": self.capcut_version,
            "id": _cc_uuid(),
            "duration": _us(plan.total_duration_ms),
            "fps": 30.0,
            "canvas_config": {"width": 1920, "height": 1080, "ratio": "16:9"},
            "materials": {
                "videos": video_materials,
                "audios": audio_materials,
                "texts": [],
                "stickers": [],
            },
            "tracks": [
                {"id": _cc_uuid(), "type": "video", "segments": video_segments},
                {"id": _cc_uuid(), "type": "audio", "segments": audio_segments},
            ],
        }

        draft_meta = {
            "draft_name": f"manga_{plan.chapter_id}",
            "draft_id": draft_content["id"],
            "app_version": self.capcut_version,
            "generator": "manga-pipeline CapCutProjectExporter",
            "source_render_plan_schema": plan.schema_version,
        }

        report = {
            "status": "success" if not warnings else "success_with_warnings",
            "chapter_id": plan.chapter_id,
            "bundle_dir": str(bundle_dir),
            "capcut_version_target": self.capcut_version,
            "supported_versions": self.SUPPORTED_CAPCUT_VERSIONS,
            "clips_count": len(plan.video_clips),
            "audio_clips_count": len(plan.audio_clips),
            "effects_total": total_effects,
            "effects_mapped": mapped_effects,
            "effects_degraded": degraded_effects,
            "warnings": warnings,
            "fallback": "FFmpeg MP4 + SRT export remains available via the render/export stages.",
        }

        self._write_json(bundle_dir / "draft_content.json", draft_content)
        self._write_json(bundle_dir / "draft_meta_info.json", draft_meta)
        self._write_json(bundle_dir / "export_report.json", report)
        return report

    # ------------------------------------------------------------------
    @staticmethod
    def _build_scale_keyframes(clip: RenderPlanVideoClip) -> list[dict[str, Any]]:
        """Serialize zoom transform as CapCut uniform-scale keyframes."""
        return [
            {
                "id": _cc_uuid(),
                "property": "KFTypeScaleX",
                "time_offset": 0,
                "value": clip.transform.scale_start,
            },
            {
                "id": _cc_uuid(),
                "property": "KFTypeScaleX",
                "time_offset": _us(clip.duration_ms),
                "value": clip.transform.scale_end,
            },
        ]

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=True)
        tmp.replace(path)
