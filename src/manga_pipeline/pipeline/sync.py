"""Timeline sync policy engine (Sprint 4).

Implements the architecture rule:
    clip.duration_ms = max(min_duration_ms, audio.duration_ms + padding_ms)

The duration snapshot is computed at explicit sync time in the Import Layer.
Re-running TTS never mutates the timeline; a new TTS artifact only reaches the
timeline after the user reviews the resync diff and confirms Resync.
"""

from dataclasses import dataclass, field
from typing import Any

from manga_pipeline.core.anchors import AnchorStore
from manga_pipeline.core.schemas.artifact_tts import TtsArtifact
from manga_pipeline.core.schemas.project_schema import (
    AudioClip,
    AudioTrack,
    ProjectSchema,
    VideoClip,
    VideoTrack,
)


@dataclass
class ResyncDiffEntry:
    """Per-clip difference between snapshot timeline and a new TTS artifact."""

    unit_anchor: str
    resolved_unit_id: str
    old_duration_ms: int
    new_duration_ms: int
    delta_ms: int
    old_artifact_version: int
    new_artifact_version: int


@dataclass
class ResyncDiff:
    """Full diff report shown in the Resync UI before user confirmation."""

    chapter_id: str
    entries: list[ResyncDiffEntry] = field(default_factory=list)
    missing_units: list[str] = field(default_factory=list)  # anchors with no clip in new TTS
    new_units: list[str] = field(default_factory=list)  # TTS unit ids without a timeline clip
    has_changes: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapter_id": self.chapter_id,
            "has_changes": self.has_changes,
            "entries": [vars(e) for e in self.entries],
            "missing_units": self.missing_units,
            "new_units": self.new_units,
        }


def compute_synced_duration(audio_duration_ms: int, min_duration_ms: int, padding_ms: int) -> int:
    """Core sync policy formula: max(min_duration_ms, audio_duration_ms + padding_ms)."""
    return max(min_duration_ms, audio_duration_ms + padding_ms)


def _tts_duration_by_unit(tts_artifact: TtsArtifact) -> dict[str, int]:
    return {c.unit_id: c.duration_ms for c in tts_artifact.clips}


def apply_sync_policy(
    project: ProjectSchema,
    chapter_id: str,
    tts_artifact: TtsArtifact,
    panel_unit_map: dict[str, str] | None = None,
) -> ProjectSchema:
    """Build or resync sequence tracks from a TTS artifact using sync_policy.

    - Audio clips get ``synced_duration_ms`` snapshot from the TTS clip durations.
    - Video clips get ``duration_ms = max(min_duration, audio + padding)``.
    - Clips are laid out sequentially (start_ms cursor).
    - ``panel_unit_map`` optionally maps panel anchor -> unit anchor to pair
      video and audio rows; when omitted, pairing is positional.
    """
    policy = project.settings.sync_policy
    store = AnchorStore(project)
    durations = _tts_duration_by_unit(tts_artifact)

    unit_anchors: list[str] = []
    for clip in tts_artifact.clips:
        anchor = store.find_by_ai_id(clip.unit_id, kind="unit")
        if anchor is None:
            anchor = store.create_anchor("unit", clip.unit_id)
        unit_anchors.append(anchor)

    panel_anchors = [k for k, v in project.anchors.items() if v.kind == "panel" and not v.retired]

    video_clips: list[VideoClip] = []
    audio_clips: list[AudioClip] = []
    cursor = 0
    for idx, (clip, unit_anchor) in enumerate(zip(tts_artifact.clips, unit_anchors, strict=False)):
        audio_ms = durations.get(clip.unit_id, 0)
        synced = compute_synced_duration(audio_ms, policy.min_duration_ms, policy.padding_ms)

        # Pair with panel: explicit map first, else positional fallback
        panel_ref: str | None = None
        if panel_unit_map:
            for p_ref, u_ref in panel_unit_map.items():
                if u_ref == unit_anchor:
                    panel_ref = p_ref
                    break
        if panel_ref is None and idx < len(panel_anchors):
            panel_ref = panel_anchors[idx]

        if panel_ref is not None:
            video_clips.append(
                VideoClip(panel_ref=panel_ref, start_ms=cursor, duration_ms=synced)
            )

        audio_clips.append(
            AudioClip(
                audio_ref=unit_anchor,
                start_ms=cursor,
                synced_duration_ms=audio_ms,
                synced_artifact_version=tts_artifact.artifact_version,
            )
        )
        cursor += synced

    project.sequence.video_tracks = [VideoTrack(clips=video_clips)]
    project.sequence.audio_tracks = [AudioTrack(clips=audio_clips)]
    return project


def compute_resync_diff(
    project: ProjectSchema,
    chapter_id: str,
    new_tts_artifact: TtsArtifact,
) -> ResyncDiff:
    """Compare current timeline snapshot against a new TTS artifact.

    Never mutates the project — this powers the Resync review UI.
    """
    store = AnchorStore(project)
    durations = _tts_duration_by_unit(new_tts_artifact)
    diff = ResyncDiff(chapter_id=chapter_id)

    seen_unit_ids: set[str] = set()
    for track in project.sequence.audio_tracks:
        for a_clip in track.clips:
            entry = project.anchors.get(a_clip.audio_ref)
            resolved = entry.current if entry else a_clip.audio_ref
            seen_unit_ids.add(resolved)
            if resolved in durations:
                new_ms = durations[resolved]
                if new_ms != a_clip.synced_duration_ms:
                    diff.entries.append(
                        ResyncDiffEntry(
                            unit_anchor=a_clip.audio_ref,
                            resolved_unit_id=resolved,
                            old_duration_ms=a_clip.synced_duration_ms,
                            new_duration_ms=new_ms,
                            delta_ms=new_ms - a_clip.synced_duration_ms,
                            old_artifact_version=a_clip.synced_artifact_version,
                            new_artifact_version=new_tts_artifact.artifact_version,
                        )
                    )
            else:
                diff.missing_units.append(a_clip.audio_ref)

    for clip in new_tts_artifact.clips:
        if clip.unit_id not in seen_unit_ids:
            anchor = store.find_by_ai_id(clip.unit_id, kind="unit")
            diff.new_units.append(anchor or clip.unit_id)

    diff.has_changes = bool(diff.entries or diff.missing_units or diff.new_units)
    return diff


def apply_resync(
    project: ProjectSchema,
    chapter_id: str,
    new_tts_artifact: TtsArtifact,
) -> tuple[ProjectSchema, ResyncDiff]:
    """Apply a confirmed resync: update duration snapshots + re-layout starts.

    Returns the applied diff for reporting. Only call after user confirmation.
    """
    diff = compute_resync_diff(project, chapter_id, new_tts_artifact)
    if not diff.has_changes:
        return project, diff

    policy = project.settings.sync_policy
    durations = _tts_duration_by_unit(new_tts_artifact)

    # Update audio snapshots in place
    for track in project.sequence.audio_tracks:
        for a_clip in track.clips:
            entry = project.anchors.get(a_clip.audio_ref)
            resolved = entry.current if entry else a_clip.audio_ref
            if resolved in durations:
                a_clip.synced_duration_ms = durations[resolved]
                a_clip.synced_artifact_version = new_tts_artifact.artifact_version

    # Re-layout sequential starts using the sync formula on paired tracks
    if project.sequence.audio_tracks:
        a_clips = project.sequence.audio_tracks[0].clips
        v_clips = project.sequence.video_tracks[0].clips if project.sequence.video_tracks else []
        cursor = 0
        for idx, a_clip in enumerate(a_clips):
            synced = compute_synced_duration(
                a_clip.synced_duration_ms, policy.min_duration_ms, policy.padding_ms
            )
            a_clip.start_ms = cursor
            if idx < len(v_clips):
                v_clips[idx].start_ms = cursor
                v_clips[idx].duration_ms = synced
            cursor += synced

    # Update active artifact version pointer
    project.active_artifacts.setdefault(chapter_id, {})["tts"] = new_tts_artifact.artifact_version
    return project, diff
