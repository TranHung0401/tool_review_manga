"""Script artifact schema (script.{ch}.v{N}.json) supporting 3 modes."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ScriptDependsOn(BaseModel):
    stage: Literal["ocr"] = "ocr"
    artifact_version: int
    depends_on_story: int | None = None


class ScriptManifest(BaseModel):
    mode: Literal["manual_script", "translate", "ai_narrate"]
    engine: str
    timestamp: str
    source_file: str | None = None
    model: str | None = None
    engine_version: str | None = None
    quantization: str | None = None
    gpu_layers: str | int | None = None
    vision: bool | None = None
    model_version_seen: str | None = None
    style_preset: str | None = None
    cost_estimate_usd: float | None = None


class ScriptUnit(BaseModel):
    id: str = Field(description="AI unit hash ID: s_...")
    panel_id: str = Field(description="Associated panel ID: p_...")
    seq: int = Field(ge=1, description="Sequence within panel")
    type: Literal["narration", "dialogue", "sfx"]
    text: str
    source_text_ids: list[str] = Field(default_factory=list, description="Source OCR text IDs: t_...")
    speaker_id_hint: str | None = None


class ScriptArtifact(BaseModel):
    schema_version: int = 1
    stage: Literal["script"] = "script"
    chapter_id: str
    artifact_version: int
    depends_on: ScriptDependsOn
    manifest: ScriptManifest
    units: list[ScriptUnit] = Field(default_factory=list)
    unassigned: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Units not assigned to any panel during manual import",
    )
