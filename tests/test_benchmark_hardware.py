"""Sprint 0: benchmark harness + hardware detection tests."""

import json
from pathlib import Path

from manga_pipeline.benchmark.gen_report import render_markdown
from manga_pipeline.benchmark.harness import BenchmarkHarness
from manga_pipeline.core.hardware import HardwareProfile, _recommend_gpu_layers, detect_hardware


def test_detect_hardware_returns_profile() -> None:
    profile = detect_hardware()
    assert isinstance(profile, HardwareProfile)
    d = profile.to_dict()
    assert "has_nvenc" in d
    assert "recommended_gpu_layers" in d
    assert d["ram_total_mb"] is None or d["ram_total_mb"] > 0


def test_gpu_layers_auto_policy() -> None:
    assert _recommend_gpu_layers(None) == 0
    assert _recommend_gpu_layers(16000) == -1  # full offload
    assert _recommend_gpu_layers(8000) == 32
    assert _recommend_gpu_layers(4000) == 16  # reference dev machine (T1000 4GB)
    assert _recommend_gpu_layers(1000) == 0


def test_harness_measures_stage_and_writes_report(tmp_path: Path) -> None:
    harness = BenchmarkHarness("ch01")

    result = harness.measure("layout", lambda: sum(range(1000)), items=4)
    assert result == 499500
    assert len(harness.report.stages) == 1
    m = harness.report.stages[0]
    assert m.stage == "layout"
    assert m.items_processed == 4
    assert m.wall_seconds >= 0
    assert m.cloud_cost_usd == 0.0

    report_path = harness.write_report(tmp_path / "bench" / "ch01.json")
    assert report_path.exists()
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["chapter_id"] == "ch01"
    assert data["parity_zero_cloud_cost"] is True  # architecture §10: parity = $0
    assert "hardware" in data


def test_harness_tracks_cloud_cost() -> None:
    harness = BenchmarkHarness("ch01")
    harness.measure("ai_narrate", lambda: None, items=1, cloud_cost_usd=0.05)
    assert harness.report.total_cloud_cost_usd == 0.05
    assert harness.report.to_dict()["parity_zero_cloud_cost"] is False


def test_tts_rtf_measurement() -> None:
    harness = BenchmarkHarness("ch01")
    harness.measure_tts_rtf("tts", lambda: None, audio_ms_out=5000)
    extra = harness.report.stages[0].extra
    assert "rtf" in extra
    assert extra["audio_ms_out"] == 5000


def test_gen_report_markdown() -> None:
    harness = BenchmarkHarness("ch01")
    harness.measure("ocr", lambda: None, items=10)
    md = render_markdown(harness.report.to_dict())
    assert "# Benchmark Report — ch01" in md
    assert "| ocr |" in md
    assert "parity $0" in md
