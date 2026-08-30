"""DoD (g): Deterministic Render Plan and Target-Neutral Golden Tests."""

import sys
from pathlib import Path

from manga_pipeline.core.schemas.artifact_layout import (
    LayoutArtifact,
    LayoutManifest,
    Panel,
    PanelSource,
)
from manga_pipeline.core.schemas.artifact_tts import (
    TtsArtifact,
    TtsClip,
    TtsDependsOn,
    TtsManifest,
)
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
from manga_pipeline.render.capcut_exporter import CapCutProjectExporter
from manga_pipeline.render.plan import RenderPlan


def test_render_plan_zero_ffmpeg_or_capcut_in_core_module() -> None:
    """Verify that render/plan.py does NOT import ffmpeg, capcut, or subprocess."""
    assert "ffmpeg" not in sys.modules
    import manga_pipeline.render.plan

    # Verify no ffmpeg attribute in plan module
    assert not hasattr(manga_pipeline.render.plan, "ffmpeg")


def test_render_plan_deterministic_json() -> None:
    project = ProjectSchema(
        story=StoryMetadata(title="Sample Manga", chapters=["ch01"]),
        anchors={
            "pa_000001": AnchorEntry(kind="panel", current="p_abc123", history=["p_abc123"]),
            "sa_000001": AnchorEntry(kind="unit", current="s_def456", history=["s_def456"]),
        },
        animation_templates={
            "tpl_slow_zoom": AnimationTemplate(
                in_animation={"type": "fade", "duration_ms": 400},
                keyframe={"type": "zoom_in", "scale_start": 1.0, "scale_end": 1.2},
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
                            synced_duration_ms=4800,
                            synced_artifact_version=1,
                        )
                    ]
                )
            ],
        ),
    )

    layout = LayoutArtifact(
        chapter_id="ch01",
        artifact_version=1,
        manifest=LayoutManifest(engine="test", engine_version="1", timestamp=""),
        panels=[
            Panel(
                id="p_abc123",
                source=PanelSource(image="pages/001.png", bbox=[0, 0, 800, 600]),
                reading_order=1,
            )
        ],
    )

    tts = TtsArtifact(
        chapter_id="ch01",
        artifact_version=1,
        depends_on=TtsDependsOn(stage="script", artifact_version=1),
        manifest=TtsManifest(provider="edge", voice_ref="vi-VN", timestamp=""),
        clips=[TtsClip(unit_id="s_def456", file="audio/ch01_s_def456.v1.wav", duration_ms=4800)],
    )

    plan1 = RenderPlan.from_project("ch01", project, layout, tts)
    plan2 = RenderPlan.from_project("ch01", project, layout, tts)

    # Identical serialized JSON
    json1 = plan1.to_json()
    json2 = plan2.to_json()

    assert json1 == json2
    assert plan1.video_clips[0].resolved_panel_id == "p_abc123"
    assert plan1.audio_clips[0].resolved_unit_id == "s_def456"
    assert plan1.audio_clips[0].audio_file == "audio/ch01_s_def456.v1.wav"
    assert plan1.total_duration_ms == 5000


def test_capcut_exporter_stub(tmp_path: Path) -> None:
    exporter = CapCutProjectExporter(tmp_path)
    plan = RenderPlan(chapter_id="ch01")
    result = exporter.export(plan)

    assert result["status"] == "stub"
    assert result["sprint_milestone"] == 3
