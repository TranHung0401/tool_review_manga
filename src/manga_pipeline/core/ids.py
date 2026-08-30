"""Hash ID generation for AI Artifacts (Tier 1 IDs)."""

import hashlib
from pathlib import Path


def normalize_bbox(bbox: list[int]) -> str:
    """Normalize integer bbox [x, y, w, h] to canonical string representation."""
    if len(bbox) != 4:
        raise ValueError(f"BBox must have 4 integers [x, y, w, h], got {bbox}")
    x, y, w, h = (int(v) for v in bbox)
    return f"{x},{y},{w},{h}"


def _normalize_filename(page_file: str) -> str:
    """Normalize file path to unix-style relative path to avoid platform differences."""
    return Path(page_file).as_posix()


def panel_id(page_file: str, bbox: list[int]) -> str:
    """Generate panel ID (p_ + sha1[:12])."""
    canonical_file = _normalize_filename(page_file)
    canonical_bbox = normalize_bbox(bbox)
    raw = f"{canonical_file}:{canonical_bbox}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"p_{digest}"


def text_id(page_file: str, bbox: list[int]) -> str:
    """Generate text region ID (t_ + sha1[:12])."""
    canonical_file = _normalize_filename(page_file)
    canonical_bbox = normalize_bbox(bbox)
    raw = f"{canonical_file}:{canonical_bbox}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"t_{digest}"


def unit_id(panel_id_val: str, seq: int, unit_type: str) -> str:
    """Generate script unit ID (s_ + sha1[:12])."""
    raw = f"{panel_id_val}:{seq}:{unit_type}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"s_{digest}"
