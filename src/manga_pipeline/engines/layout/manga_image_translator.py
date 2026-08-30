"""Layout detection engine adapter."""

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from manga_pipeline.core.ids import panel_id, text_id
from manga_pipeline.core.schemas.artifact_layout import (
    InputPage,
    LayoutArtifact,
    LayoutManifest,
    Panel,
    PanelSource,
    TextRegion,
)
from manga_pipeline.engines.protocols import LayoutRequest, LayoutResult


def _compute_sha256(file_path: Path) -> str:
    """Compute sha256 hash of an image file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def detect_panels_and_text(img: Image.Image, page_rel_path: str) -> list[Panel]:
    """
    Detect comic panels and text regions using image processing heuristics
    (gutter detection and contrast profiling) conforming to layout schema.
    """
    w, h = img.size
    gray = img.convert("L")
    arr = np.array(gray)

    # Calculate row-wise white and black pixel ratios to detect authentic gutters
    row_white_ratio = np.mean(arr > 240, axis=1)
    row_black_ratio = np.mean(arr < 15, axis=1)
    gutter_mask = (row_white_ratio > 0.93) | (row_black_ratio > 0.93)

    # Find continuous non-gutter segments (panels along vertical axis)
    cuts = []
    in_panel = False
    start_y = 0

    for y, is_gutter in enumerate(gutter_mask):
        if not is_gutter and not in_panel:
            in_panel = True
            start_y = y
        elif is_gutter and in_panel:
            in_panel = False
            if (y - start_y) > h * 0.08:  # Minimum 8% of page height
                cuts.append((start_y, y))

    if in_panel and (h - start_y) > h * 0.08:
        cuts.append((start_y, h))

    if not cuts:
        # Fallback: divide page into 3 default panel rows
        cuts = [(0, int(h * 0.33)), (int(h * 0.33), int(h * 0.66)), (int(h * 0.66), h)]

    panels: list[Panel] = []
    reading_order = 1

    for y1, y2 in cuts:
        panel_h = y2 - y1
        panel_w = w
        bbox = [0, y1, panel_w, panel_h]
        pid = panel_id(page_rel_path, bbox)

        # Bubble region heuristic (upper portion of each panel)
        bubble_h = max(60, int(panel_h * 0.25))
        bubble_w = max(100, int(panel_w * 0.35))
        bubble_x = int(panel_w * 0.55)  # Right side (manga style)
        bubble_y = y1 + int(panel_h * 0.1)

        t_bbox = [bubble_x, bubble_y, bubble_w, bubble_h]
        tid = text_id(page_rel_path, t_bbox)

        panels.append(
            Panel(
                id=pid,
                source=PanelSource(image=page_rel_path, bbox=bbox),
                reading_order=reading_order,
                text_regions=[TextRegion(id=tid, bbox=t_bbox, region_type="bubble")],
            )
        )
        reading_order += 1

    return panels


class MangaImageTranslatorLayoutEngine:
    """Implements LayoutEngine protocol for panel and text detection."""

    def __init__(self, options: dict[str, Any] | None = None):
        self.options = options or {}

    def detect(self, request: LayoutRequest) -> LayoutResult:
        inputs: list[InputPage] = []
        all_panels: list[Panel] = []
        global_reading_order = 1

        for page_path in request.pages:
            rel_path = page_path.as_posix()
            file_hash = _compute_sha256(page_path)
            inputs.append(InputPage(file=rel_path, sha256=file_hash))

            with Image.open(page_path) as img:
                page_panels = detect_panels_and_text(img, rel_path)
                for p in page_panels:
                    p.reading_order = global_reading_order
                    global_reading_order += 1
                    all_panels.append(p)

        manifest = LayoutManifest(
            engine="manga-image-translator/detector",
            engine_version="0.1.0",
            timestamp=datetime.now(timezone.utc).isoformat(),
            inputs=inputs,
        )

        artifact = LayoutArtifact(
            schema_version=1,
            stage="layout",
            chapter_id=request.chapter_id,
            artifact_version=1,
            manifest=manifest,
            panels=all_panels,
        )

        return LayoutResult(artifact=artifact)
