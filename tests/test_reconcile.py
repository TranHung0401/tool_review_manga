"""DoD (b)(c): Reconcile and anchor remap tests."""

import pytest

from manga_pipeline.core.anchors import AnchorStore
from manga_pipeline.core.reconcile import (
    ImageSourceChangedWarning,
    calculate_iou,
    reconcile_layout,
)
from manga_pipeline.core.schemas.artifact_layout import (
    LayoutArtifact,
    LayoutManifest,
    Panel,
    PanelSource,
)
from manga_pipeline.core.schemas.project_schema import (
    ProjectSchema,
    StoryMetadata,
    TextOverride,
)


def create_sample_layout(version: int, panels_data: list[tuple[str, str, list[int]]]) -> LayoutArtifact:
    panels = [
        Panel(
            id=pid,
            source=PanelSource(image=img, bbox=bbox),
            reading_order=idx + 1,
        )
        for idx, (pid, img, bbox) in enumerate(panels_data)
    ]
    return LayoutArtifact(
        schema_version=1,
        stage="layout",
        chapter_id="ch01",
        artifact_version=version,
        manifest=LayoutManifest(
            engine="test_detector",
            engine_version="1.0",
            timestamp="2026-08-30T10:00:00Z",
        ),
        panels=panels,
    )


def test_iou_calculation() -> None:
    box1 = [100, 100, 200, 200]  # area 40000
    box2 = [100, 100, 200, 200]  # identical
    assert calculate_iou(box1, box2) == 1.0

    box3 = [
        200,
        100,
        200,
        200,
    ]  # 50% overlap in x -> overlap 100x200 = 20000; union = 40000 + 40000 - 20000 = 60000 -> 1/3
    assert pytest.approx(calculate_iou(box1, box3), 0.01) == 0.333

    box_disjoint = [500, 500, 100, 100]
    assert calculate_iou(box1, box_disjoint) == 0.0


def test_first_import_creates_initial_anchors() -> None:
    project = ProjectSchema(story=StoryMetadata(title="Test", chapters=["ch01"]))
    store = AnchorStore(project)

    layout_v1 = create_sample_layout(
        1,
        [
            ("p_111", "pages/001.png", [100, 100, 500, 400]),
            ("p_222", "pages/001.png", [100, 550, 500, 400]),
        ],
    )

    res = reconcile_layout(None, layout_v1, store)
    assert len(res.new_anchors) == 2
    assert len(project.anchors) == 2
    assert project.anchors["pa_000001"].current == "p_111"
    assert project.anchors["pa_000002"].current == "p_222"


def test_rerun_same_segmentation_anchor_stable() -> None:
    """DoD (b): Re-run with identical panels keeps current anchor unchanged."""
    project = ProjectSchema(story=StoryMetadata(title="Test", chapters=["ch01"]))
    store = AnchorStore(project)

    layout_v1 = create_sample_layout(
        1,
        [
            ("p_111", "pages/001.png", [100, 100, 500, 400]),
        ],
    )
    reconcile_layout(None, layout_v1, store)

    # Re-run producing same panel
    layout_v2 = create_sample_layout(
        2,
        [
            ("p_111", "pages/001.png", [100, 100, 500, 400]),
        ],
    )
    res = reconcile_layout(layout_v1, layout_v2, store)

    assert len(res.matched_exact) == 1
    assert project.anchors["pa_000001"].current == "p_111"
    assert len(res.orphaned) == 0


def test_different_segmentation_anchor_remap() -> None:
    """DoD (b): Re-run with slightly shifted bbox (IoU >= 0.6) remaps anchor to new AI ID."""
    project = ProjectSchema(story=StoryMetadata(title="Test", chapters=["ch01"]))
    store = AnchorStore(project)

    layout_v1 = create_sample_layout(
        1,
        [
            ("p_old111", "pages/001.png", [100, 100, 500, 400]),
        ],
    )
    reconcile_layout(None, layout_v1, store)

    # Re-run producing slightly different bbox (IoU ~ 0.85) -> new hash ID
    layout_v2 = create_sample_layout(
        2,
        [
            ("p_new222", "pages/001.png", [105, 105, 495, 395]),
        ],
    )
    res = reconcile_layout(layout_v1, layout_v2, store)

    assert len(res.remapped) == 1
    anchor_id, old_id, new_id, iou_val = res.remapped[0]
    assert anchor_id == "pa_000001"
    assert old_id == "p_old111"
    assert new_id == "p_new222"
    assert iou_val >= 0.6
    assert project.anchors["pa_000001"].current == "p_new222"
    assert project.anchors["pa_000001"].history == ["p_old111", "p_new222"]


def test_locked_anchor_never_auto_remapped() -> None:
    """Locked user-drawn panels are immune to auto-remapping."""
    project = ProjectSchema(story=StoryMetadata(title="Test", chapters=["ch01"]))
    store = AnchorStore(project)

    layout_v1 = create_sample_layout(
        1,
        [
            ("p_user_drawn", "pages/001.png", [0, 0, 1000, 1000]),
        ],
    )
    reconcile_layout(None, layout_v1, store)
    project.anchors["pa_000001"].locked = True

    # Detector re-runs and detects a shifted panel at same spot
    layout_v2 = create_sample_layout(
        2,
        [
            ("p_ai_detected", "pages/001.png", [10, 10, 980, 980]),
        ],
    )
    res = reconcile_layout(layout_v1, layout_v2, store)
    assert len(res.matched_exact) == 1

    # Anchor remains locked to p_user_drawn
    assert project.anchors["pa_000001"].current == "p_user_drawn"
    assert project.anchors["pa_000001"].locked is True


def test_rename_source_image_anchor_survives() -> None:
    """DoD (c): Renaming source image changes AI Hash ID, but persistent anchor and user overrides survive."""
    project = ProjectSchema(story=StoryMetadata(title="Test", chapters=["ch01"]))
    store = AnchorStore(project)

    # Initial import: panel on page 001.png
    layout_v1 = create_sample_layout(
        1,
        [
            ("p_old_name_hash", "pages/001.png", [100, 100, 500, 400]),
        ],
    )
    reconcile_layout(None, layout_v1, store)

    # User adds an override on persistent anchor pa_000001
    project.overrides["ta_000001"] = TextOverride(text="User edited text override", reviewed=True)

    # User renames source image to page_01.png -> new AI Hash ID generated
    layout_v2 = create_sample_layout(
        2,
        [
            ("p_new_name_hash", "pages/page_01.png", [100, 100, 500, 400]),
        ],
    )

    # Reconcile or manual remap updates anchor.current to new hash ID
    store.update_current("pa_000001", layout_v2.panels[0].id)

    # Verify: persistent anchor is updated, and user override on anchor is still intact
    assert project.anchors["pa_000001"].current == "p_new_name_hash"
    assert "p_old_name_hash" in project.anchors["pa_000001"].history
    assert project.overrides["ta_000001"].text == "User edited text override"


def test_resize_source_image_anchor_survives() -> None:
    """DoD (c): Resizing source image with scale_factor allows reconcile to remap correctly."""
    project = ProjectSchema(story=StoryMetadata(title="Test", chapters=["ch01"]))
    store = AnchorStore(project)

    # Original size: 1000x1000, panel at [100, 100, 500, 400]
    layout_v1 = create_sample_layout(
        1,
        [
            ("p_orig_hash", "pages/001.png", [100, 100, 500, 400]),
        ],
    )
    reconcile_layout(None, layout_v1, store)

    # Resized to 50% (500x500): panel at [50, 50, 250, 200] -> scale_factor = 0.5
    layout_v2 = create_sample_layout(
        2,
        [
            ("p_resized_hash", "pages/001.png", [50, 50, 250, 200]),
        ],
    )

    res = reconcile_layout(layout_v1, layout_v2, store, scale_factor=0.5)

    assert len(res.remapped) == 1
    assert project.anchors["pa_000001"].current == "p_resized_hash"
    assert "p_orig_hash" in project.anchors["pa_000001"].history


def test_orphaned_override_not_silently_lost() -> None:
    """Orphaned anchors preserve all attached overrides in project.json without silent loss."""
    project = ProjectSchema(story=StoryMetadata(title="Test", chapters=["ch01"]))
    store = AnchorStore(project)

    layout_v1 = create_sample_layout(
        1,
        [
            ("p_111", "pages/001.png", [100, 100, 200, 200]),
        ],
    )
    reconcile_layout(None, layout_v1, store)
    ta_id = store.create_anchor("text", "t_111")
    project.overrides[ta_id] = TextOverride(text="Important user edit", reviewed=True)

    # Re-run layout with panel removed -> anchor becomes orphaned
    layout_v2 = create_sample_layout(
        2,
        [
            ("p_999", "pages/001.png", [800, 800, 100, 100]),
        ],
    )
    res = reconcile_layout(layout_v1, layout_v2, store, mode="merge")

    assert "pa_000001" in res.orphaned
    # User's override is still in project.json
    assert ta_id in project.overrides
    assert project.overrides[ta_id].text == "Important user edit"


def test_guided_mode_raises_on_complete_source_change() -> None:
    """Guided mode raises ImageSourceChangedWarning when >80% anchors are orphaned."""
    project = ProjectSchema(story=StoryMetadata(title="Test", chapters=["ch01"]))
    store = AnchorStore(project)

    # Initial 5 panels on chapter 1
    layout_v1 = create_sample_layout(1, [(f"p_{i}", "pages/001.png", [100 * i, 100, 80, 80]) for i in range(5)])
    reconcile_layout(None, layout_v1, store)

    # User accidentally passes entirely different images (002.png) with no overlap
    layout_v2 = create_sample_layout(2, [(f"p_new_{i}", "pages/002.png", [500, 500, 80, 80]) for i in range(5)])

    with pytest.raises(ImageSourceChangedWarning):
        reconcile_layout(layout_v1, layout_v2, store, mode="guided")
