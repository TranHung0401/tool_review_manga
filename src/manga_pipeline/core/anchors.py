"""Persistent Anchors Store (Tier 2 IDs)."""

from typing import Literal

from manga_pipeline.core.schemas.project_schema import AnchorEntry, ProjectSchema


class AnchorStore:
    """Manages persistent project anchors (pa_, ta_, sa_) inside project.json state."""

    def __init__(self, project: ProjectSchema):
        self.project = project

    def _next_sequence_id(self, prefix: str) -> str:
        """Find next available 6-digit sequence ID for given prefix (pa_, ta_, sa_)."""
        max_num = 0
        for anchor_id in self.project.anchors:
            if anchor_id.startswith(prefix):
                try:
                    num = int(anchor_id[len(prefix) :])
                    if num > max_num:
                        max_num = num
                except ValueError:
                    pass
        return f"{prefix}{max_num + 1:06d}"

    def create_anchor(
        self,
        kind: Literal["panel", "text", "unit"],
        current_ai_id: str,
        locked: bool = False,
    ) -> str:
        """Create a new persistent anchor pointing to the initial current AI artifact ID."""
        prefix_map = {"panel": "pa_", "text": "ta_", "unit": "sa_"}
        prefix = prefix_map[kind]
        anchor_id = self._next_sequence_id(prefix)

        entry = AnchorEntry(
            kind=kind,
            current=current_ai_id,
            history=[current_ai_id],
            locked=locked,
            retired=False,
        )
        self.project.anchors[anchor_id] = entry
        return anchor_id

    def update_current(self, anchor_id: str, new_ai_id: str) -> None:
        """Update anchor's current AI ID and append to history."""
        if anchor_id not in self.project.anchors:
            raise KeyError(f"Anchor '{anchor_id}' does not exist in project anchors.")
        anchor = self.project.anchors[anchor_id]
        anchor.current = new_ai_id
        if new_ai_id not in anchor.history:
            anchor.history.append(new_ai_id)

    def retire(self, anchor_id: str) -> None:
        """Mark anchor as retired without deleting it."""
        if anchor_id not in self.project.anchors:
            raise KeyError(f"Anchor '{anchor_id}' does not exist in project anchors.")
        self.project.anchors[anchor_id].retired = True

    def find_by_ai_id(self, ai_id: str, kind: str | None = None) -> str | None:
        """Lookup active anchor by current AI ID or history."""
        # 1. Check current AI ID first
        for anchor_id, entry in self.project.anchors.items():
            if entry.retired:
                continue
            if kind and entry.kind != kind:
                continue
            if entry.current == ai_id:
                return anchor_id

        # 2. Check history fallback
        for anchor_id, entry in self.project.anchors.items():
            if entry.retired:
                continue
            if kind and entry.kind != kind:
                continue
            if ai_id in entry.history:
                return anchor_id

        return None

    def get_by_kind(self, kind: Literal["panel", "text", "unit"]) -> dict[str, AnchorEntry]:
        """Get all active anchors of a specific kind."""
        return {aid: entry for aid, entry in self.project.anchors.items() if entry.kind == kind and not entry.retired}
