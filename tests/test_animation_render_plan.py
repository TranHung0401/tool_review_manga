"""Golden tests for Render Plan Animation Templates and Motion resolution."""

import json

from manga_pipeline.core.schemas.artifact_layout import LayoutArtifact, LayoutManifest, Panel, PanelSource
from manga_pipeline.core.schemas.artifact_tts import TtsArtifact, TtsClip, TtsDependsOn, TtsManifest
from manga_pipeline.core.schemas.project_schema import (
    AnchorEntry,
    AnimationTemplate,
    AudioClip,
    AudioTrack,
    ProjectSchema,
    SequenceModel,
    StoryMetadata,
    VideoClip,
    VideoTrack,
)
from manga_pipeline.render.plan import RenderPlan


def test_animation_template_resolution_in_render_plan() -> None:
    """Verify animation template (zoom_in + fade) resolves deterministically into RenderPlan."""
    project = ProjectSchema(
        story=StoryMetadata(title="Test Story", chapters=["ch01"]),
        anchors={
            "pa_000001": AnchorEntry(kind="panel", current="p_001", history=["p_001"]),
            "sa_000001": AnchorEntry(kind="unit", current="s_001", history=["s_001"]),
        },
        animation_templates={
            "tpl_slow_zoom": AnimationTemplate(
                in_animation={"type": "fade", "duration_ms": 500},
                keyframe={"type": "zoom_in", "scale_start": 1.0, "scale_end": 1.2, "anchor": "center"},
                out_animation={"type": "fade", "duration_ms": 300},
            )
        },
        sequence=SequenceModel(
            video_tracks=[
                VideoTrack(
                    clips=[
                        VideoClip(
                            panel_ref="pa_000001",
                            start_ms=0,
                            duration_ms=5000,
                            visual_effects={"template_ref": "tpl_slow_zoom"},
                        )
                    ]
                )
            ],
            audio_tracks=[
                AudioTrack(
                    clips=[
                        AudioClip(
                            audio_ref="sa_000001",
                            start_ms=0,
                            synced_duration_ms=4500,
                        )
                    ]
                )
            ],
        ),
    )

    layout = LayoutArtifact(
        chapter_id="ch01",
        artifact_version=1,
        manifest=LayoutManifest(engine="test_engine", engine_version="1.0.0", timestamp="2026-08-30T00:00:00Z"),
        panels=[
            Panel(
                id="p_001",
                source=PanelSource(image="pages/001.png", bbox=[100, 100, 800, 600]),
                reading_order=1,
            )
        ],
    )

    tts = TtsArtifact(
        chapter_id="ch01",
        artifact_version=1,
        depends_on=TtsDependsOn(stage="script", artifact_version=1),
        manifest=TtsManifest(provider="edge-tts", voice_ref="vi-VN-HoaiMyNeural", timestamp="2026-08-30T00:00:00Z"),
        clips=[TtsClip(unit_id="s_001", file="audio/ch01_s_001.v1.wav", duration_ms=4500)],
    )

    plan = RenderPlan.from_project("ch01", project, layout, tts)

    assert len(plan.video_clips) == 1
    vclip = plan.video_clips[0]
    assert vclip.transform.type == "zoom_in"
    assert vclip.transform.scale_start == 1.0
    assert vclip.transform.scale_end == 1.2
    assert len(vclip.visual_effects) == 2
    assert vclip.visual_effects[0].effect_type == "fade"
    assert vclip.visual_effects[0].duration_ms == 500

    # Ensure JSON serializes cleanly and deterministically
    plan_json = plan.to_json()
    loaded = json.loads(plan_json)
    assert loaded["chapter_id"] == "ch01"
    assert loaded["video_clips"][0]["transform"]["type"] == "zoom_in"
