"""Local folder connector for importing raw manga images from local filesystem."""

import hashlib
import shutil
from pathlib import Path
from typing import ClassVar

from PIL import Image

from manga_pipeline.connectors.base import ChapterImportResult, ImportConnector, PageFileInfo
from manga_pipeline.core.schemas.project_schema import ProjectSchema


def _calculate_sha256(filepath: Path) -> str:
    """Compute sha256 checksum of a file."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class LocalFolderConnector(ImportConnector):
    """Imports manga pages from local directory containing PNG/JPG/WEBP images."""

    SUPPORTED_EXTENSIONS: ClassVar[set[str]] = {".png", ".jpg", ".jpeg", ".webp"}

    def discover_chapters(self, source_path: Path) -> list[str]:
        """Discover subdirectories or return the folder name itself if it contains images."""
        if not source_path.exists():
            return []

        # If subdirectories exist and contain images, list them as chapters
        subdirs = [d for d in source_path.iterdir() if d.is_dir()]
        chapters: list[str] = []
        for subdir in subdirs:
            if any(f.suffix.lower() in self.SUPPORTED_EXTENSIONS for f in subdir.iterdir() if f.is_file()):
                chapters.append(subdir.name)

        if not chapters:
            # Check if source_path itself contains images
            if any(f.suffix.lower() in self.SUPPORTED_EXTENSIONS for f in source_path.iterdir() if f.is_file()):
                chapters.append(source_path.name or "ch01")

        return sorted(chapters)

    def import_chapter(
        self,
        chapter_id: str,
        source_path: Path,
        target_project_dir: Path,
    ) -> ChapterImportResult:
        """Scan, validate, compute checksums, copy to pages/ and register in project."""
        src_dir = source_path
        if (source_path / chapter_id).is_dir():
            src_dir = source_path / chapter_id

        # Discover all valid image files
        image_files = [
            f for f in sorted(src_dir.iterdir()) if f.is_file() and f.suffix.lower() in self.SUPPORTED_EXTENSIONS
        ]

        if not image_files:
            raise ValueError(f"No supported image files found in {src_dir}")

        dest_pages_dir = target_project_dir / "pages" / chapter_id
        dest_pages_dir.mkdir(parents=True, exist_ok=True)

        pages_info: list[PageFileInfo] = []
        for idx, img_file in enumerate(image_files, start=1):
            dest_file = dest_pages_dir / img_file.name
            if not dest_file.exists() or dest_file.stat().st_size != img_file.stat().st_size:
                shutil.copy2(img_file, dest_file)

            sha = _calculate_sha256(dest_file)
            with Image.open(dest_file) as im:
                w, h = im.size

            rel_path = f"pages/{chapter_id}/{img_file.name}"
            pages_info.append(
                PageFileInfo(
                    index=idx,
                    filename=img_file.name,
                    relative_path=rel_path,
                    full_path=dest_file,
                    sha256=sha,
                    width=w,
                    height=h,
                )
            )

        # Update or create project.json
        project_file = target_project_dir / "project.json"
        if project_file.exists():
            with open(project_file, encoding="utf-8") as f:
                project = ProjectSchema.model_validate_json(f.read())
            if chapter_id not in project.story.chapters:
                project.story.chapters.append(chapter_id)
            with open(project_file, "w", encoding="utf-8") as f:
                f.write(project.model_dump_json(indent=2))

        return ChapterImportResult(
            chapter_id=chapter_id,
            chapter_title=chapter_id,
            pages=pages_info,
            source_type="local_folder",
        )
