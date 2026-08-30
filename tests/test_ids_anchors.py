"""Unit tests for Tier 1 AI Hash IDs and Tier 2 Persistent Anchors."""

import pytest

from manga_pipeline.core.anchors import AnchorStore
from manga_pipeline.core.ids import normalize_bbox, panel_id, text_id, unit_id
from manga_pipeline.core.schemas.project_schema import ProjectSchema, StoryMetadata


def test_bbox_normalization() -> None:
    assert normalize_bbox([100, 200, 700, 400]) == "100,200,700,400"
    with pytest.raises(ValueError):
        normalize_bbox([100, 200, 300])


def test_hash_id_determinism() -> None:
    p1 = panel_id("pages/001.png", [10, 20, 300, 400])
    p2 = panel_id("pages/001.png", [10, 20, 300, 400])
    p3 = panel_id("pages/002.png", [10, 20, 300, 400])

    assert p1.startswith("p_")
    assert p1 == p2
    assert p1 != p3

    t1 = text_id("pages/001.png", [10, 20, 50, 60])
    assert t1.startswith("t_")

    s1 = unit_id(p1, 1, "dialogue")
    assert s1.startswith("s_")


def test_anchor_store_crud() -> None:
    project = ProjectSchema(story=StoryMetadata(title="Test", chapters=["ch01"]))
    store = AnchorStore(project)

    pa1 = store.create_anchor("panel", "p_111111111111")
    assert pa1 == "pa_000001"
    assert project.anchors[pa1].current == "p_111111111111"
    assert project.anchors[pa1].history == ["p_111111111111"]

    ta1 = store.create_anchor("text", "t_222222222222")
    assert ta1 == "ta_000001"

    sa1 = store.create_anchor("unit", "s_333333333333")
    assert sa1 == "sa_000001"

    # Update current AI ID (re-run AI)
    store.update_current(pa1, "p_999999999999")
    assert project.anchors[pa1].current == "p_999999999999"
    assert project.anchors[pa1].history == ["p_111111111111", "p_999999999999"]

    # Lookup
    assert store.find_by_ai_id("p_999999999999") == pa1
    assert store.find_by_ai_id("p_111111111111") == pa1  # found in history

    # Retire
    store.retire(pa1)
    assert project.anchors[pa1].retired is True
    assert store.find_by_ai_id("p_999999999999") is None  # retired anchors are ignored
