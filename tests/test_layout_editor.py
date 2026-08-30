"""Sprint 2: Layout Editor resolved-layout tests (delete/merge/draw/order)."""

from manga_pipeline.core.anchors import AnchorStore
from manga_pipeline.core.layout_resolve import layout_overrides_hash, resolve_layout
from manga_pipeline.core.schemas.artifact_layout import (
    LayoutArtifact,
    LayoutManifest,
    Panel,
    PanelSource,
)
from manga_pipeline.core.schemas.project_schema import (
    ChapterLayoutOverrides,
    MergeOverride,
    ProjectSchema,
    StoryMetadata,
    UserPanelOverride,
)


def _layout(panels_data: list[tuple[str, str, list[int]]]) -> LayoutArtifact:
    return LayoutArtifact(
        schema_version=1,
        stage="layout",
        chapter_id="ch01",
        artifact_version=1,
        manifest=LayoutManifest(engine="test", engine_version="1.0", timestamp="2026-08-30T10:00:00Z"),
        panels=[
            Panel(id=pid, source=PanelSource(image=img, bbox=bbox), reading_order=i + 1)
            for i, (pid, img, bbox) in enumerate(panels_data)
        ],
    )


def _project_with_anchors(layout: LayoutArtifact) -> tuple[ProjectSchema, dict[str, str]]:
    proj = ProjectSchema(story=StoryMetadata(title="T", chapters=["ch01"]))
    store = AnchorStore(proj)
    mapping = {}
    for p in layout.panels:
        mapping[p.id] = store.create_anchor("panel", p.id)
    return proj, mapping


def test_resolve_without_overrides_is_identity() -> None:
    layout = _layout([("p_aaa111222333", "pages/001.png", [0, 0, 100, 100])])
    proj, _ = _project_with_anchors(layout)
    resolved = resolve_layout(layout, proj, "ch01")
    assert [p.id for p in resolved.panels] == [p.id for p in layout.panels]


def test_delete_panel() -> None:
    layout = _layout(
        [
            ("p_aaa111222333", "pages/001.png", [0, 0, 100, 100]),
            ("p_bbb444555666", "pages/001.png", [0, 120, 100, 100]),
        ]
    )
    proj, m = _project_with_anchors(layout)
    proj.layout_overrides["ch01"] = ChapterLayoutOverrides(deleted_panels=[m["p_aaa111222333"]])

    resolved = resolve_layout(layout, proj, "ch01")
    assert len(resolved.panels) == 1
    assert resolved.panels[0].id == "p_bbb444555666"
    assert resolved.panels[0].reading_order == 1  # renumbered


def test_merge_panels_union_bbox() -> None:
    layout = _layout(
        [
            ("p_aaa111222333", "pages/001.png", [0, 0, 100, 100]),
            ("p_bbb444555666", "pages/001.png", [50, 50, 100, 100]),
        ]
    )
    proj, m = _project_with_anchors(layout)
    proj.layout_overrides["ch01"] = ChapterLayoutOverrides(
        merged=[MergeOverride(into=m["p_aaa111222333"], **{"from": [m["p_bbb444555666"]]})]
    )

    resolved = resolve_layout(layout, proj, "ch01")
    assert len(resolved.panels) == 1
    assert resolved.panels[0].source.bbox == [0, 0, 150, 150]  # union


def test_user_drawn_panel_appended_locked() -> None:
    layout = _layout([("p_aaa111222333", "pages/001.png", [0, 0, 100, 100])])
    proj, _ = _project_with_anchors(layout)
    store = AnchorStore(proj)
    user_anchor = store.create_anchor("panel", "p_placeholder0", locked=True)
    proj.layout_overrides["ch01"] = ChapterLayoutOverrides(
        user_panels=[
            UserPanelOverride(
                anchor=user_anchor,
                source=PanelSource(image="pages/002.png", bbox=[0, 0, 900, 1300]),
                reading_order=2,
                locked=True,
            )
        ]
    )

    resolved = resolve_layout(layout, proj, "ch01")
    assert len(resolved.panels) == 2
    drawn = resolved.panels[1]
    assert drawn.source.image == "pages/002.png"
    # Anchor now points to the real hash ID computed from image+bbox
    assert proj.anchors[user_anchor].current == drawn.id
    assert proj.anchors[user_anchor].locked is True


def test_reading_order_override_resorts() -> None:
    layout = _layout(
        [
            ("p_aaa111222333", "pages/001.png", [0, 0, 100, 100]),
            ("p_bbb444555666", "pages/001.png", [0, 120, 100, 100]),
        ]
    )
    proj, m = _project_with_anchors(layout)
    proj.layout_overrides["ch01"] = ChapterLayoutOverrides(
        reading_order_overrides={m["p_aaa111222333"]: 5}
    )

    resolved = resolve_layout(layout, proj, "ch01")
    assert resolved.panels[0].id == "p_bbb444555666"
    assert resolved.panels[1].id == "p_aaa111222333"
    assert [p.reading_order for p in resolved.panels] == [1, 2]


def test_overrides_hash_deterministic_and_sensitive() -> None:
    ov1 = ChapterLayoutOverrides(deleted_panels=["pa_000001"])
    ov2 = ChapterLayoutOverrides(deleted_panels=["pa_000001"])
    ov3 = ChapterLayoutOverrides(deleted_panels=["pa_000002"])
    assert layout_overrides_hash(ov1) == layout_overrides_hash(ov2)
    assert layout_overrides_hash(ov1) != layout_overrides_hash(ov3)
    assert layout_overrides_hash(None) == layout_overrides_hash(None)


def test_original_artifact_never_mutated() -> None:
    """Immutability: resolve produces a materialized view, source untouched."""
    layout = _layout(
        [
            ("p_aaa111222333", "pages/001.png", [0, 0, 100, 100]),
            ("p_bbb444555666", "pages/001.png", [0, 120, 100, 100]),
        ]
    )
    proj, m = _project_with_anchors(layout)
    proj.layout_overrides["ch01"] = ChapterLayoutOverrides(deleted_panels=[m["p_aaa111222333"]])

    resolve_layout(layout, proj, "ch01")
    assert len(layout.panels) == 2  # source artifact untouched
    assert layout.panels[0].reading_order == 1
