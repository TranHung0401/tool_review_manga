# manga-pipeline-sprint0.md
# Sprint 0 — Manga-to-Video Pipeline (Khóa Schema & Nền tảng)

> **Ngày tạo:** 2026-08-30
> **Phương án:** C — Hybrid (Schema Skeleton → Spike thực tế → Harden + DoD)
> **Kiến trúc tham chiếu:** [architecture.md](./architecture.md) — v5 FINAL

---

## Overview

Xây dựng nền tảng schema-first cho pipeline chuyển đổi Comic/Manga thành video, bám sát kiến trúc v5. Sprint 0 là giai đoạn **Khóa Schema**: không có code nào được viết tiếp vào Sprint 1 cho đến khi 7 tiêu chí DoD được vượt qua bằng test thật.

**Mục tiêu:** Kết thúc Sprint 0 với:
1. Toàn bộ schema artifact được định nghĩa và validate được
2. Hệ thống 2-tầng ID (AI hash + persistent anchor) hoạt động đúng
3. Bộ máy Reconcile xử lý được re-run AI và guided-mode khi ảnh nguồn đổi
4. Job system chịu crash-resume với engine_lock
5. Pipeline chạy thật end-to-end → MP4 từ 1 chapter manga mẫu
6. 7 tiêu chí DoD PASS với test fixture thực tế → Schema LOCKED

---

## Project Type

**BACKEND** — Python pipeline core (`backend-specialist`)
**DESKTOP UI** — Electron/Tauri (Sprint 2+, nằm ngoài Sprint 0)

> ⚠️ Sprint 0 là CLI-only. Không có UI. Desktop framework quyết định tại Sprint 1.

---

## Success Criteria (Đo được)

| # | Tiêu chí | Đo lường |
|---|---------|----------|
| 1 | 5 artifact schema + project.json validate JSON Schema | `pytest tests/test_schemas.py` → 100% PASS |
| 2 | Anchor remap đúng khi re-run layout/OCR khác segmentation | `pytest tests/test_reconcile.py::test_different_segmentation_anchor_remap` PASS |
| 3 | Anchor + override sống sót khi đổi tên/resize ảnh nguồn | `pytest tests/test_reconcile.py::test_rename_source_image_anchor_survives` PASS |
| 4 | Job crash-resume giữ engine_lock | `pytest tests/test_jobs.py` → 100% PASS |
| 5 | Re-run TTS không dịch chuyển timeline (trước Resync) | `pytest tests/test_tts_resync.py` → 100% PASS |
| 6 | 3 script mode cho ra cùng schema unit | `pytest tests/test_script_modes.py` → 100% PASS |
| 7 | Render Plan golden test → FFmpeg args + CapCut stub | `pytest tests/test_render_plan.py` → 100% PASS |
| Bonus | Pipeline chạy thật → MP4 từ chapter mẫu | File `renders/ch_sample.mp4` tồn tại và phát được |

---

## Tech Stack

| Layer | Technology | Lý do |
|-------|-----------|-------|
| Runtime | Python 3.10+ | Native hệ sinh thái AI (manga-ocr, manga-image-translator) |
| Schema validation | Pydantic v2 | Type-safe, JSON Schema export, fast |
| Testing | pytest + pytest-snapshot | Golden test Render Plan; snapshot test artifacts |
| Lint / Type check | ruff + mypy | Bắt lỗi sớm, nhất quán |
| Package manager | uv | Nhanh hơn pip; lock file nghiêm túc |
| Layout detect | manga-image-translator (detector only) | Mã nguồn mở, VRAM-aware |
| OCR | manga-ocr (kha-white/manga-ocr-base) | Chuyên manga JP, chạy CPU được |
| TTS | edge-tts | Miễn phí, vi-VN voices, không cần GPU |
| Render | ffmpeg-python | NVENC nếu có, CPU fallback |
| Desktop UI (Sprint 2+) | Electron hoặc Tauri | Quyết định tại Sprint 1 sau khi cấu trúc IPC Python rõ |

---

## File Structure

```text
tool_review_manga_v2/
├── architecture.md                  # Tài liệu kiến trúc — READ ONLY
├── manga-pipeline-sprint0.md        # File plan này
├── pyproject.toml                   # Python project config (uv)
├── src/
│   └── manga_pipeline/
│       ├── __init__.py
│       ├── core/
│       │   ├── schemas/
│       │   │   ├── __init__.py
│       │   │   ├── artifact_layout.py    # Pydantic: layout.*.json
│       │   │   ├── artifact_ocr.py       # Pydantic: ocr.*.json
│       │   │   ├── artifact_script.py    # Pydantic: script.*.json (3 mode)
│       │   │   ├── artifact_tts.py       # Pydantic: tts.*.json
│       │   │   ├── artifact_story.py     # Pydantic: story.*.json (reserved)
│       │   │   └── project_schema.py     # Pydantic: project.json
│       │   ├── ids.py                    # Hash ID generation (p_, t_, s_)
│       │   ├── anchors.py                # Persistent anchor CRUD (pa_, ta_, sa_)
│       │   └── reconcile.py              # IoU matcher, remap, guided-mode
│       ├── engines/
│       │   ├── protocols.py              # Protocol interfaces (4 engines)
│       │   ├── layout/
│       │   │   └── manga_image_translator.py
│       │   ├── ocr/
│       │   │   └── manga_ocr_engine.py
│       │   ├── script/
│       │   │   └── manual_import.py
│       │   └── tts/
│       │       └── edge_tts_engine.py
│       ├── pipeline/
│       │   ├── jobs.py                   # Per-item checkpoint, engine_lock, atomic
│       │   └── stages.py                 # Stage runner (layout/ocr/script/tts)
│       ├── render/
│       │   ├── plan.py                   # Render Plan builder (deterministic)
│       │   ├── ffmpeg_renderer.py        # FFmpeg output target
│       │   └── capcut_exporter.py        # Stub (impl Sprint 3)
│       └── cli/
│           └── main.py                   # CLI entry points
├── tests/
│   ├── fixtures/
│   │   └── ch_sample/                    # Artifacts thật từ Pha 2 Spike
│   ├── test_schemas.py                   # DoD (a)
│   ├── test_reconcile.py                 # DoD (b)(c)
│   ├── test_jobs.py                      # DoD (d)
│   ├── test_tts_resync.py                # DoD (e)
│   ├── test_script_modes.py              # DoD (f)
│   └── test_render_plan.py              # DoD (g)
└── docs/
    └── dev-setup.md
```

---

## Task Breakdown

> **Ký hiệu:** `[ ]` chưa làm · `[/]` đang làm · `[x]` hoàn thành

---

### 📦 PHASE 1 — SKELETON (Ngày 1–4)

#### TASK-001 — Khởi tạo project Python
- **Agent:** `backend-specialist`
- **Skill:** `clean-code`
- **Priority:** P0 (Blocker cho mọi task còn lại)
- **Dependencies:** Không có
- **INPUT:** Thư mục rỗng, architecture.md
- **OUTPUT:** `pyproject.toml`, `.python-version`, `src/manga_pipeline/__init__.py`, `uv.lock`
- **VERIFY:** `uv run python -c "import manga_pipeline"` không lỗi
- [x] Tạo `pyproject.toml` với dependencies: `pydantic>=2.0`, `pytest`, `pytest-snapshot`, `ruff`, `mypy`
- [x] Cấu hình ruff (lint) + mypy (type check) trong `pyproject.toml`
- [x] Tạo cấu trúc thư mục `src/manga_pipeline/` + `tests/` + `docs/`

---

#### TASK-002 — Schema: 5 Artifact + project.json (Pydantic v2)
- **Agent:** `backend-specialist`
- **Skill:** `clean-code`, `api-patterns`
- **Priority:** P0 (Blocker cho TASK-003, TASK-004, và toàn bộ Pha 2)
- **Dependencies:** TASK-001
- **INPUT:** Mục 4 và 7 trong architecture.md (JSON examples chi tiết)
- **OUTPUT:** 6 file Pydantic trong `src/manga_pipeline/core/schemas/`
- **VERIFY:** `from manga_pipeline.core.schemas import LayoutArtifact, ProjectSchema` không lỗi; `LayoutArtifact.model_json_schema()` trả đúng cấu trúc
- [x] `artifact_layout.py`: `LayoutArtifact`, `Panel`, `TextRegion`, `LayoutManifest`
- [x] `artifact_ocr.py`: `OcrArtifact`, `OcrPanel`, `OcrText`, `OcrManifest`; `text_type: Literal["dialogue","sfx","narration"]`
- [x] `artifact_script.py`: `ScriptArtifact`, `ScriptUnit`, `ScriptManifest` với `mode: Literal["manual_script","translate","ai_narrate"]`
- [x] `artifact_tts.py`: `TtsArtifact`, `TtsClip`, `TtsManifest`; filename convention `audio/{ch}_{unit_id}.v{N}.wav`
- [x] `artifact_story.py`: Reserved stub — `StoryArtifact` với `stage: Literal["story"]`, `beats: list`, `character_state: dict`
- [x] `project_schema.py`: `ProjectSchema` đầy đủ; validator đảm bảo mọi ref trong `overrides/sequence/layout_overrides` là `pa_/ta_/sa_` prefix (không cho phép `p_/t_/s_` trực tiếp)

---

#### TASK-003 — Hệ ID 2 tầng: Hash ID + Persistent Anchor
- **Agent:** `backend-specialist`
- **Skill:** `clean-code`
- **Priority:** P0
- **Dependencies:** TASK-001
- **INPUT:** Mục 3 trong architecture.md (hash formula, anchor JSON schema)
- **OUTPUT:** `ids.py`, `anchors.py`
- **VERIFY:** Unit test xác nhận cùng bbox → cùng ID; khác bbox → khác ID; anchor CRUD đọc/ghi đúng vào `project.json`
- [x] `ids.py`:
  - `normalize_bbox(bbox: list[int]) -> str`: Chuẩn hóa `[x,y,w,h]` về string canonical
  - `panel_id(page_file, bbox) -> str`: `"p_" + sha1(page_file + ":" + normalized)[:12]`
  - `text_id(page_file, bbox) -> str`: `"t_" + sha1(...)`
  - `unit_id(panel_id, seq, type) -> str`: `"s_" + sha1(...)`
- [x] `anchors.py`:
  - `AnchorStore(project_path)`: Load/save anchors từ `project.json`
  - `create_anchor(kind, ai_id) -> str`: Auto-increment `pa_/ta_/sa_` + 6 digits
  - `update_current(anchor_id, new_ai_id)`: Append history, update current
  - `retire(anchor_id)`: Đánh dấu `retired: true`, không xóa
  - `find_by_ai_id(ai_id) -> str | None`: Lookup ngược AI ID → anchor

---

#### TASK-004 — Reconcile Engine + Guided Mode
- **Agent:** `backend-specialist`
- **Skill:** `clean-code`
- **Priority:** P0
- **Dependencies:** TASK-003
- **INPUT:** Mục 6 trong architecture.md (IoU ≥ 0.6, orphaned policy); Guided mode đã xác nhận
- **OUTPUT:** `reconcile.py`
- **VERIFY:** Unit test với synthetic bbox data — IoU khớp → remap; không khớp → orphaned; > 80% orphaned → `ImageSourceChangedWarning` raised
- [x] `iou(bbox_a, bbox_b) -> float`: Intersection over Union tính trên `[x,y,w,h]`
- [x] `text_similarity(a, b) -> float`: Levenshtein ratio (fallback khi IoU gần 0.6)
- [x] `reconcile(old_artifact, new_artifact, anchor_store, layout_overrides) -> ReconcileResult`
  - Match AI ID trùng → `anchor.current` giữ nguyên
  - Không trùng → IoU ≥ 0.6 + text_sim → đề xuất remap (chưa commit)
  - Không match → anchor vào `orphaned[]`
  - `locked: true` → KHÔNG bao giờ tự remap
- [x] `ReconcileResult(remapped, orphaned, new_anchors, warnings: list[str])`
- [x] **Guided Mode**: Nếu `len(orphaned) / total_anchors > 0.8` → raise `ImageSourceChangedWarning` với message mô tả rõ ràng; dừng import cho đến khi user chọn `--mode=reset` hoặc `--mode=merge`

---

#### TASK-005 — AI Engine Protocols + Job System
- **Agent:** `backend-specialist`
- **Skill:** `clean-code`
- **Priority:** P1
- **Dependencies:** TASK-002
- **INPUT:** Mục 5 và 9 trong architecture.md
- **OUTPUT:** `engines/protocols.py`, `pipeline/jobs.py`
- **VERIFY:** Protocol check bằng `isinstance`; Job crash-resume test với synthetic item list
- [x] `protocols.py`: `LayoutEngine`, `OcrEngine`, `ScriptEngine`, `TtsEngine` Protocol classes với full type annotations
- [x] `jobs.py`:
  - `JobState` dataclass: `job_id, type, chapter_id, status, engine_lock, items_total, items`
  - `JobRunner.start(job_def) -> JobState`: Tạo `.tmp` file, ghi per-item state
  - `JobRunner.resume(job_id, engine_lock) -> JobState`: Verify engine_lock khớp; nếu lệch → raise `EngineLockMismatch`
  - `JobRunner.mark_done(job_id, item_id)`: Update item status = "done"
  - `JobRunner.finalize(job_id)`: Atomic rename `.tmp` → final filename
  - `JobRunner.get_pending_items(job_state) -> list`: Return items chưa "done"

---

#### TASK-006 — Render Plan Builder (Deterministic)
- **Agent:** `backend-specialist`
- **Skill:** `clean-code`
- **Priority:** P1
- **Dependencies:** TASK-002, TASK-003
- **INPUT:** Mục 8 trong architecture.md; `project.json` schema
- **OUTPUT:** `render/plan.py`, `render/capcut_exporter.py` (stub)
- **VERIFY:** Cùng `project.json` → identical JSON bytes (deterministic); không có import FFmpeg/CapCut trong `plan.py`
- [x] `RenderPlan.from_project(project: ProjectSchema) -> RenderPlan`:
  - Resolve `pa_/ta_/sa_` anchors → current AI IDs
  - Apply overrides (text sửa, speaker_id)
  - Apply animation templates (template_ref hoặc inline; inline thắng)
  - Serialize JSON với keys sorted (determinism)
- [x] `RenderPlanClip`: panel + audio clip resolved, target-neutral vocabulary (`fade/zoom_in/zoom_out/pan/slide_*`)
- [x] `capcut_exporter.py`: Stub trả `{"status": "stub", "sprint": 3}` — impl Sprint 3 sau fixture task

---

### 🔥 PHASE 2 — SPIKE (Ngày 5–11)

> **Điều kiện bắt đầu:** Bạn cung cấp folder ảnh manga mẫu (5–20 trang, tiếng Nhật) vào `tests/fixtures/ch_sample/pages/`

---

#### TASK-007 — Layout Engine Adapter (manga-image-translator)
- **Agent:** `backend-specialist`
- **Skill:** `clean-code`
- **Priority:** P0 (Pha 2)
- **Dependencies:** TASK-005, folder ảnh mẫu
- **INPUT:** Folder `pages/*.png`, `LayoutEngine` Protocol
- **OUTPUT:** `engines/layout/manga_image_translator.py`, file `artifacts/layout.ch_sample.v1.json` thật
- **VERIFY:** File JSON validate được bằng `LayoutArtifact.model_validate_json()`; panel_id giống nhau khi chạy lại cùng ảnh
- [ ] Cài `manga-image-translator` (detector module only, không cần full pipeline)
- [ ] Implement `MITLayoutEngine(LayoutEngine)`:
  - Gọi detector → parse bbox output (format native → `[x,y,w,h]`)
  - Sinh `panel_id` + `text_id` bằng `ids.py`
  - Trả `LayoutResult` → serialize `LayoutArtifact` → ghi `artifacts/layout.ch_sample.v1.json`

---

#### TASK-008 — OCR Engine Adapter (manga-ocr)
- **Agent:** `backend-specialist`
- **Skill:** `clean-code`
- **Priority:** P1 (Pha 2)
- **Dependencies:** TASK-007
- **INPUT:** `layout.ch_sample.v1.json` + `layout_overrides` (rỗng lần đầu), `OcrEngine` Protocol
- **OUTPUT:** `engines/ocr/manga_ocr_engine.py`, file `artifacts/ocr.ch_sample.v1.json` thật
- **VERIFY:** File JSON validate bằng `OcrArtifact`; `confidence` field có giá trị float 0–1
- [ ] Cài `manga-ocr`
- [ ] Implement `MangaOcrEngine(OcrEngine)`:
  - Resolve layout từ artifact + overrides
  - Chạy OCR từng text region
  - Trả `OcrResult` → serialize `OcrArtifact`

---

#### TASK-009 — Manual Script Import + Script Artifact
- **Agent:** `backend-specialist`
- **Skill:** `clean-code`
- **Priority:** P1 (Pha 2)
- **Dependencies:** TASK-008
- **INPUT:** File script text có markers `## p:<reading_order>`, `ScriptEngine` Protocol
- **OUTPUT:** `engines/script/manual_import.py`, file `artifacts/script.ch_sample.v1.json`
- **VERIFY:** File JSON validate bằng `ScriptArtifact`; unit không gán panel → trong `unassigned[]`, không fail im lặng; `mode: "manual_script"` trong manifest
- [ ] Parse format: `## p:1\nDialog text\n## p:2\nNarration...`
- [ ] Map unit → `panel_id` qua `reading_order` lookup trong layout artifact
- [ ] Unit không map được → `unassigned[]`, log warning rõ ràng

---

#### TASK-010 — TTS Engine Adapter (edge-tts)
- **Agent:** `backend-specialist`
- **Skill:** `clean-code`
- **Priority:** P1 (Pha 2)
- **Dependencies:** TASK-009
- [x] **TASK-007**: Cài đặt `manga-image-translator` (detector) <!-- id: 7 -->
- [x] **TASK-008**: Cài đặt `manga-ocr` <!-- id: 8 -->
- [x] **TASK-009**: Tạo Engine adapter cho Layout (`src/manga_pipeline/engines/layout/manga_image_translator.py`) <!-- id: 9 -->
- [x] **TASK-010**: Tạo Engine adapter cho OCR (`src/manga_pipeline/engines/ocr/manga_ocr_engine.py`) <!-- id: 10 -->
- [x] **TASK-011**: Tạo Engine adapter cho Script Manual Import (`src/manga_pipeline/engines/script/manual_import.py`) <!-- id: 11 -->
- [x] **TASK-012**: Tạo Engine adapter cho TTS Edge TTS (`src/manga_pipeline/engines/tts/edge_tts_engine.py`) <!-- id: 12 -->
- [x] **TASK-013**: Tạo FFmpeg Video Renderer (`src/manga_pipeline/render/ffmpeg_renderer.py`) hỗ trợ NVENC & Concat Demuxer <!-- id: 13 -->
- [x] **TASK-014**: Tạo Typer CLI (`src/manga_pipeline/cli/main.py`) với `layout`, `ocr`, `script`, `tts`, `render`, `run-all` <!-- id: 14 -->
- [x] **TASK-015**: Chạy Spike End-to-End trên 4 trang manga mẫu thực tế (`tests/fixtures/ch_sample/pages/`) -> `renders/ch_sample.mp4` <!-- id: 15 -->

---

## 3. Phase 3 — Hardening + DoD Verification (Ngày 12–16)

- [x] **TASK-016**: Viết tài liệu setup (`docs/dev-setup.md`) <!-- id: 16 -->
- [x] **TASK-017**: Bổ sung bộ DoD Unit Tests (`tests/test_script_modes.py`, `tests/test_tts_resync.py`, `tests/test_reconcile.py`) <!-- id: 17 -->
- [x] **TASK-018**: Chạy toàn bộ 32 test cases qua `pytest` (100% Pass) <!-- id: 18 -->
- [x] **TASK-019**: Chạy Static Type Check `mypy --strict` (100% Pass trên 28 files) & `ruff check` <!-- id: 19 -->
- [x] **TASK-020**: Chạy `security_scan.py` (100% Pass, 0 findings) <!-- id: 20 -->
- [x] **TASK-021**: **Khóa Schema (Schema Locked)** — Chuẩn bị cho Sprint 1 <!-- id: 21 -->

---

## 4. Definition of Done (DoD) Checklist

| DoD Criterion | Status | Test File / Evidence |
| :--- | :---: | :--- |
| **(a) Schema Validation** | **PASSED** | `tests/test_schemas.py` (5 Artifacts + `project.json` + real fixtures) |
| **(b) Reconcile Engine** | **PASSED** | `tests/test_reconcile.py` (IoU >= 0.6, exact AI ID, auto-remap) |
| **(c) Source Rename / Resize** | **PASSED** | `tests/test_reconcile.py` (Anchor & overrides survive) |
| **(d) Crash-Resume & EngineLock** | **PASSED** | `tests/test_jobs.py` (Atomic write, resume from checkpoint) |
| **(e) TTS Versioning & Resync** | **PASSED** | `tests/test_tts_resync.py` (Timeline snapshot isolated until Resync) |
| **(f) Script Modes Uniformity** | **PASSED** | `tests/test_script_modes.py` (3 modes output uniform `ScriptUnit`) |
| **(g) Render Plan Determinism** | **PASSED** | `tests/test_render_plan.py` (0 FFmpeg deps in core, JSON deterministic) |
| **(Spike) Real Video Output** | **PASSED** | `renders/ch_sample.mp4` (4.5 MB, NVENC/FFmpeg rendered) |

---

#### TASK-011 — FFmpeg Renderer + CLI Entry Points
- **Agent:** `backend-specialist`
- **Skill:** `clean-code`
- **Priority:** P1 (Pha 2)
- **Dependencies:** TASK-006, TASK-010
- **INPUT:** `RenderPlan` từ project + TTS artifacts
- **OUTPUT:** `render/ffmpeg_renderer.py`, `cli/main.py`, file `renders/ch_sample.mp4`
- **VERIFY:** `renders/ch_sample.mp4` tồn tại và phát được (VLC/ffprobe); NVENC log nếu Quadro T1000 detect được
- [ ] `FFmpegRenderer.render(plan: RenderPlan, output_path: Path)`: Map vocabulary → FFmpeg filter graph
  - `fade` → `fade` filter
  - `zoom_in/zoom_out` → `zoompan` filter
  - `pan` → `crop` + movement
- [ ] Hardware detect: `ffmpeg -encoders | grep nvenc` → dùng `h264_nvenc` nếu có, fallback `libx264`
- [ ] CLI commands qua `typer` hoặc `argparse`:
  ```
  manga-pipeline layout ch01 --pages pages/
  manga-pipeline ocr ch01
  manga-pipeline import-script ch01 --file script.txt
  manga-pipeline tts ch01
  manga-pipeline render ch01 --output renders/
  manga-pipeline import-artifact ch01 layout [--mode=guided|reset|merge]
  ```

---

### 🔒 PHASE 3 — HARDENING + DOD (Ngày 12–16)

#### TASK-012 — Test Fixtures từ Pha 2 + DoD (a): Schema Tests
- **Agent:** `backend-specialist`
- **Skill:** `clean-code`, `tdd-workflow`
- **Priority:** P0 (Pha 3)
- **Dependencies:** TASK-007 đến TASK-011 hoàn thành
- **INPUT:** Artifacts thật từ Pha 2 Spike
- **OUTPUT:** `tests/fixtures/ch_sample/` (copy artifacts thật), `tests/test_schemas.py`
- **VERIFY:** `pytest tests/test_schemas.py -v` → 100% PASS
- [ ] Copy artifacts thật vào `tests/fixtures/ch_sample/`
- [ ] `test_layout_schema_valid()`: Parse fixture → validate
- [ ] `test_ocr_schema_valid()`
- [ ] `test_script_schema_valid()` — cả 3 mode manifest
- [ ] `test_tts_schema_valid()`
- [ ] `test_story_schema_reserved()`: chỉ cần `stage="story"` + placeholder fields
- [ ] `test_project_schema_valid()`
- [ ] `test_overrides_reject_ai_ids()`: Validator từ chối `p_/t_/s_` prefix trong override refs

---

#### TASK-013 — DoD (b)(c): Reconcile Tests với Real Data
- **Agent:** `backend-specialist`
- **Skill:** `clean-code`, `tdd-workflow`
- **Priority:** P0 (Pha 3)
- **Dependencies:** TASK-004, TASK-012
- **INPUT:** Layout fixtures thật; synthetic "re-run with different segmentation" variants
- **OUTPUT:** `tests/test_reconcile.py`
- **VERIFY:** `pytest tests/test_reconcile.py -v` → 100% PASS
- [ ] `test_rerun_same_id_anchor_stable()`: Cùng AI ID → anchor.current không đổi
- [ ] `test_different_segmentation_anchor_remap()`: IoU ≥ 0.6 → đề xuất remap đúng
- [ ] `test_below_iou_threshold_goes_orphaned()`: IoU < 0.6 → orphaned, không tự remap
- [ ] `test_rename_source_image_anchor_survives()`: DoD (c) — đổi tên file → AI ID thay đổi nhưng anchor + override sống sót
- [ ] `test_resize_source_image_anchor_survives()`: DoD (c) — resize → scale_factor adjust → reconcile thành công
- [ ] `test_locked_anchor_never_remapped()`: `locked: true` → reconcile bỏ qua
- [ ] `test_orphaned_override_not_silently_lost()`: Override gắn orphaned anchor → vẫn trong `overrides`, không bị xóa
- [ ] `test_guided_mode_blocks_on_full_source_change()`: > 80% orphaned → `ImageSourceChangedWarning`, import dừng

---

#### TASK-014 — DoD (d)(e): Job System + TTS Resync Tests
- **Agent:** `backend-specialist`
- **Skill:** `clean-code`, `tdd-workflow`
- **Priority:** P0 (Pha 3)
- **Dependencies:** TASK-005, TASK-010
- **OUTPUT:** `tests/test_jobs.py`, `tests/test_tts_resync.py`
- **VERIFY:** `pytest tests/test_jobs.py tests/test_tts_resync.py -v` → 100% PASS
- [ ] `test_job_crash_resume()`: Simulate crash sau item 3/10 → resume bắt đầu từ item 4
- [ ] `test_engine_lock_mismatch_fails_clearly()`: Resume với engine khác → `EngineLockMismatch`, không có artifact "nửa vời"
- [ ] `test_atomic_write_no_partial_artifact()`: Interrupt trong khi ghi → không có file `.json` hỏng (chỉ `.tmp`)
- [ ] `test_rerun_tts_new_version_not_overwrite()`: Re-run TTS → version mới, file cũ vẫn còn
- [ ] `test_timeline_snapshot_unchanged_before_resync()`: `clip.duration_ms` trong timeline không tự đổi khi TTS re-run
- [ ] `test_resync_updates_snapshot_correctly()`: User bấm Resync → `synced_duration_ms` update đúng

---

#### TASK-015 — DoD (f)(g): Script Mode Tests + Render Plan Golden Tests
- **Agent:** `backend-specialist`
- **Skill:** `clean-code`, `tdd-workflow`
- **Priority:** P0 (Pha 3)
- **Dependencies:** TASK-006, TASK-009
- **OUTPUT:** `tests/test_script_modes.py`, `tests/test_render_plan.py`
- **VERIFY:** `pytest tests/test_script_modes.py tests/test_render_plan.py -v` → 100% PASS
- [ ] `test_manual_script_unit_schema()`: mode=manual_script → ScriptUnit validate đúng
- [ ] `test_translate_mode_unit_schema()`: mode=translate (stub mock) → cùng ScriptUnit schema
- [ ] `test_ai_narrate_mode_unit_schema()`: mode=ai_narrate (stub mock) → cùng ScriptUnit schema
- [ ] `test_unit_anchor_stable_on_rerun()`: Cùng input → cùng `s_` hash ID
- [ ] `test_render_plan_deterministic()`: Cùng project.json → identical JSON bytes (sorted keys)
- [ ] `test_render_plan_no_ffmpeg_import()`: `import manga_pipeline.render.plan` → không trigger import ffmpeg hoặc capcut
- [ ] `test_ffmpeg_args_from_render_plan()`: Render Plan với `zoom_in` → FFmpeg args chứa `zoompan`
- [ ] `test_capcut_exporter_stub()`: Stub trả dict với `status: "stub"`, không raise

---

#### TASK-016 — Dev Setup Documentation
- **Agent:** `backend-specialist`
- **Skill:** `clean-code`
- **Priority:** P2 (Non-blocker)
- **Dependencies:** TASK-011
- **OUTPUT:** `docs/dev-setup.md`
- **VERIFY:** Theo hướng dẫn từ máy mới → pipeline chạy được end-to-end
- [ ] Hướng dẫn cài uv, Python 3.10+
- [ ] Hardware requirements: Quadro T1000 4GB VRAM; RAM 32GB; NVENC detect
- [ ] Lệnh chạy pipeline: layout → ocr → script → tts → render
- [ ] Cách cung cấp chapter mẫu (folder ảnh format)
- [ ] Giải thích Guided Mode reconcile warning

---

## Phase X — Verification Checklist

> 🔴 Schema chỉ được "LOCKED" khi TẤT CẢ checks dưới đây PASS.

```bash
# Toàn bộ DoD test suite
pytest tests/ -v --tb=short

# Breakdown từng DoD
pytest tests/test_schemas.py -v          # DoD (a) — Schema validation
pytest tests/test_reconcile.py -v        # DoD (b)(c) — Anchor remap
pytest tests/test_jobs.py -v             # DoD (d) — Job crash-resume
pytest tests/test_tts_resync.py -v       # DoD (e) — TTS Resync
pytest tests/test_script_modes.py -v    # DoD (f) — 3 mode cùng schema
pytest tests/test_render_plan.py -v     # DoD (g) — Render Plan golden test

# Lint + type check
uv run ruff check src/ tests/
uv run mypy src/

# Security scan
python .agents/skills/vulnerability-scanner/scripts/security_scan.py .

# Manual: Kiểm tra MP4 output
ffprobe renders/ch_sample.mp4
```

**Rule Compliance:**
- [ ] Không có code path nào ghi vào `artifacts/` từ app (chỉ batch pipeline)
- [ ] Mọi ref trong project.json là anchor (`pa_/ta_/sa_`), không phải AI ID trực tiếp
- [ ] Artifact ghi atomic (`.tmp` → rename), không có partial file
- [ ] Guided mode log warning rõ ràng — không có nhánh im lặng

---

## Risks & Mitigations

| # | Rủi ro | Xác suất | Mitigation |
|---|--------|----------|------------|
| 1 | `manga-image-translator` detector API thay đổi | Thấp | Pin version trong pyproject.toml; adapter tách biệt |
| 2 | OCR bbox không khớp để test IoU (synthetic data không đủ thực tế) | Trung bình | Dùng fixtures thật từ Pha 2 cho Pha 3 tests |
| 3 | VRAM 4GB không chạy được manga-image-translator | Trung bình | Thử CPU mode; detector thường nhẹ hơn full pipeline |
| 4 | edge-tts thay đổi API / bị rate limit | Thấp | Cài `edge-tts` offline cache; fallback ghi duration_ms = 0 trong test |
| 5 | Schema phải sửa sau Pha 2 (thực tế không khớp spec) | Trung bình | Expected! Đây là mục đích của Hybrid — sửa trước khi lock |
| 6 | Electron vs Tauri chưa chốt | Thấp (Sprint 0) | Non-blocker; quyết định Sprint 1 dựa trên IPC pattern |

---

## Milestones

| Milestone | Ngày | Deliverable |
|-----------|------|-------------|
| M1 — Skeleton Done | Ngày 4 | 6 Pydantic schemas + ID/Anchor/Reconcile + Job System + Render Plan |
| M2 — Spike Done | Ngày 11 | MP4 output từ chapter mẫu; artifacts thật trong fixtures/ |
| M3 — Schema Locked | Ngày 16 | `pytest tests/ -v` → 100% PASS trên 7 DoD groups |

---

*Sau khi M3 đạt được, Sprint 1 bắt đầu: Local Folder import connector, Panel model, Timeline model, FFmpeg renderer hoàn chỉnh.*
