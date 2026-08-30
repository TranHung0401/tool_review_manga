"""Unit tests for Import Connectors (LocalFolderConnector & HakuNekoStub)."""

import tempfile
from pathlib import Path

from PIL import Image

from manga_pipeline.connectors.hakuneko import HakuNekoConnectorStub
from manga_pipeline.connectors.local_folder import LocalFolderConnector


def test_local_folder_connector_discovery_and_import() -> None:
    """Test LocalFolderConnector discovers and imports pages into project."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        source_dir = root / "raw_manga"
        source_dir.mkdir(parents=True)

        # Create 2 sample images
        img1 = Image.new("RGB", (800, 1200), color=(255, 0, 0))
        img1.save(source_dir / "01.png")
        img2 = Image.new("RGB", (800, 1200), color=(0, 255, 0))
        img2.save(source_dir / "02.jpg")

        connector = LocalFolderConnector()
        chapters = connector.discover_chapters(source_dir)
        assert len(chapters) >= 1

        project_dir = root / "project"
        project_dir.mkdir(parents=True)
        res = connector.import_chapter("ch01", source_dir, project_dir)

        assert res.chapter_id == "ch01"
        assert len(res.pages) == 2
        assert res.pages[0].width == 800
        assert res.pages[0].height == 1200
        assert res.pages[0].sha256 != ""
        assert (project_dir / "pages" / "ch01" / "01.png").exists()


def test_hakuneko_connector_stub() -> None:
    """Test HakuNekoConnectorStub delegates to LocalFolderConnector."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        source_dir = root / "hakuneko_downloads"
        source_dir.mkdir(parents=True)

        img = Image.new("RGB", (600, 900), color=(0, 0, 255))
        img.save(source_dir / "page_01.png")

        stub = HakuNekoConnectorStub()
        chapters = stub.discover_chapters(source_dir)
        assert len(chapters) >= 1

        project_dir = root / "proj"
        project_dir.mkdir(parents=True)
        res = stub.import_chapter("ch01", source_dir, project_dir)
        assert res.source_type == "hakuneko"
        assert len(res.pages) == 1
