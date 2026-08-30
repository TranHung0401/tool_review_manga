"""CapCut Project Exporter Stub (Full implementation in Sprint 3)."""

from pathlib import Path
from typing import Any

from manga_pipeline.render.plan import RenderPlan


class CapCutProjectExporter:
    """
    Serializes deterministic RenderPlan to CapCut PC project bundles.
    Implementation will be based on reverse-engineered fixtures in Sprint 3.
    """

    SUPPORTED_CAPCUT_VERSIONS = ["5.0.0", "5.1.0"]

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def export(self, plan: RenderPlan) -> dict[str, Any]:
        """Stub export method returning bundle metadata."""
        return {
            "status": "stub",
            "sprint_milestone": 3,
            "chapter_id": plan.chapter_id,
            "supported_versions": self.SUPPORTED_CAPCUT_VERSIONS,
            "clips_count": len(plan.video_clips),
        }
