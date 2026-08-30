"""Sprint 4: sync policy + Resync tests.

Rule: clip.duration_ms = max(min_duration_ms, audio.duration_ms + padding_ms)
Re-run TTS never moves the timeline until the user applies Resync.
"""

from manga_pipeline.core.anchors import AnchorStore
from manga_pipeline.core.schemas.artifact_tts import TtsArtifact, TtsClip, TtsDependsOn, TtsManifest
from manga_pipeline.core.schemas.project_schema import ProjectSchema, StoryMetadata
from manga_pipeline.pipeline.sync import (
    apply_resync,
    apply_sync_policy,
    compute_resync_diff,
    compute_synced_duration,
)


def _make_tts(version: int, durations: dict[str, int]) -> TtsArtifact:
    return TtsArtifact(
        chapter_id="ch01",
        artifact_version=version,
        depends_on=TtsDependsOn(stage="script", artifact_version=1),
        manifest=TtsManifest(provider="edge-tts", voice_ref="vi-VN-HoaiMyNeural", timestamp="2026-08-30T10:00:00Z"),
        clips=[
            TtsClip(unit_id=uid, file=f"audio/ch01_{uid}.v{version}.wav", duration_ms=ms)
            for uid, ms in durations.items()
        ],
    )


def _make_project_with_panels(n: int) -> ProjectSchema:
    proj = ProjectSchema(story=StoryMetadata(title="T", chapters=["ch01"]))
    store = AnchorStore(proj)
    for i in range(n):
        store.create_anchor("panel", f"p_panel{i:04d}0000")
    return proj


def test_sync_formula() -> None:
    """duration = max(min_duration_ms, audio + padding)."""
    assert compute_synced_duration(5100, 1500, 300) == 5400
    assert compute_synced_duration(200, 1500, 300) == 1500  # min floor wins
    assert compute_synced_duration(1200, 1500, 300) == 1500
    assert compute_synced_duration(1201, 1500, 300) == 1501


def test_apply_sync_policy_builds_snapshot_timeline() -> None:
    proj = _make_project_with_panels(2)
    tts = _make_tts(1, {"s_unit0001aaaa": 5100, "s_unit0002bbbb": 800})

    apply_sync_policy(proj, "ch01", tts)

    a_clips = proj.sequence.audio_tracks[0].clips
    v_clips = proj.sequence.video_tracks[0].clips

    # Audio snapshot = exact audio durations + artifact version
    assert a_clips[0].synced_duration_ms == 5100
    assert a_clips[0].synced_artifact_version == 1
    assert a_clips[1].synced_duration_ms == 800

    # Video durations follow sync formula (min 1500, padding 300)
    assert v_clips[0].duration_ms == 5400
    assert v_clips[1].duration_ms == 1500

    # Sequential layout
    assert v_clips[0].start_ms == 0
    assert v_clips[1].start_ms == 5400
    assert a_clips[1].start_ms == 5400


def test_rerun_tts_does_not_touch_timeline_before_resync() -> None:
    """DoD (e) strengthened: computing a diff must not mutate the project."""
    proj = _make_project_with_panels(1)
    tts_v1 = _make_tts(1, {"s_unit0001aaaa": 3000})
    apply_sync_policy(proj, "ch01", tts_v1)
    snapshot_before = proj.sequence.audio_tracks[0].clips[0].synced_duration_ms

    tts_v2 = _make_tts(2, {"s_unit0001aaaa": 4200})
    diff = compute_resync_diff(proj, "ch01", tts_v2)

    assert diff.has_changes
    assert diff.entries[0].old_duration_ms == 3000
    assert diff.entries[0].new_duration_ms == 4200
    assert diff.entries[0].delta_ms == 1200
    # Timeline untouched
    assert proj.sequence.audio_tracks[0].clips[0].synced_duration_ms == snapshot_before
    assert proj.sequence.audio_tracks[0].clips[0].synced_artifact_version == 1


def test_apply_resync_updates_snapshot_and_relayouts() -> None:
    proj = _make_project_with_panels(2)
    tts_v1 = _make_tts(1, {"s_unit0001aaaa": 3000, "s_unit0002bbbb": 2000})
    apply_sync_policy(proj, "ch01", tts_v1)

    tts_v2 = _make_tts(2, {"s_unit0001aaaa": 6000, "s_unit0002bbbb": 2000})
    proj, diff = apply_resync(proj, "ch01", tts_v2)

    a_clips = proj.sequence.audio_tracks[0].clips
    v_clips = proj.sequence.video_tracks[0].clips

    assert a_clips[0].synced_duration_ms == 6000
    assert a_clips[0].synced_artifact_version == 2
    assert v_clips[0].duration_ms == 6300  # 6000 + 300 padding
    # Second clip start shifted by the new first duration
    assert v_clips[1].start_ms == 6300
    assert proj.active_artifacts["ch01"]["tts"] == 2
    assert len(diff.entries) == 1


def test_resync_no_changes_is_noop() -> None:
    proj = _make_project_with_panels(1)
    tts_v1 = _make_tts(1, {"s_unit0001aaaa": 3000})
    apply_sync_policy(proj, "ch01", tts_v1)

    same = _make_tts(1, {"s_unit0001aaaa": 3000})
    diff = compute_resync_diff(proj, "ch01", same)
    assert not diff.has_changes


def test_resync_detects_new_and_missing_units() -> None:
    proj = _make_project_with_panels(1)
    tts_v1 = _make_tts(1, {"s_unit0001aaaa": 3000})
    apply_sync_policy(proj, "ch01", tts_v1)

    tts_v2 = _make_tts(2, {"s_unit0009zzzz": 2500})  # replaced unit
    diff = compute_resync_diff(proj, "ch01", tts_v2)
    assert diff.has_changes
    assert len(diff.missing_units) == 1  # old anchor missing in new artifact
    assert len(diff.new_units) == 1  # new clip with no timeline slot
