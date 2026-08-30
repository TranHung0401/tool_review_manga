"""Sprint 3: CapCut Project Exporter tests (pinned versions, report, degrade)."""

import json
from pathlib import Path

from manga_pipeline.render.capcut_exporter import CapCutProjectExporter
from manga_pipeline.render.plan import (
    RenderPlan,
    RenderPlanAudioClip,
    RenderPlanVideoClip,
    ResolvedTransform,
    ResolvedVisualEffect,
)


def _plan() -> RenderPlan:
    return RenderPlan(
        chapter_id="ch01",
        video_clips=[
            RenderPlanVideoClip(
                clip_id="vclip_0_0",
                panel_anchor="pa_000001",
                resolved_panel_id="p_aaa111222333",
                source_image="pages/001.png",
                source_bbox=[10, 20, 700, 400],
                start_ms=0,
                duration_ms=5400,
                transform=ResolvedTransform(type="zoom_in", scale_start=1.0, scale_end=1.2),
                visual_effects=[ResolvedVisualEffect(effect_type="fade", duration_ms=500)],
            ),
            RenderPlanVideoClip(
                clip_id="vclip_0_1",
                panel_anchor="pa_000002",
                resolved_panel_id="p_bbb444555666",
                source_image="pages/001.png",
                source_bbox=[10, 500, 700, 400],
                start_ms=5400,
                duration_ms=1500,
                visual_effects=[ResolvedVisualEffect(effect_type="hologram_warp", duration_ms=300)],
            ),
        ],
        audio_clips=[
            RenderPlanAudioClip(
                clip_id="aclip_0_0",
                unit_anchor="sa_000001",
                resolved_unit_id="s_unit00000001",
                audio_file="audio/ch01_s_unit00000001.v1.wav",
                start_ms=0,
                duration_ms=5100,
            )
        ],
        total_duration_ms=6900,
    )


def test_export_creates_draft_bundle(tmp_path: Path) -> None:
    exporter = CapCutProjectExporter(tmp_path, capcut_version="5.9.0")
    report = exporter.export(_plan())

    bundle = tmp_path / "ch01_capcut"
    assert (bundle / "draft_content.json").exists()
    assert (bundle / "draft_meta_info.json").exists()
    assert (bundle / "export_report.json").exists()
    assert report["status"] == "success"

    content = json.loads((bundle / "draft_content.json").read_text(encoding="utf-8"))
    # Microsecond timeline
    assert content["duration"] == 6900 * 1000
    video_track = next(t for t in content["tracks"] if t["type"] == "video")
    audio_track = next(t for t in content["tracks"] if t["type"] == "audio")
    assert len(video_track["segments"]) == 2
    assert len(audio_track["segments"]) == 1
    assert video_track["segments"][0]["target_timerange"]["duration"] == 5400 * 1000

    # Crop carries the panel bbox
    mat = content["materials"]["videos"][0]
    assert mat["crop"]["upper_left_x"] == 10
    assert mat["crop"]["lower_right_x"] == 710


def test_effect_mapping_and_degrade_report(tmp_path: Path) -> None:
    exporter = CapCutProjectExporter(tmp_path)
    report = exporter.export(_plan())

    # zoom_in keyframe + fade mapped; hologram_warp degraded
    assert report["effects_total"] == 3
    assert report["effects_mapped"] == 2
    assert len(report["effects_degraded"]) == 1
    assert report["effects_degraded"][0]["effect"] == "hologram_warp"
    assert "fallback" in report  # MP4+SRT fallback always documented


def test_unpinned_version_warns_best_effort(tmp_path: Path) -> None:
    exporter = CapCutProjectExporter(tmp_path, capcut_version="9.9.9")
    report = exporter.export(_plan())
    assert report["status"] == "success_with_warnings"
    assert any("9.9.9" in w for w in report["warnings"])
    # Bundle still produced (best-effort)
    assert (tmp_path / "ch01_capcut" / "draft_content.json").exists()


def test_zoom_serialized_as_scale_keyframes(tmp_path: Path) -> None:
    exporter = CapCutProjectExporter(tmp_path)
    exporter.export(_plan())
    content = json.loads((tmp_path / "ch01_capcut" / "draft_content.json").read_text(encoding="utf-8"))
    seg = next(t for t in content["tracks"] if t["type"] == "video")["segments"][0]
    kfs = seg["keyframes"]
    assert len(kfs) == 2
    assert kfs[0]["value"] == 1.0
    assert kfs[1]["value"] == 1.2
    assert kfs[1]["time_offset"] == 5400 * 1000


def test_no_capcut_reference_leaks_into_core() -> None:
    """Render Plan core must stay target-neutral (architecture §8)."""
    import inspect

    from manga_pipeline.render import plan as plan_module

    src = inspect.getsource(plan_module).lower()
    assert "capcut" not in src
    assert "draft_content" not in src
