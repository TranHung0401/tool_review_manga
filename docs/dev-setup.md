# Manga to Video Pipeline — Development Setup & Guide

## Requirements
- **OS**: Windows 10/11 or Linux
- **Python**: Python 3.10+ (tested with Python 3.14)
- **Package Manager**: [uv](https://github.com/astral-sh/uv)
- **Rendering Engine**: FFmpeg (with optional NVIDIA `h264_nvenc` support)
- **Hardware Reference**: 32 GB RAM, 4 GB VRAM (e.g. Quadro T1000 with NVENC)

---

## 1. Quick Installation

```bash
# Clone and install dependencies
uv sync --extra dev
```

---

## 2. Running the Complete End-to-End Pipeline

To process a manga chapter from raw image pages to final MP4 video:

```bash
uv run manga-pipeline run-all <chapter_id> --pages <path_to_pages_folder> [--output renders/<chapter_id>.mp4]
```

### Example:
```bash
uv run manga-pipeline run-all ch_sample --pages tests/fixtures/ch_sample/pages --output renders/ch_sample.mp4
```

---

## 3. Web Dashboard (Giao diện đồ họa cục bộ)
Để mở Dashboard giao diện trực quan trên trình duyệt:

```bash
uv run manga-pipeline ui --port 8000
```
Truy cập: `http://127.0.0.1:8000`

---

## 4. Individual Stage Commands

The batch pipeline is modular and idempotent:

```bash
# Stage 0: Import from Local Folder
# (Tự động nạp qua UI hoặc CLI)

# Stage 1: Layout Detection
uv run manga-pipeline layout ch01 --pages pages/

# Stage 2: OCR Extraction
uv run manga-pipeline ocr ch01

# Stage 3: Script Production (manual import default mode)
uv run manga-pipeline script ch01 [--file script.txt]

# Stage 4: Speech Synthesis (TTS)
uv run manga-pipeline tts ch01 [--voice vi-VN-HoaiMyNeural]

# Stage 5: Deterministic Render to MP4
uv run manga-pipeline render ch01 [--output renders/ch01.mp4]
```

---

## 4. Architecture Principles & 2-Tier ID System
- **Tier 1 (AI Hash IDs)**: `p_...`, `t_...`, `s_...` hash generated from source image + normalized bbox `[x, y, w, h]`.
- **Tier 2 (Persistent Anchors)**: `pa_...`, `ta_...`, `sa_...` owned by `project.json`.
- **Reconcile Engine**: Re-running AI auto-remaps anchors (IoU >= 0.6) and triggers **Guided Mode** warning if >80% anchors are orphaned.

---

## 5. Running Verification & DoD Tests

```bash
# Run full DoD test suite (7 criteria)
uv run pytest -v

# Run linting & type checks
uv run ruff check src tests
uv run mypy src tests
```
