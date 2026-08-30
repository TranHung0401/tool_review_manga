"""DoD (f): Script Modes uniformity and Unit Anchor stability tests."""

from manga_pipeline.core.ids import unit_id
from manga_pipeline.core.schemas.artifact_script import (
    ScriptArtifact,
    ScriptDependsOn,
    ScriptManifest,
    ScriptUnit,
)


def test_script_modes_uniform_unit_schema() -> None:
    """DoD (f): All 3 script modes produce the exact same ScriptUnit schema."""
    modes = ["manual_script", "translate", "ai_narrate"]
    artifacts: list[ScriptArtifact] = []

    for mode_name in modes:
        artifact = ScriptArtifact(
            chapter_id="ch01",
            artifact_version=1,
            depends_on=ScriptDependsOn(stage="ocr", artifact_version=1),
            manifest=ScriptManifest(
                mode=mode_name,  # type: ignore[arg-type]
                engine=f"engine_{mode_name}",
                timestamp="2026-08-30T10:00:00Z",
            ),
            units=[
                ScriptUnit(
                    id="s_abc123456789",
                    panel_id="p_panel001",
                    seq=1,
                    type="dialogue",
                    text="Xin chào",
                    source_text_ids=["t_text001"],
                    speaker_id_hint="alice",
                )
            ],
        )
        artifacts.append(artifact)

    for art in artifacts:
        unit = art.units[0]
        assert isinstance(unit, ScriptUnit)
        assert unit.id == "s_abc123456789"
        assert unit.panel_id == "p_panel001"
        assert unit.type == "dialogue"
        assert unit.text == "Xin chào"


def test_unit_anchor_stable_on_rerun() -> None:
    """DoD (f): Re-running script generation on identical panel/seq produces identical s_ hash ID."""
    u1 = unit_id("p_panel001", 1, "narration")
    u2 = unit_id("p_panel001", 1, "narration")
    u3 = unit_id("p_panel001", 2, "narration")

    assert u1 == u2
    assert u1 != u3
    assert u1.startswith("s_")
