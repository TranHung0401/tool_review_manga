"""Story artifact schema (story.{ch}.v{N}.json) — Reserved extension for Sprint 5."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class StoryBeat(BaseModel):
    type: Literal["hook", "setup", "conflict", "climax", "ending", "other"]
    panel_ids: list[str] = Field(default_factory=list)
    description: str = ""


class CharacterState(BaseModel):
    personality: list[str] = Field(default_factory=list)
    relationships: dict[str, str] = Field(default_factory=dict)
    current_state: str = ""


class StoryArtifact(BaseModel):
    schema_version: int = 1
    stage: Literal["story"] = "story"
    chapter_id: str
    artifact_version: int
    depends_on: dict[str, Any] | None = None
    manifest: dict[str, Any] = Field(default_factory=dict)
    beats: list[StoryBeat] = Field(default_factory=list)
    character_state: dict[str, CharacterState] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
