"""Manga import connectors."""

from manga_pipeline.connectors.base import ChapterImportResult, ImportConnector, PageFileInfo
from manga_pipeline.connectors.hakuneko import HakuNekoConnectorStub
from manga_pipeline.connectors.local_folder import LocalFolderConnector

__all__ = [
    "ImportConnector",
    "PageFileInfo",
    "ChapterImportResult",
    "LocalFolderConnector",
    "HakuNekoConnectorStub",
]
