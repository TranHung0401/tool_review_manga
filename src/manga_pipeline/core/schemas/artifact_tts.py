"""TTS artifact schema (tts.{ch}.v{N}.json)."""

from typing import Literal

from pydantic import BaseModel, Field


class TtsDependsOn(BaseModel):
    stage: Literal["script"] = "script"
    artifact_version: int


class TtsManifest(BaseModel):
    provider: str
    voice_ref: str
    timestamp: str
    fallback_provider: str | None = None


class TtsClip(BaseModel):
    unit_id: str = Field(description="AI unit hash ID: s_...")
    file: str = Field(description="Audio file path, e.g. audio/ch01_s_ab12cd34ef56.v7.wav")
    duration_ms: int = Field(ge=0, description="Exact audio duration in milliseconds")


class TtsArtifact(BaseModel):
    schema_version: int = 1
    stage: Literal["tts"] = "tts"
    chapter_id: str
    artifact_version: int
    depends_on: TtsDependsOn
    manifest: TtsManifest
    clips: list[TtsClip] = Field(default_factory=list)
