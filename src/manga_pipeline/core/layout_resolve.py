"""Resolved Layout builder (Sprint 2 — Layout Editor pre-OCR workflow).

Architecture rule: ``Auto-detect → Layout Editor (delete/merge/draw/reading
order) → OCR runs on the RESOLVED layout``. User edits live in
``project.json.layout_overrides`` referencing panel anchors (pa_...); the AI
layout artifact stays immutable. This module materializes the resolved view.
"""

import hashlib
import json

from manga_pipeline.core.anchors import AnchorStore
from manga_pipeline.core.ids import panel_id as make_panel_id
from manga_pipeline.core.schemas.artifact_layout import LayoutArtifact, Panel, PanelSource
from manga_pipeline.core.schemas.project_schema import ChapterLayoutOverrides, ProjectSchema


def layout_overrides_hash(overrides: ChapterLayoutOverrides | None) -> str:
    """Deterministic sha1 of active layout overrides, stored in OCR depends_on."""
    payload = overrides.model_dump(by_alias=True) if overrides else {}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def _union_bbox(a: list[int], b: list[int]) -> list[int]:
    x1 = min(a[0], b[0])
    y1 = min(a[1], b[1])
    x2 = max(a[0] + a[2], b[0] + b[2])
    y2 = max(a[1] + a[3], b[1] + b[3])
    return [x1, y1, x2 - x1, y2 - y1]


def resolve_layout(
    layout_artifact: LayoutArtifact,
    project: ProjectSchema,
    chapter_id: str,
) -> LayoutArtifact:
    """Apply layout overrides to produce the resolved layout used by OCR.

    Order of operations:
      1. drop panels whose anchors are in ``deleted_panels``
      2. merge panels (union bbox + combined text regions) per ``merged``
      3. append ``user_panels`` (hand-drawn, locked anchors)
      4. apply ``reading_order_overrides`` then re-sort & re-number

    The returned artifact is a MATERIALIZED VIEW — never written back to
    ``artifacts/`` as a layout version; OCR references it via
    ``layout_overrides_hash`` in its ``depends_on``.
    """
    overrides = project.layout_overrides.get(chapter_id)
    if overrides is None:
        return layout_artifact

    store = AnchorStore(project)

    def anchor_of(ai_id: str) -> str | None:
        return store.find_by_ai_id(ai_id, kind="panel")

    deleted = set(overrides.deleted_panels)
    merge_sources: dict[str, str] = {}  # source anchor -> target anchor
    for m in overrides.merged:
        for src in m.from_:
            merge_sources[src] = m.into

    panels_by_anchor: dict[str, Panel] = {}
    passthrough: list[Panel] = []
    for p in layout_artifact.panels:
        a = anchor_of(p.id)
        if a is None:
            passthrough.append(p.model_copy(deep=True))
            continue
        if a in deleted:
            continue
        panels_by_anchor[a] = p.model_copy(deep=True)

    # 2. merges: union bbox into target, absorb text regions, drop source
    for src_anchor, dst_anchor in merge_sources.items():
        src_panel = panels_by_anchor.pop(src_anchor, None)
        dst_panel = panels_by_anchor.get(dst_anchor)
        if src_panel is None or dst_panel is None:
            continue
        if src_panel.source.image == dst_panel.source.image:
            dst_panel.source.bbox = _union_bbox(dst_panel.source.bbox, src_panel.source.bbox)
        dst_panel.text_regions.extend(src_panel.text_regions)

    resolved: list[tuple[str | None, Panel]] = [(a, p) for a, p in panels_by_anchor.items()]
    resolved.extend((None, p) for p in passthrough)

    # 3. user-drawn panels (locked)
    for up in overrides.user_panels:
        uid = make_panel_id(up.source.image, up.source.bbox)
        entry = project.anchors.get(up.anchor)
        if entry is not None and entry.current != uid:
            store.update_current(up.anchor, uid)
        panel = Panel(
            id=uid,
            source=PanelSource(image=up.source.image, bbox=list(up.source.bbox)),
            reading_order=up.reading_order,
            text_regions=[],
        )
        resolved.append((up.anchor, panel))

    # 4. reading order overrides then stable re-sort
    for a, p in resolved:
        if a is not None and a in overrides.reading_order_overrides:
            p.reading_order = overrides.reading_order_overrides[a]

    resolved.sort(key=lambda ap: ap[1].reading_order)
    for i, (_, p) in enumerate(resolved):
        p.reading_order = i + 1

    return layout_artifact.model_copy(update={"panels": [p for _, p in resolved]})
