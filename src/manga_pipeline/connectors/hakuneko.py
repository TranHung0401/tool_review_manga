"""HakuNeko connector stub for future manga scraping/download integration."""

from pathlib import Path

from manga_pipeline.connectors.base import ChapterImportResult, ImportConnector
from manga_pipeline.connectors.local_folder import LocalFolderConnector


class HakuNekoConnectorStub(ImportConnector):
    """Stub connector for HakuNeko manga downloads, delegating to LocalFolderConnector."""

    def __init__(self) -> None:
        self._delegate = LocalFolderConnector()

    def discover_chapters(self, source_path: Path) -> list[str]:
        """Discover chapters in HakuNeko download directory."""
        return self._delegate.discover_chapters(source_path)

    def import_chapter(
        self,
        chapter_id: str,
        source_path: Path,
        target_project_dir: Path,
    ) -> ChapterImportResult:
        """Import chapter pages from HakuNeko directory."""
        res = self._delegate.import_chapter(chapter_id, source_path, target_project_dir)
        res.source_type = "hakuneko"
        return res
