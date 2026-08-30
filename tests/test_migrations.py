"""Sprint 0: N-1 one-way migration policy tests (golden)."""

import pytest

from manga_pipeline.core.migrations import (
    UnsupportedSchemaVersionError,
    migrate_document,
    register_migrator,
    supported_versions,
)


def test_supported_window_is_n_and_n_minus_1() -> None:
    assert supported_versions(1) == (1, 1)
    assert supported_versions(2) == (1, 2)
    assert supported_versions(5) == (4, 5)


def test_current_version_passes_through_untouched() -> None:
    doc = {"schema_version": 1, "stage": "layout", "panels": [1, 2, 3]}
    out = migrate_document(doc, kind="layout", current_version=1)
    assert out is doc


def test_newer_version_rejected_explicitly() -> None:
    doc = {"schema_version": 3}
    with pytest.raises(UnsupportedSchemaVersionError, match="newer than supported"):
        migrate_document(doc, kind="layout", current_version=1)


def test_older_than_n_minus_1_rejected() -> None:
    doc = {"schema_version": 1}
    with pytest.raises(UnsupportedSchemaVersionError, match="N-1 policy"):
        migrate_document(doc, kind="layout", current_version=3)


def test_golden_migration_v1_to_v2() -> None:
    """Golden test template: registering a migrator upgrades N-1 docs one-way."""

    @register_migrator("golden_kind", 1)
    def _v1_to_v2(data: dict) -> dict:  # type: ignore[type-arg]
        data["schema_version"] = 2
        data["renamed_field"] = data.pop("old_field", None)
        return data

    doc_v1 = {"schema_version": 1, "old_field": "value", "stage": "golden_kind"}
    out = migrate_document(doc_v1, kind="golden_kind", current_version=2)

    assert out["schema_version"] == 2
    assert out["renamed_field"] == "value"
    assert "old_field" not in out


def test_missing_migrator_raises() -> None:
    doc = {"schema_version": 1}
    with pytest.raises(UnsupportedSchemaVersionError, match="No migrator registered"):
        migrate_document(doc, kind="kind_without_migrator", current_version=2)
