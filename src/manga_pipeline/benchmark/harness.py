"""Benchmark harness measuring real pipeline stages (architecture §10).

Standard output: one real chapter end-to-end; the parity path
(manual/translate) must measure $0 cloud cost.

Metrics per stage:
    Layout   pages/min
    OCR      pages/min, CPU%, RAM
    Script   (translate) units/sec
    TTS      RTF (real-time factor) per provider
    Render   wall seconds for 1080p
    Export   bundle generation time + effect mapping ratio
"""

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from manga_pipeline.core.hardware import detect_hardware


@dataclass
class StageMetric:
    stage: str
    wall_seconds: float
    items_processed: int
    throughput_per_min: float
    cloud_cost_usd: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkReport:
    chapter_id: str
    started_at: str
    hardware: dict[str, Any] = field(default_factory=dict)
    stages: list[StageMetric] = field(default_factory=list)
    total_wall_seconds: float = 0.0
    total_cloud_cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapter_id": self.chapter_id,
            "started_at": self.started_at,
            "hardware": self.hardware,
            "stages": [asdict(s) for s in self.stages],
            "total_wall_seconds": self.total_wall_seconds,
            "total_cloud_cost_usd": self.total_cloud_cost_usd,
            "parity_zero_cloud_cost": self.total_cloud_cost_usd == 0.0,
        }


class BenchmarkHarness:
    """Times pipeline stages and produces a JSON benchmark report."""

    def __init__(self, chapter_id: str):
        self.chapter_id = chapter_id
        self.report = BenchmarkReport(
            chapter_id=chapter_id,
            started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            hardware=detect_hardware().to_dict(),
        )

    def measure(
        self,
        stage: str,
        fn: Any,
        items: int = 1,
        cloud_cost_usd: float = 0.0,
        **extra: Any,
    ) -> Any:
        """Run ``fn()`` timing the wall clock and recording throughput."""
        start = time.perf_counter()
        result = fn()
        elapsed = time.perf_counter() - start

        throughput = (items / elapsed * 60.0) if elapsed > 0 else 0.0
        metric = StageMetric(
            stage=stage,
            wall_seconds=round(elapsed, 4),
            items_processed=items,
            throughput_per_min=round(throughput, 2),
            cloud_cost_usd=cloud_cost_usd,
            extra=extra,
        )
        self.report.stages.append(metric)
        self.report.total_wall_seconds = round(self.report.total_wall_seconds + elapsed, 4)
        self.report.total_cloud_cost_usd += cloud_cost_usd
        return result

    def measure_tts_rtf(self, stage: str, fn: Any, audio_ms_out: int) -> Any:
        """Measure TTS with Real-Time Factor = synth_time / audio_duration."""
        start = time.perf_counter()
        result = fn()
        elapsed = time.perf_counter() - start
        rtf = elapsed / (audio_ms_out / 1000.0) if audio_ms_out > 0 else 0.0
        metric = StageMetric(
            stage=stage,
            wall_seconds=round(elapsed, 4),
            items_processed=1,
            throughput_per_min=0.0,
            extra={"rtf": round(rtf, 4), "audio_ms_out": audio_ms_out},
        )
        self.report.stages.append(metric)
        self.report.total_wall_seconds = round(self.report.total_wall_seconds + elapsed, 4)
        return result

    def write_report(self, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = output_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.report.to_dict(), f, indent=2, ensure_ascii=False)
        tmp.replace(output_path)
        return output_path
