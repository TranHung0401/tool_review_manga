"""Reconciliation engine for AI artifacts and persistent anchors."""

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Literal

from manga_pipeline.core.anchors import AnchorStore
from manga_pipeline.core.schemas.artifact_layout import LayoutArtifact, Panel
from manga_pipeline.core.schemas.project_schema import ChapterLayoutOverrides


class ImageSourceChangedError(Exception):
    """Raised in guided mode when the source image set has changed drastically (>80% orphaned)."""


ImageSourceChangedWarning = ImageSourceChangedError


@dataclass
class ReconcileResult:
    matched_exact: list[tuple[str, str]] = field(default_factory=list)  # (anchor_id, ai_id)
    remapped: list[tuple[str, str, str, float]] = field(default_factory=list)  # (anchor_id, old_ai_id, new_ai_id, iou)
    orphaned: list[str] = field(default_factory=list)  # list of anchor_ids
    new_anchors: list[tuple[str, str]] = field(default_factory=list)  # (anchor_id, ai_id)
    warnings: list[str] = field(default_factory=list)
    requires_confirmation: bool = False


def calculate_iou(bbox_a: list[int], bbox_b: list[int]) -> float:
    """Calculate Intersection over Union (IoU) between two [x, y, w, h] boxes."""
    xa1, ya1, wa, ha = bbox_a
    xb1, yb1, wb, hb = bbox_b

    xa2, ya2 = xa1 + wa, ya1 + ha
    xb2, yb2 = xb1 + wb, yb1 + hb

    inter_x1 = max(xa1, xb1)
    inter_y1 = max(ya1, yb1)
    inter_x2 = min(xa2, xb2)
    inter_y2 = min(ya2, yb2)

    inter_w = max(0, inter_x2 - inter_x1)
    inter_h = max(0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h

    area_a = wa * ha
    area_b = wb * hb
    union_area = area_a + area_b - inter_area

    if union_area <= 0:
        return 0.0
    return inter_area / union_area


def text_similarity(str_a: str, str_b: str) -> float:
    """Calculate normalized character similarity ratio between two strings (0.0 to 1.0)."""
    return SequenceMatcher(None, str_a, str_b).ratio()


def reconcile_layout(
    old_layout: LayoutArtifact | None,
    new_layout: LayoutArtifact,
    anchor_store: AnchorStore,
    layout_overrides: ChapterLayoutOverrides | None = None,
    mode: Literal["guided", "merge", "reset"] = "guided",
    iou_threshold: float = 0.6,
    scale_factor: float = 1.0,
) -> ReconcileResult:
    """
    Reconcile new LayoutArtifact with existing persistent anchors.
    Ensures overrides and timeline clips survive AI re-runs.
    """
    result = ReconcileResult()

    new_panels_by_id: dict[str, Panel] = {p.id: p for p in new_layout.panels}
    matched_new_ai_ids: set[str] = set()

    existing_panel_anchors = anchor_store.get_by_kind("panel")
    total_existing = len(existing_panel_anchors)

    # If first import (no existing anchors)
    if total_existing == 0:
        for p in new_layout.panels:
            aid = anchor_store.create_anchor("panel", p.id)
            result.new_anchors.append((aid, p.id))
        return result

    # Build lookup of old panels if old_layout provided
    old_panels_by_id: dict[str, Panel] = {}
    if old_layout:
        old_panels_by_id = {p.id: p for p in old_layout.panels}

    for anchor_id, anchor_entry in existing_panel_anchors.items():
        if anchor_entry.locked:
            # Locked anchor (e.g. user hand-drawn panel) -> keep current, never auto-remap
            result.matched_exact.append((anchor_id, anchor_entry.current))
            continue

        current_ai_id = anchor_entry.current

        # 1. Exact AI ID match
        if current_ai_id in new_panels_by_id:
            matched_new_ai_ids.add(current_ai_id)
            result.matched_exact.append((anchor_id, current_ai_id))
            continue

        # 2. IoU Geometric matching on same page
        best_match_id: str | None = None
        best_iou = 0.0

        old_panel = old_panels_by_id.get(current_ai_id)
        if old_panel:
            old_img = old_panel.source.image
            old_bbox = old_panel.source.bbox

            # Adjust for scale factor if new images were resized
            scaled_old_bbox = [
                int(old_bbox[0] * scale_factor),
                int(old_bbox[1] * scale_factor),
                int(old_bbox[2] * scale_factor),
                int(old_bbox[3] * scale_factor),
            ]

            for new_p in new_layout.panels:
                if new_p.id in matched_new_ai_ids:
                    continue
                if new_p.source.image == old_img:
                    iou_val = calculate_iou(scaled_old_bbox, new_p.source.bbox)
                    if iou_val >= iou_threshold and iou_val > best_iou:
                        best_iou = iou_val
                        best_match_id = new_p.id

        if best_match_id:
            matched_new_ai_ids.add(best_match_id)
            anchor_store.update_current(anchor_id, best_match_id)
            result.remapped.append((anchor_id, current_ai_id, best_match_id, best_iou))
        else:
            result.orphaned.append(anchor_id)

    # Check for drastic source change (>80% orphaned)
    orphan_ratio = len(result.orphaned) / total_existing if total_existing > 0 else 0.0
    if orphan_ratio > 0.8:
        msg = (
            f"Image source appears completely changed: {len(result.orphaned)}/{total_existing} "
            f"({orphan_ratio:.0%}) anchors orphaned. Reconcile paused in guided mode."
        )
        result.warnings.append(msg)
        result.requires_confirmation = True

        if mode == "guided":
            raise ImageSourceChangedWarning(msg)
        elif mode == "reset":
            # User opted to reset old anchors
            for aid in result.orphaned:
                anchor_store.retire(aid)
            result.orphaned.clear()

    # Create new anchors for newly detected panels that weren't matched
    for p in new_layout.panels:
        if p.id not in matched_new_ai_ids and not any(r[2] == p.id for r in result.remapped):
            aid = anchor_store.create_anchor("panel", p.id)
            result.new_anchors.append((aid, p.id))

    return result
