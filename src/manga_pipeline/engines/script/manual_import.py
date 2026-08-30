"""Manual script import engine adapter."""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from manga_pipeline.core.ids import unit_id
from manga_pipeline.core.schemas.artifact_script import (
    ScriptArtifact,
    ScriptDependsOn,
    ScriptManifest,
    ScriptUnit,
)
from manga_pipeline.engines.protocols import ScriptEngine, ScriptRequest, ScriptResult


class ManualScriptEngine(ScriptEngine):
    """Implements ScriptEngine for manual script import (parity default mode)."""

    def __init__(self, options: dict[str, Any] | None = None):
        self.options = options or {}

    def produce(self, request: ScriptRequest) -> ScriptResult:
        units: list[ScriptUnit] = []
        unassigned: list[dict[str, Any]] = []

        # Map reading order to panel ID
        panels_by_reading_order = {
            p.texts[0].reading_order if p.texts else idx + 1: p.id for idx, p in enumerate(request.ocr_artifact.panels)
        }
        # Default fallback to panel list indexing
        panels_list = [p.id for p in request.ocr_artifact.panels]

        script_text = ""
        if request.source_file and Path(request.source_file).exists():
            script_text = Path(request.source_file).read_text(encoding="utf-8")
        else:
            # Generate script from extracted OCR texts or fallback narration
            for idx, p in enumerate(request.ocr_artifact.panels):
                if p.texts:
                    combined_ocr = " ".join(t.original.strip() for t in p.texts if t.original.strip())
                    script_text += f"## p:{idx + 1}\n[dialogue] {combined_ocr}\n"
                else:
                    script_text += f"## p:{idx + 1}\n[narration] Lời dẫn chuyện cho khung tranh {idx + 1}.\n"

        # Parse marker: ## p:<reading_order>
        panel_seq_counter: dict[str, int] = {}
        current_panel_id: str | None = None

        lines = script_text.strip().splitlines()
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            marker_match = re.match(r"^##\s*p:(\d+)", line_str)
            if marker_match:
                order_num = int(marker_match.group(1))
                if order_num <= len(panels_list):
                    current_panel_id = panels_list[order_num - 1]
                else:
                    current_panel_id = panels_by_reading_order.get(order_num)
                continue

            # Parse line content: [type:speaker] text
            unit_type: Literal["narration", "dialogue", "sfx"] = "narration"
            speaker: str | None = None
            clean_text = line_str

            tag_match = re.match(r"^\[(narration|dialogue|sfx)(?::([^\]]+))?\]\s*(.*)$", line_str, re.IGNORECASE)
            if tag_match:
                raw_type = tag_match.group(1).lower()
                if raw_type in ("narration", "dialogue", "sfx"):
                    unit_type = raw_type  # type: ignore[assignment]
                speaker = tag_match.group(2)
                clean_text = tag_match.group(3)

            if current_panel_id:
                seq = panel_seq_counter.get(current_panel_id, 0) + 1
                panel_seq_counter[current_panel_id] = seq
                uid = unit_id(current_panel_id, seq, unit_type)

                units.append(
                    ScriptUnit(
                        id=uid,
                        panel_id=current_panel_id,
                        seq=seq,
                        type=unit_type,
                        text=clean_text,
                        speaker_id_hint=speaker,
                    )
                )
            else:
                unassigned.append({"raw_line": line_str, "text": clean_text})

        manifest = ScriptManifest(
            mode="manual_script",
            engine="manual_import",
            source_file=str(request.source_file) if request.source_file else "auto_generated",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        depends_on = ScriptDependsOn(
            stage="ocr",
            artifact_version=request.ocr_artifact.artifact_version,
        )

        artifact = ScriptArtifact(
            schema_version=1,
            stage="script",
            chapter_id=request.chapter_id,
            artifact_version=1,
            depends_on=depends_on,
            manifest=manifest,
            units=units,
            unassigned=unassigned,
        )

        return ScriptResult(artifact=artifact)
