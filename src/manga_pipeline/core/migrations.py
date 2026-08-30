"""Schema migration policy (Sprint 0 — N-1, one-way).

Architecture §6.3: the app reads the CURRENT ``schema_version`` and N-1.
Migrators are one-way (older → newer). Raising a schema version requires a
migrator plus a golden test before merge.

Registered migrators transform raw dicts (as loaded from JSON) so they can
run before Pydantic validation of the current models.
"""

from collections.abc import Callable
from typing import Any

CURRENT_SCHEMA_VERSION = 1

Migrator = Callable[[dict[str, Any]], dict[str, Any]]

# key: (kind, from_version) -> migrator producing from_version + 1
_MIGRATORS: dict[tuple[str, int], Migrator] = {}


class UnsupportedSchemaVersionError(Exception):
    """Raised when a document version is outside the supported N / N-1 window."""


def register_migrator(kind: str, from_version: int) -> Callable[[Migrator], Migrator]:
    """Decorator registering a one-way migrator for ``kind`` documents."""

    def _wrap(fn: Migrator) -> Migrator:
        _MIGRATORS[(kind, from_version)] = fn
        return fn

    return _wrap


def supported_versions(current: int = CURRENT_SCHEMA_VERSION) -> tuple[int, int]:
    """The app reads current and N-1 only."""
    return (max(1, current - 1), current)


def migrate_document(
    data: dict[str, Any],
    kind: str,
    current_version: int = CURRENT_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Migrate a raw document dict up to ``current_version``.

    - Documents already at current version pass through untouched.
    - Documents at N-1 run through the registered migrator chain.
    - Anything older than N-1 or newer than N is rejected explicitly —
      never silently accepted.
    """
    version = int(data.get("schema_version", 1))
    lo, hi = supported_versions(current_version)

    if version == current_version:
        return data
    if version > current_version:
        raise UnsupportedSchemaVersionError(
            f"{kind} document has schema_version={version}, newer than supported {current_version}. "
            "Upgrade the tool to read this document."
        )
    if version < lo:
        raise UnsupportedSchemaVersionError(
            f"{kind} document has schema_version={version}; only versions {lo}..{hi} are readable "
            f"(N-1 policy). Re-run the pipeline stage to regenerate the artifact."
        )

    while version < current_version:
        migrator = _MIGRATORS.get((kind, version))
        if migrator is None:
            raise UnsupportedSchemaVersionError(
                f"No migrator registered for {kind} v{version} -> v{version + 1}."
            )
        data = migrator(dict(data))
        new_version = int(data.get("schema_version", version))
        if new_version <= version:
            raise RuntimeError(
                f"Migrator for {kind} v{version} did not bump schema_version (still {new_version})."
            )
        version = new_version

    return data


# ---------------------------------------------------------------------------
# Example forward-compat scaffold: when schema_version 2 ships, its v1 -> v2
# migrator is registered here alongside a golden test. The identity template
# below documents the required shape without altering v1 behaviour.
# ---------------------------------------------------------------------------

def _template_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover - template
    data["schema_version"] = 2
    return data
