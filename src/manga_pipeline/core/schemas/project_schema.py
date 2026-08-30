"""Project state schema (project.json)."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from manga_pipeline.core.schemas.artifact_layout import PanelSource


class StoryMetadata(BaseModel):
    title: str
    chapters: list[str] = Field(default_factory=list)


class SyncPolicy(BaseModel):
    min_duration_ms: int = 1500
    padding_ms: int = 300


class ProjectSettings(BaseModel):
    privacy: Literal["local_only", "cloud_allowed"] = "local_only"
    script_mode_default: Literal["manual_script", "translate", "ai_narrate"] = "manual_script"
    sync_policy: SyncPolicy = Field(default_factory=SyncPolicy)
    directories: dict[str, str] = Field(
        default_factory=lambda: {"capcut_drafts": "exports/capcut", "exports": "exports/"}
    )


class AnchorEntry(BaseModel):
    kind: Literal["panel", "text", "unit"]
    current: str = Field(description="Current AI artifact ID: p_..., t_..., s_...")
    history: list[str] = Field(default_factory=list)
    locked: bool = False
    retired: bool = False

    @model_validator(mode="after")
    def validate_current_in_history(self) -> "AnchorEntry":
        if self.current and self.current not in self.history:
            self.history.append(self.current)
        return self


class MergeOverride(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    into: str = Field(description="Target anchor ID: pa_...")
    from_: list[str] = Field(alias="from", description="Source anchor IDs to merge from: pa_...")


class UserPanelOverride(BaseModel):
    anchor: str = Field(description="Anchor ID: pa_...")
    source: PanelSource
    reading_order: int
    locked: bool = True


class ChapterLayoutOverrides(BaseModel):
    deleted_panels: list[str] = Field(default_factory=list, description="List of pa_... anchors")
    merged: list[MergeOverride] = Field(default_factory=list)
    user_panels: list[UserPanelOverride] = Field(default_factory=list)
    reading_order_overrides: dict[str, int] = Field(
        default_factory=dict, description="pa_... anchor -> new reading order"
    )

    @field_validator("deleted_panels")
    @classmethod
    def check_deleted_panels_are_anchors(cls, v: list[str]) -> list[str]:
        for anchor_id in v:
            if not anchor_id.startswith("pa_"):
                raise ValueError(
                    f"Invalid panel anchor '{anchor_id}'. "
                    "Layout overrides must use 'pa_' anchor refs, never AI IDs (p_)."
                )
        return v

    @field_validator("reading_order_overrides")
    @classmethod
    def check_reading_order_anchors(cls, v: dict[str, int]) -> dict[str, int]:
        for anchor_id in v:
            if not anchor_id.startswith("pa_"):
                raise ValueError(
                    f"Invalid panel anchor '{anchor_id}'. Reading order overrides must use 'pa_' anchor refs."
                )
        return v


class TextOverride(BaseModel):
    original: str | None = None
    text: str | None = None
    speaker_id: str | None = None
    reviewed: bool = False


class CharacterEntry(BaseModel):
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    voice: str
    speech_style: str = ""
    notes: str = ""


class AnimationTemplate(BaseModel):
    in_animation: dict[str, Any] | None = None
    keyframe: dict[str, Any] | None = None
    out_animation: dict[str, Any] | None = None


class VideoClip(BaseModel):
    panel_ref: str = Field(description="Anchor reference: pa_...")
    start_ms: int = Field(ge=0)
    duration_ms: int = Field(gt=0)
    in_point: int = 0
    transform: dict[str, Any] = Field(default_factory=dict)
    visual_effects: dict[str, Any] = Field(default_factory=dict)

    @field_validator("panel_ref")
    @classmethod
    def check_panel_ref(cls, v: str) -> str:
        if not v.startswith("pa_"):
            raise ValueError(
                f"Invalid panel_ref '{v}'. Video clips must reference persistent anchors (pa_...), not AI IDs (p_)."
            )
        return v


class VideoTrack(BaseModel):
    clips: list[VideoClip] = Field(default_factory=list)


class AudioClip(BaseModel):
    audio_ref: str = Field(description="Anchor reference: sa_...")
    start_ms: int = Field(ge=0)
    synced_duration_ms: int = Field(ge=0)
    synced_artifact_version: int = 1

    @field_validator("audio_ref")
    @classmethod
    def check_audio_ref(cls, v: str) -> str:
        if not v.startswith("sa_"):
            raise ValueError(
                f"Invalid audio_ref '{v}'. "
                "Audio clips must reference persistent unit anchors (sa_...), not AI IDs (s_)."
            )
        return v


class AudioTrack(BaseModel):
    clips: list[AudioClip] = Field(default_factory=list)


class SequenceModel(BaseModel):
    video_tracks: list[VideoTrack] = Field(default_factory=list)
    audio_tracks: list[AudioTrack] = Field(default_factory=list)
    overlay_tracks: list[dict[str, Any]] = Field(default_factory=list)


class ProjectSchema(BaseModel):
    schema_version: int = 1
    story: StoryMetadata
    settings: ProjectSettings = Field(default_factory=ProjectSettings)
    active_artifacts: dict[str, dict[str, int]] = Field(
        default_factory=dict,
        description="Active artifact versions per chapter: {'ch01': {'layout': 1, 'ocr': 2, ...}}",
    )
    anchors: dict[str, AnchorEntry] = Field(
        default_factory=dict, description="Persistent anchors: pa_..., ta_..., sa_..."
    )
    layout_overrides: dict[str, ChapterLayoutOverrides] = Field(default_factory=dict)
    overrides: dict[str, TextOverride] = Field(
        default_factory=dict, description="Text overrides keyed by ta_... or sa_... anchor ID"
    )
    characters: dict[str, CharacterEntry] = Field(default_factory=dict)
    animation_templates: dict[str, AnimationTemplate] = Field(default_factory=dict)
    sequence: SequenceModel = Field(default_factory=SequenceModel)

    @field_validator("anchors")
    @classmethod
    def check_anchors_keys(cls, v: dict[str, AnchorEntry]) -> dict[str, AnchorEntry]:
        for k in v:
            if not (k.startswith("pa_") or k.startswith("ta_") or k.startswith("sa_")):
                raise ValueError(f"Invalid anchor key '{k}'. Anchors must start with 'pa_', 'ta_', or 'sa_'.")
        return v

    @field_validator("overrides")
    @classmethod
    def check_overrides_keys(cls, v: dict[str, TextOverride]) -> dict[str, TextOverride]:
        for k in v:
            if not (k.startswith("ta_") or k.startswith("sa_")):
                raise ValueError(
                    f"Invalid override key '{k}'. "
                    "Overrides must reference anchor IDs (ta_... or sa_...), "
                    "never AI IDs (t_... or s_...)."
                )
        return v
