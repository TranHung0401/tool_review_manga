"""AI Engine capability Protocols and request/result data contracts."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from manga_pipeline.core.schemas.artifact_layout import LayoutArtifact
from manga_pipeline.core.schemas.artifact_ocr import OcrArtifact
from manga_pipeline.core.schemas.artifact_script import ScriptArtifact
from manga_pipeline.core.schemas.artifact_tts import TtsArtifact


# ----------------- Layout Engine Protocol -----------------
@dataclass
class LayoutRequest:
    chapter_id: str
    pages: list[Path]
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class LayoutResult:
    artifact: LayoutArtifact


class LayoutEngine(Protocol):
    def detect(self, request: LayoutRequest) -> LayoutResult:
        """Detect comic panels and text bubble bounding boxes."""
        ...


# ----------------- OCR Engine Protocol -----------------
@dataclass
class OcrRequest:
    chapter_id: str
    layout_artifact: LayoutArtifact
    pages_dir: Path
    cleaned_dir: Path | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class OcrResult:
    artifact: OcrArtifact


class OcrEngine(Protocol):
    def extract(self, request: OcrRequest) -> OcrResult:
        """Extract text from panels/bubbles and generate cleaned inpainted images."""
        ...


# ----------------- Script Engine Protocol -----------------
@dataclass
class ScriptRequest:
    chapter_id: str
    mode: Literal["manual_script", "translate", "ai_narrate"]
    ocr_artifact: OcrArtifact
    source_file: Path | None = None
    target_language: str = "vi"
    glossary: dict[str, str] = field(default_factory=dict)
    style_preset: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScriptResult:
    artifact: ScriptArtifact


class ScriptEngine(Protocol):
    def produce(self, request: ScriptRequest) -> ScriptResult:
        """Produce standardized script units across all 3 modes."""
        ...


# ----------------- TTS Engine Protocol -----------------
@dataclass
class TtsRequest:
    chapter_id: str
    script_artifact: ScriptArtifact
    audio_output_dir: Path
    artifact_version: int = 1
    voice_ref: str = "vi-VN-HoaiMyNeural"
    speed: float = 1.0
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class TtsResult:
    artifact: TtsArtifact


class TtsEngine(Protocol):
    def synthesize(self, request: TtsRequest) -> TtsResult:
        """Synthesize speech audio files for all script units."""
        ...
