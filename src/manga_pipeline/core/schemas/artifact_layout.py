"""Layout artifact schema (layout.{ch}.v{N}.json)."""

from typing import Literal

from pydantic import BaseModel, Field


class InputPage(BaseModel):
    file: str
    sha256: str


class LayoutManifest(BaseModel):
    engine: str
    engine_version: str
    timestamp: str
    inputs: list[InputPage] = Field(default_factory=list)


class PanelSource(BaseModel):
    image: str
    bbox: list[int] = Field(description="[x, y, w, h] integer pixel in original image coords")


class TextRegion(BaseModel):
    id: str = Field(description="AI text hash ID: t_...")
    bbox: list[int] = Field(description="[x, y, w, h] integer pixel in original image coords")
    region_type: Literal["bubble", "sfx", "other"] = "bubble"


class Panel(BaseModel):
    id: str = Field(description="AI panel hash ID: p_...")
    source: PanelSource
    reading_order: int
    text_regions: list[TextRegion] = Field(default_factory=list)


class LayoutArtifact(BaseModel):
    schema_version: int = 1
    stage: Literal["layout"] = "layout"
    chapter_id: str
    artifact_version: int
    manifest: LayoutManifest
    panels: list[Panel] = Field(default_factory=list)
