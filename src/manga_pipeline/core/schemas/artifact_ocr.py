"""OCR artifact schema (ocr.{ch}.v{N}.json)."""

from typing import Literal

from pydantic import BaseModel, Field


class OcrDependsOn(BaseModel):
    stage: Literal["layout"] = "layout"
    artifact_version: int
    layout_overrides_hash: str | None = None


class OcrManifest(BaseModel):
    engine: str
    model: str
    engine_version: str
    timestamp: str
    scale_factor: float = 1.0


class OcrText(BaseModel):
    id: str = Field(description="AI text hash ID: t_...")
    original: str
    text_type: Literal["dialogue", "sfx", "narration"] = "dialogue"
    reading_order: int
    speaker_id_hint: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class OcrPanel(BaseModel):
    id: str = Field(description="AI panel hash ID: p_...")
    cleaned_image: str | None = None
    texts: list[OcrText] = Field(default_factory=list)


class OcrArtifact(BaseModel):
    schema_version: int = 1
    stage: Literal["ocr"] = "ocr"
    chapter_id: str
    artifact_version: int
    depends_on: OcrDependsOn
    manifest: OcrManifest
    panels: list[OcrPanel] = Field(default_factory=list)
