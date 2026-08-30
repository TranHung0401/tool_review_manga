"""Deterministic, target-neutral Render Plan Builder supporting Animation Templates."""

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from manga_pipeline.core.schemas.artifact_layout import LayoutArtifact, Panel
from manga_pipeline.core.schemas.artifact_tts import TtsArtifact
from manga_pipeline.core.schemas.project_schema import (
    AudioClip,
    AudioTrack,
    ProjectSchema,
    VideoClip,
    VideoTrack,
)


@dataclass
class ResolvedTransform:
    """Resolved 2D motion and zoom transform for a clip."""

    type: str = "static"
    scale_start: float = 1.0
    scale_end: float = 1.0
    pan_start: tuple[float, float] = (0.0, 0.0)
    pan_end: tuple[float, float] = (0.0, 0.0)
    anchor: str = "center"


@dataclass
class ResolvedVisualEffect:
    """Resolved visual effect (fade, slide, transition)."""

    template_name: str | None = None
    effect_type: str = "none"
    duration_ms: int = 0
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class RenderPlanVideoClip:
    """Video clip in deterministic Render Plan."""

    clip_id: str
    panel_anchor: str
    resolved_panel_id: str
    source_image: str
    source_bbox: list[int]
    start_ms: int
    duration_ms: int
    in_point_ms: int = 0
    transform: ResolvedTransform = field(default_factory=ResolvedTransform)
    visual_effects: list[ResolvedVisualEffect] = field(default_factory=list)


@dataclass
class RenderPlanAudioClip:
    """Audio clip in deterministic Render Plan."""

    clip_id: str
    unit_anchor: str
    resolved_unit_id: str
    audio_file: str
    start_ms: int
    duration_ms: int


@dataclass
class RenderPlan:
    """Deterministic, target-neutral specification for rendering a chapter."""

    chapter_id: str
    schema_version: int = 1
    video_clips: list[RenderPlanVideoClip] = field(default_factory=list)
    audio_clips: list[RenderPlanAudioClip] = field(default_factory=list)
    total_duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        """Serialize to deterministic JSON (sorted keys, 2-space indent)."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False)

    @classmethod
    def from_project(
        cls,
        chapter_id: str,
        project: ProjectSchema,
        layout_artifact: LayoutArtifact | None = None,
        tts_artifact: TtsArtifact | None = None,
    ) -> "RenderPlan":
        """
        Build deterministic RenderPlan from project.json state by resolving
        persistent anchors (pa_, sa_) to concrete panel and audio resources.
        """
        panels_by_id: dict[str, Panel] = {}
        if layout_artifact:
            panels_by_id = {p.id: p for p in layout_artifact.panels}

        tts_clips_by_unit: dict[str, str] = {}
        if tts_artifact:
            tts_clips_by_unit = {c.unit_id: c.file for c in tts_artifact.clips}

        video_clips: list[RenderPlanVideoClip] = []
        audio_clips: list[RenderPlanAudioClip] = []
        total_duration = 0

        # Ensure default video tracks exist if empty
        video_tracks = list(project.sequence.video_tracks)
        if not video_tracks:
            panel_anchors = [k for k, v in project.anchors.items() if v.kind == "panel" and not v.retired]
            if not panel_anchors and layout_artifact:
                panel_anchors = [p.id for p in layout_artifact.panels]

            if panel_anchors:
                vclips = [
                    VideoClip(panel_ref=pa, start_ms=i * 3000, duration_ms=3000)
                    for i, pa in enumerate(panel_anchors)
                ]
                video_tracks = [VideoTrack(clips=vclips)]

        # Ensure default audio tracks exist if empty
        audio_tracks = list(project.sequence.audio_tracks)
        if not audio_tracks:
            unit_anchors = [k for k, v in project.anchors.items() if v.kind == "unit" and not v.retired]
            if not unit_anchors and tts_artifact:
                unit_anchors = [c.unit_id for c in tts_artifact.clips]

            if unit_anchors:
                aclips = [
                    AudioClip(audio_ref=sa, start_ms=i * 3000, synced_duration_ms=2500)
                    for i, sa in enumerate(unit_anchors)
                ]
                audio_tracks = [AudioTrack(clips=aclips)]

        # 1. Resolve Video Tracks
        for track_idx, track in enumerate(video_tracks):
            for clip_idx, clip in enumerate(track.clips):
                panel_anchor = clip.panel_ref
                anchor_entry = project.anchors.get(panel_anchor)
                resolved_id = anchor_entry.current if anchor_entry else panel_anchor

                panel_obj = panels_by_id.get(resolved_id)
                if not panel_obj and layout_artifact and layout_artifact.panels:
                    if clip_idx < len(layout_artifact.panels):
                        panel_obj = layout_artifact.panels[clip_idx]

                img_path = panel_obj.source.image if panel_obj else ""
                bbox = panel_obj.source.bbox if panel_obj else [0, 0, 1920, 1080]

                # Resolve template if present
                v_effects: list[ResolvedVisualEffect] = []
                transform = ResolvedTransform()

                tpl_ref = clip.visual_effects.get("template_ref")
                if tpl_ref and tpl_ref in project.animation_templates:
                    tpl = project.animation_templates[tpl_ref]
                    if tpl.in_animation:
                        v_effects.append(
                            ResolvedVisualEffect(
                                template_name=tpl_ref,
                                effect_type=tpl.in_animation.get("type", "fade"),
                                duration_ms=tpl.in_animation.get("duration_ms", 300),
                                params=tpl.in_animation,
                            )
                        )
                    if tpl.out_animation:
                        v_effects.append(
                            ResolvedVisualEffect(
                                template_name=tpl_ref,
                                effect_type=tpl.out_animation.get("type", "fade"),
                                duration_ms=tpl.out_animation.get("duration_ms", 300),
                                params=tpl.out_animation,
                            )
                        )
                    if tpl.keyframe:
                        kf_type = tpl.keyframe.get("type", "static")
                        s_start = float(tpl.keyframe.get("scale_start", 1.0))
                        s_end = float(tpl.keyframe.get("scale_end", 1.0))
                        anchor_pos = tpl.keyframe.get("anchor", "center")

                        if kf_type == "zoom_in" and s_start == 1.0 and s_end == 1.0:
                            s_end = 1.15
                        elif kf_type == "zoom_out" and s_start == 1.0 and s_end == 1.0:
                            s_start = 1.15
                            s_end = 1.0

                        transform = ResolvedTransform(
                            type=kf_type,
                            scale_start=s_start,
                            scale_end=s_end,
                            anchor=anchor_pos,
                        )

                # Direct clip transform override (if specified)
                if clip.transform:
                    if "scale_start" in clip.transform:
                        transform.scale_start = float(clip.transform["scale_start"])
                    if "scale_end" in clip.transform:
                        transform.scale_end = float(clip.transform["scale_end"])

                plan_vclip = RenderPlanVideoClip(
                    clip_id=f"vclip_{track_idx}_{clip_idx}",
                    panel_anchor=panel_anchor,
                    resolved_panel_id=resolved_id,
                    source_image=img_path,
                    source_bbox=bbox,
                    start_ms=clip.start_ms,
                    duration_ms=clip.duration_ms,
                    in_point_ms=clip.in_point,
                    transform=transform,
                    visual_effects=v_effects,
                )
                video_clips.append(plan_vclip)
                clip_end = clip.start_ms + clip.duration_ms
                if clip_end > total_duration:
                    total_duration = clip_end

        # 2. Resolve Audio Tracks
        for a_track_idx, a_track in enumerate(audio_tracks):
            for a_clip_idx, a_clip in enumerate(a_track.clips):
                unit_anchor = a_clip.audio_ref
                anchor_entry = project.anchors.get(unit_anchor)
                resolved_unit_id = anchor_entry.current if anchor_entry else unit_anchor
                audio_file = tts_clips_by_unit.get(resolved_unit_id, "")

                plan_aclip = RenderPlanAudioClip(
                    clip_id=f"aclip_{a_track_idx}_{a_clip_idx}",
                    unit_anchor=unit_anchor,
                    resolved_unit_id=resolved_unit_id,
                    audio_file=audio_file,
                    start_ms=a_clip.start_ms,
                    duration_ms=a_clip.synced_duration_ms,
                )
                audio_clips.append(plan_aclip)

        return cls(
            chapter_id=chapter_id,
            video_clips=video_clips,
            audio_clips=audio_clips,
            total_duration_ms=total_duration,
        )
