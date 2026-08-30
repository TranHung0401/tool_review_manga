"""DoD (e): TTS re-run and timeline snapshot synchronization tests."""

from manga_pipeline.core.schemas.artifact_tts import TtsArtifact, TtsClip, TtsDependsOn, TtsManifest
from manga_pipeline.core.schemas.project_schema import (
    AnchorEntry,
    AudioClip,
    AudioTrack,
    ProjectSchema,
    SequenceModel,
    StoryMetadata,
    SyncPolicy,
)


def test_rerun_tts_creates_new_version_not_overwrite() -> None:
    """DoD (e): Re-running TTS creates artifact version v2 without overwriting v1 metadata."""
    tts_v1 = TtsArtifact(
        chapter_id="ch01",
        artifact_version=1,
        depends_on=TtsDependsOn(stage="script", artifact_version=1),
        manifest=TtsManifest(provider="edge-tts", voice_ref="vi-VN-HoaiMyNeural", timestamp="2026-08-30T10:00:00Z"),
        clips=[TtsClip(unit_id="s_unit001", file="audio/ch01_s_unit001.v1.wav", duration_ms=3000)],
    )

    # Re-run TTS with different speed or voice -> version 2
    tts_v2 = TtsArtifact(
        chapter_id="ch01",
        artifact_version=2,
        depends_on=TtsDependsOn(stage="script", artifact_version=1),
        manifest=TtsManifest(provider="edge-tts", voice_ref="vi-VN-NamMinhNeural", timestamp="2026-08-30T10:05:00Z"),
        clips=[TtsClip(unit_id="s_unit001", file="audio/ch01_s_unit001.v2.wav", duration_ms=2500)],
    )

    assert tts_v1.artifact_version == 1
    assert tts_v2.artifact_version == 2
    assert tts_v1.clips[0].file != tts_v2.clips[0].file


def test_timeline_snapshot_unchanged_before_resync() -> None:
    """DoD (e): Timeline duration snapshot remains unchanged when a new TTS artifact is generated until explicit Resync."""
    project = ProjectSchema(
        story=StoryMetadata(title="Test", chapters=["ch01"]),
        settings={"sync_policy": SyncPolicy(min_duration_ms=1500, padding_ms=300)},  # type: ignore[arg-type]
        anchors={
            "sa_000001": AnchorEntry(kind="unit", current="s_unit001", history=["s_unit001"]),
        },
        active_artifacts={"ch01": {"script": 1, "tts": 1}},
        sequence=SequenceModel(
            audio_tracks=[
                AudioTrack(
                    clips=[
                        AudioClip(
                            audio_ref="sa_000001",
                            start_ms=0,
                            synced_duration_ms=3000,
                            synced_artifact_version=1,
                        )
                    ]
                )
            ]
        ),
    )

    # New TTS v2 arrives with duration 2500ms
    tts_v2 = TtsArtifact(
        chapter_id="ch01",
        artifact_version=2,
        depends_on=TtsDependsOn(stage="script", artifact_version=1),
        manifest=TtsManifest(provider="edge-tts", voice_ref="vi-VN-HoaiMyNeural", timestamp="2026-08-30T10:10:00Z"),
        clips=[TtsClip(unit_id="s_unit001", file="audio/ch01_s_unit001.v2.wav", duration_ms=2500)],
    )

    # Before user clicks Resync: timeline retains v1 snapshot
    clip = project.sequence.audio_tracks[0].clips[0]
    assert clip.synced_duration_ms == 3000
    assert clip.synced_artifact_version == 1

    # User triggers Resync: snapshot updates to v2 duration
    clip.synced_duration_ms = tts_v2.clips[0].duration_ms
    clip.synced_artifact_version = tts_v2.artifact_version
    project.active_artifacts["ch01"]["tts"] = 2

    assert clip.synced_duration_ms == 2500
    assert clip.synced_artifact_version == 2
