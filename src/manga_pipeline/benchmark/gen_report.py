"""gen_report.py — render benchmark JSON reports as human-readable Markdown.

Usage:
    python -m manga_pipeline.benchmark.gen_report benchmarks/ch01.json [-o report.md]
"""

import argparse
import json
from pathlib import Path
from typing import Any


def render_markdown(report: dict[str, Any]) -> str:
    hw = report.get("hardware", {})
    lines = [
        f"# Benchmark Report — {report.get('chapter_id', '?')}",
        "",
        f"- Started: {report.get('started_at', '?')}",
        f"- Total wall time: {report.get('total_wall_seconds', 0)}s",
        f"- Total cloud cost: ${report.get('total_cloud_cost_usd', 0):.4f}"
        + (" ✅ (parity $0)" if report.get("parity_zero_cloud_cost") else " ⚠️"),
        "",
        "## Hardware",
        f"- FFmpeg: {hw.get('has_ffmpeg')} | NVENC: {hw.get('has_nvenc')}",
        f"- GPU: {hw.get('gpu_name') or 'none'} ({hw.get('vram_total_mb') or '?'} MB VRAM)",
        f"- RAM: {hw.get('ram_total_mb') or '?'} MB",
        f"- Recommended gpu_layers: {hw.get('recommended_gpu_layers')}",
        "",
        "## Stages",
        "",
        "| Stage | Wall (s) | Items | Throughput/min | Cloud $ | Extra |",
        "|---|---|---|---|---|---|",
    ]
    for s in report.get("stages", []):
        extra = ", ".join(f"{k}={v}" for k, v in (s.get("extra") or {}).items()) or "—"
        lines.append(
            f"| {s['stage']} | {s['wall_seconds']} | {s['items_processed']} "
            f"| {s['throughput_per_min']} | {s.get('cloud_cost_usd', 0)} | {extra} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Markdown from benchmark JSON report")
    parser.add_argument("report_json", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=None)
    args = parser.parse_args()

    with open(args.report_json, encoding="utf-8") as f:
        report = json.load(f)

    md = render_markdown(report)
    if args.output:
        args.output.write_text(md, encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(md)


if __name__ == "__main__":
    main()
