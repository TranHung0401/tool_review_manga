"""Base connector interfaces and data classes for importing manga chapters."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class PageFileInfo:
    """Information about a single manga page image."""

    index: int
    filename: str
    relative_path: str
    full_path: Path
    sha256: str
    width: int
    height: int


@dataclass
class ChapterImportResult:
    """Result of importing a manga chapter."""

    chapter_id: str
    chapter_title: str
    pages: list[PageFileInfo] = field(default_factory=list)
    source_type: str = "local_folder"


class ImportConnector(Protocol):
    """Protocol for manga chapter import connectors."""

    def discover_chapters(self, source_path: Path) -> list[str]:
        """Discover available chapter identifiers in the given source."""
        ...

    def import_chapter(
        self,
        chapter_id: str,
        source_path: Path,
        target_project_dir: Path,
    ) -> ChapterImportResult:
        """Import pages of a chapter into the target project."""
        ...
