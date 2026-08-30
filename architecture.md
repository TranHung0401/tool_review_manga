# ARCHITECTURE.md — Comic/Manga to Video Tool (v5, FINAL)

> Cập nhật: 2026-08-30 — bản chốt sau 2 vòng product review (đối chiếu MagaRecap).
> **Định vị sản phẩm: (a) PARITY TOOL** — bám workflow MagaRecap hiện tại. AI narration là extension tùy chọn, không phải trục bắt buộc.
> Thay đổi trục so với v4: persistent anchors tách khỏi AI ID, script 3 mode (manual/translate/ai_narrate), story.* reserved cho extension.
> Máy dev tham chiếu: 32 GB RAM + 4 GB VRAM (Quadro T1000, có NVENC)

---

## 0. Nguyên tắc cốt lõi (không đổi sau này)

> **AI output là artifact bất biến (immutable). Editor không bao giờ ghi đè lên artifact. Mọi chỉnh sửa của user là override trong `project.json`, tham chiếu tới PERSISTENT ANCHOR (project sở hữu) — không bao giờ tham chiếu trực tiếp AI-generated ID.**

Hệ quả bắt buộc (kiểm chứng được, không chỉ tuyên bố):
- Chạy lại bất kỳ AI stage nào → tạo **artifact version mới**, không sửa file cũ.
- Re-run AI chỉ được phép **cập nhật mapping anchor → ID mới** (qua reconcile); overrides và timeline không phải sửa vì chúng chỉ biết anchor.
- Artifact tách theo **stage lifecycle** (Layout ≠ OCR ≠ Script ≠ TTS).
- Override của user là **input hợp lệ** cho stage phía sau; artifact vẫn immutable.

Các nguyên tắc khác:
1. **Local-first cho OCR / TTS / render** — cloud chỉ là fallback/option. *Khác MagaRecap (cloud + credit) một cách CÓ CHỦ ĐÍCH: tool cá nhân, không quota, không phí.* Riêng mode `ai_narrate` (extension): chấp nhận cloud-first, có provenance + cost estimate, và không bao giờ là điều kiện để pipeline chạy.
2. Không ép mọi thứ chạy GPU 4GB — cho phép offload RAM, chấp nhận chậm.
3. Tách AI preprocessing (batch, ngoài app) khỏi app runtime (lắp ráp, nhẹ).
4. Dùng lại repo mã nguồn mở, không tự viết lại pipeline.
5. AI engine implement interface theo **capability**, không theo model. Mọi model/provider nêu trong doc này là **đề xuất cho tool này — KHÔNG phải công nghệ đã xác nhận của MagaRecap**.
6. **Render Plan trung lập với output target**: vocabulary hiệu ứng không lệ thuộc FFmpeg hay CapCut; renderer/exporter tự map.

---

## 1. Kiến trúc tổng thể

```text
   Import Connectors
   ├── Local Folder (BẮT BUỘC)
   ├── HakuNeko Connector (optional)
   └── URL Import (sau)
            │
            ▼
┌──────────────────────────────────────────────┐
│              AI Batch Pipeline                 │
│  Layout → OCR → Script(3 mode) → TTS           │
│  (jobs/ resumable, atomic tmp+rename)           │
└───────────────────┬──────────────────────────┘
                    │
    Staged Artifacts (immutable, versioned)
    layout.* / ocr.* / script.* / tts.*  (+ story.* reserved)
                    │
                    ▼
┌──────────────────────────────────────────────┐
│                Import Layer                    │ ← ranh giới duy nhất app đọc artifact
│  (materialize + reconcile → anchor remap       │
│   + sync policy)                               │
└───────────────────┬──────────────────────────┘
                    ▼
┌──────────────────────────────────────────────────────────┐
│                    APPLICATION CORE                         │
│                                                             │
│  project.json (state):                                      │
│   - ANCHORS (persistent, indirection layer)                 │
│   - layout overrides (sửa khung TRƯỚC OCR)                  │
│   - text/script overrides, review status                    │
│   - character/voice registry (user-owned fields only)       │
│   - timeline (duration SNAPSHOT) + animation templates      │
│                             │                               │
│                             ▼                               │
│        Render Plan (JSON, deterministic, target-neutral)    │
└──────────────┬──────────────────────────────┬──────────────┘
               ▼        OUTPUT TARGETS         ▼
      ┌────────────────┐            ┌─────────────────────────┐
      │ FFmpeg RENDERER │            │ CapCut Project EXPORTER  │
      │ (render MP4,    │            │ (serialize bundle cho    │
      │  NVENC nếu có)  │            │  CapCut PC render)       │
      └───────┬────────┘            └──────────┬──────────────┘
              ▼                                ▼
             MP4                    CapCut project bundle
                                    (version-specific, fixture-based)
```

**Quy tắc đọc/ghi (bắt buộc):**
- Batch pipeline chỉ ghi vào `artifacts/` và `jobs/`, luôn ghi **atomic** (`*.tmp` → rename).
- App **không live-read** artifact — chỉ thấy artifact mới qua bước **Import tường minh** (kèm reconcile — mục 6).
- App chỉ ghi `project.json`. Không tồn tại code path nào ghi vào `artifacts/`.

---

## 2. Cấu trúc project trên đĩa

```text
project/
├── project.json                  # state: anchors, overrides, registry, timeline
├── artifacts/
│   ├── layout.ch01.v1.json
│   ├── ocr.ch01.v2.json
│   ├── script.ch01.v4.json       # mode: manual_script | translate | ai_narrate
│   ├── tts.ch01.v7.json
│   └── story.ch01.v1.json        # (reserved — extension, Sprint 5)
├── jobs/                         # per-item checkpoint, resumable
├── pages/                        # ảnh gốc (immutable)
├── cleaned/                      # ảnh inpaint (artifact của OCR stage)
├── audio/                        # WAV, tên file chứa artifact version
├── exports/                      # CapCut project bundle + export report
├── cache/
└── renders/
```

- File audio versioned: `audio/ch01_s_ab12cd34ef56.v7.wav` → re-run TTS không ghi đè (idempotent, timeline cũ vẫn render được).
- Format interchange một-file (nếu cần) là **materialized view** — generate được, không edit được.

---

## 3. Hệ thống ID hai tầng (khóa tại Sprint 0)

### 3.1 BBox — một format duy nhất

```text
bbox = [x, y, w, h]         # pixel, integer
Hệ tọa độ: ảnh GỐC trong pages/. Origin: góc trên-trái.
Nếu cleaned bị resize: lưu scale_factor trong artifact OCR.
```

### 3.2 Tầng 1 — AI artifact ID (anchor-based hash, sống theo đời artifact)

```text
panel_id = "p_" + sha1(page_file + ":" + bbox_normalized)[:12]
text_id  = "t_" + sha1(page_file + ":" + bbox_normalized)[:12]
unit_id  = "s_" + sha1(panel_id + ":" + seq + ":" + type)[:12]
```

Hash giúp cùng-segmentation → cùng ID (reconcile tự khớp), nhưng **KHÔNG tuyệt đối**: resize/re-export ảnh nguồn, đổi tên file, detector lệch bbox → hash đổi. Vì vậy có tầng 2.

### 3.3 Tầng 2 — Persistent Anchor (project sở hữu, bất tử)

```text
overrides / timeline ──► anchor ──► AI artifact ID hiện hành
```

```json
"anchors": {
  "pa_000123": { "kind": "panel", "current": "p_3fa8c1d02b9e",
                 "history": ["p_old1111aaaa", "p_3fa8c1d02b9e"], "locked": true },
  "ta_000124": { "kind": "text",  "current": "t_9b2e44f01a7c", "history": ["t_9b2e44f01a7c"] },
  "sa_000125": { "kind": "unit",  "current": "s_ab12cd34ef56", "history": ["s_ab12cd34ef56"] }
}
```

**Luật cứng:**
- Anchor sinh **một lần khi import lần đầu** (hoặc khi user vẽ khung), không bao giờ xóa — chỉ đánh dấu `retired`.
- `overrides`, `timeline clips`, `characters` gán thoại... **chỉ được tham chiếu anchor** (`pa_/ta_/sa_`), cấm tham chiếu `p_/t_/s_` trực tiếp.
- Re-run AI → reconcile cập nhật `current` + append `history`. Không match được → anchor vào **orphaned list**, mọi override/clip gắn nó vẫn nguyên vẹn chờ user quyết.
- Khung user vẽ tay có `locked: true` — reconcile không bao giờ tự remap.

---

## 4. Staged Artifacts — 4 stage (+1 reserved)

| Artifact | Nội dung | Tần suất chạy lại | Tham chiếu |
|---|---|---|---|
| `layout.{ch}.vN.json` | panel/bubble bbox auto-detect | Hiếm | pages/ (sha256) |
| `ocr.{ch}.vN.json` | texts.original, cleaned images | Hiếm | layout + overrides resolve |
| `script.{ch}.vN.json` | script units (3 mode) | Thường | ocr (+story nếu có) |
| `tts.{ch}.vN.json` | unit_id → audio + duration_ms | Rất thường | script |
| `story.{ch}.vN.json` | beats, character state (extension) | — | Reserved, Sprint 5 |

### 4.1 `layout.ch01.v1.json`

```json
{
  "schema_version": 1, "stage": "layout", "chapter_id": "ch01", "artifact_version": 1,
  "manifest": {
    "engine": "manga-image-translator/detector", "engine_version": "...",
    "timestamp": "...", "inputs": [{ "file": "pages/001.png", "sha256": "..." }]
  },
  "panels": [
    {
      "id": "p_3fa8c1d02b9e",
      "source": { "image": "pages/001.png", "bbox": [100, 200, 700, 400] },
      "reading_order": 1,
      "text_regions": [
        { "id": "t_9b2e44f01a7c", "bbox": [120, 220, 180, 100], "region_type": "bubble" }
      ]
    }
  ]
}
```

**Workflow bắt buộc (Pre-OCR editing):** `Auto-detect → Layout Editor (xóa/gộp/vẽ/reading order, auto-width/height khi vẽ) → OCR chạy trên resolved layout`. User sửa khung = layout overrides trong `project.json`.

### 4.2 `ocr.ch01.v2.json`

```json
{
  "schema_version": 1, "stage": "ocr", "chapter_id": "ch01", "artifact_version": 2,
  "depends_on": { "stage": "layout", "artifact_version": 1, "layout_overrides_hash": "sha1..." },
  "manifest": { "engine": "manga-ocr", "model": "kha-white/manga-ocr-base",
                "engine_version": "0.1.11", "timestamp": "..." },
  "panels": [
    {
      "id": "p_3fa8c1d02b9e",
      "cleaned_image": "cleaned/001.png",
      "texts": [
        { "id": "t_9b2e44f01a7c", "original": "...", "text_type": "dialogue",
          "reading_order": 1, "speaker_id_hint": "alice", "confidence": 0.94 }
      ]
    }
  ]
}
```

- `text_type`: `dialogue | sfx | narration`. Panel tràn trang: `source.images[]` (reserved).

### 4.3 `script.ch01.v4.json` — 3 MODE (thay đổi trục của v5)

```text
manual_script   → user paste/import kịch bản có sẵn  ← MODE MẶC ĐỊNH (parity)
translate       → dịch 1-1 theo bubble, local LLM     ← parity, 100% local
ai_narrate      → phóng tác vision, cloud-first       ← EXTENSION (Sprint 5)
```

```json
{
  "schema_version": 1, "stage": "script", "chapter_id": "ch01", "artifact_version": 4,
  "depends_on": { "stage": "ocr", "artifact_version": 2 },
  "manifest": {
    "mode": "manual_script",
    "engine": "manual_import",
    "source_file": "imports/ch01_script.txt",
    "timestamp": "..."
  },
  "units": [
    { "id": "s_ab12cd34ef56", "panel_id": "p_3fa8c1d02b9e", "seq": 1,
      "type": "narration", "text": "...", "source_text_ids": [], "speaker_id_hint": null },
    { "id": "s_cd34ef567890", "panel_id": "p_3fa8c1d02b9e", "seq": 2,
      "type": "dialogue", "text": "...", "source_text_ids": ["t_9b2e44f01a7c"],
      "speaker_id_hint": "alice" }
  ]
}
```

- **Mọi mode cho ra cùng schema units** — TTS và timeline không cần biết script từ đâu ra. `manual_import` cũng là artifact immutable (re-import = version mới).
- `mode: translate` → `manifest` có engine/model/quantization như v4 (local: llama.cpp + Phi-4-mini Q4_K_M — *đề xuất, không phải của MagaRecap*).
- `mode: ai_narrate` (extension) → `manifest` thêm `vision: true`, `model_version_seen`, `cost_estimate_usd`, `style_preset`, và optional `depends_on_story`. Unit theo panel 1:N. Không bật mode này pipeline vẫn đầy đủ.
- Manual import mapping: file script đánh dấu theo panel (marker đơn giản `## p:<reading_order>`) hoặc gán qua UI; unit không gán panel → vào review UI, không fail im lặng.

### 4.4 `tts.ch01.v7.json`

```json
{
  "schema_version": 1, "stage": "tts", "chapter_id": "ch01", "artifact_version": 7,
  "depends_on": { "stage": "script", "artifact_version": 4 },
  "manifest": { "provider": "edge-tts", "voice_ref": "vi-VN-HoaiMyNeural", "timestamp": "..." },
  "clips": [
    { "unit_id": "s_ab12cd34ef56", "file": "audio/ch01_s_ab12cd34ef56.v7.wav", "duration_ms": 5100 }
  ]
}
```

**TTS là multi-provider adapter** (parity với MagaRecap dùng nhiều vendor): `edge-tts | elevenlabs | openai | vieneu-local | kokoro-local | ...` — cùng `TtsEngine` interface, local là fallback luôn hoạt động.

### 4.5 `story.ch01.v1.json` — RESERVED (extension, Sprint 5)

Schema đặt chỗ từ Sprint 0 (rẻ), chỉ dùng khi `ai_narrate`:

```json
{
  "schema_version": 1, "stage": "story", "chapter_id": "ch01", "artifact_version": 1,
  "depends_on": { "stage": "ocr", "artifact_version": 2 },
  "manifest": { "engine": "...", "timestamp": "..." },
  "beats": [{ "type": "hook|setup|conflict|climax|ending", "panel_ids": ["..."] }],
  "character_state": { "alice": { "personality": [], "relationships": {}, "current_state": "" } },
  "events": [], "open_questions": []
}
```

Lưu ý tầng: `personality/relationships/current_state` là **AI trích xuất theo chapter → thuộc artifact này**, KHÔNG thuộc character registry (registry chỉ giữ thứ user sở hữu — mục 7).

---

## 5. Job system — per-item checkpoint, idempotent

```json
{
  "job_id": "job_001", "type": "ocr", "chapter_id": "ch01", "status": "running",
  "engine_lock": { "engine": "manga-ocr", "model": "...", "engine_version": "..." },
  "output_artifact": "artifacts/ocr.ch01.v2.json.tmp",
  "items_total": 100,
  "items": {
    "p_3fa8c1d02b9e": { "status": "done" },
    "p_11d0aa83c2f4": { "status": "failed", "error": "timeout", "attempts": 2 }
  }
}
```

- **Per-item state** — crash ở item 73 → resume từ 73. Trạng thái job (`pending/running/success/failed`) expose ra UI (Job Status — backlog mục 12).
- **Idempotent**: chạy lại item cho cùng output path (tên file chứa version).
- **`engine_lock`**: resume phải đúng engine/model/version; lệch → fail rõ, user chọn. Không có artifact "nửa nọ nửa kia".
- Xong 100% → rename `.tmp` (atomic). Job cloud (nếu dùng) ghi `cost_actual_usd`.

---

## 6. Import & Reconcile (→ anchor remap)

### 6.1 Điều kiện chuỗi
Import chỉ hợp lệ khi `depends_on` khớp artifact + overrides đang active, hoặc user xác nhận chuỗi mới.

### 6.2 Reconcile
1. AI ID trùng → anchor `current` giữ nguyên.
2. Không trùng → match **IoU bbox ≥ 0.6 + text similarity** → đề xuất remap anchor → ID mới.
3. Không match → anchor vào **orphaned list** trên review UI; overrides/clips gắn anchor **không mất**, chờ user remap tay hoặc retire.
4. Anchor `locked: true` (khung user vẽ) không bao giờ tự remap.

### 6.3 Migration policy
App đọc `schema_version` hiện tại và N-1; migrator một chiều. Nâng version = migrator + golden test trước khi merge.

---

## 7. `project.json`

```json
{
  "schema_version": 1,
  "story": { "title": "...", "chapters": ["ch01", "ch02"] },
  "settings": {
    "privacy": "local_only",
    "script_mode_default": "manual_script",
    "sync_policy": { "min_duration_ms": 1500, "padding_ms": 300 },
    "directories": { "capcut_drafts": "...", "exports": "exports/" }
  },

  "active_artifacts": { "ch01": { "layout": 1, "ocr": 2, "script": 4, "tts": 7 } },

  "anchors": {
    "pa_000123": { "kind": "panel", "current": "p_3fa8c1d02b9e", "history": ["p_3fa8c1d02b9e"] },
    "ta_000124": { "kind": "text",  "current": "t_9b2e44f01a7c", "history": ["t_9b2e44f01a7c"] },
    "sa_000125": { "kind": "unit",  "current": "s_ab12cd34ef56", "history": ["s_ab12cd34ef56"] }
  },

  "layout_overrides": {
    "ch01": {
      "deleted_panels": ["pa_000200"],
      "merged": [{ "into": "pa_000123", "from": ["pa_000201"] }],
      "user_panels": [
        { "anchor": "pa_u_000300", "source": { "image": "pages/002.png", "bbox": [0, 0, 900, 1300] },
          "reading_order": 3, "locked": true }
      ],
      "reading_order_overrides": { "pa_000123": 2 }
    }
  },

  "overrides": {
    "ta_000124": { "original": "sửa OCR sai", "reviewed": true },
    "sa_000125": { "text": "bản sửa kịch bản", "speaker_id": "alice", "reviewed": true }
  },

  "characters": {
    "alice": { "display_name": "Alice", "aliases": ["Alicia"],
               "voice": "edge:vi-VN-HoaiMyNeural", "speech_style": "", "notes": "" }
  },

  "animation_templates": {
    "tpl_slow_zoom": {
      "in_animation": { "type": "fade", "duration_ms": 500 },
      "keyframe": { "type": "zoom_in", "scale_start": 1.0, "scale_end": 1.2, "anchor": "center" },
      "out_animation": null
    }
  },

  "sequence": {
    "video_tracks": [{ "clips": [
      { "panel_ref": "pa_000123", "start_ms": 0, "duration_ms": 5400, "in_point": 0,
        "transform": {}, "visual_effects": { "template_ref": "tpl_slow_zoom" } }
    ]}],
    "audio_tracks": [{ "clips": [
      { "audio_ref": "sa_000125", "start_ms": 0,
        "synced_duration_ms": 5100, "synced_artifact_version": 7 }
    ]}],
    "overlay_tracks": []
  }
}
```

Điểm chốt:
- **Mọi ref trong overrides/timeline/layout_overrides là ANCHOR** (`pa_/ta_/sa_`) — không phải AI ID.
- **Registry chỉ giữ user-owned**: name/aliases/voice/speech_style/notes. Trạng thái nhân vật do AI suy ra thuộc `story.*` artifact (extension).
- **Animation**: `template_ref` hoặc inline (inline thắng); bulk apply template = thao tác UI. Vocabulary trung lập (`fade/slide_*/zoom_*/pan`), serialize được sang cả 2 output target.
- **Sync policy** (snapshot vẫn là luật): `clip.duration_ms = max(min_duration_ms, audio.duration_ms + padding_ms)` — tính tại thời điểm sync trong Import Layer. Re-run TTS không tự đụng timeline; import TTS mới → diff → user bấm **Resync** mới cập nhật snapshot.

---

## 8. Timeline → Render Plan → Output Targets

```text
Timeline Model (project.json)
      ↓  resolve anchors → current IDs + overrides + templates
Render Plan     # JSON thuần, DETERMINISTIC, target-neutral
      ↓                              ↓
FFmpeg RENDERER              CapCut Project EXPORTER
(thực sự render MP4,         (serialize bundle để CapCut PC render;
 NVENC, preview + headless)   version-specific, fixture-based)
```

- **Renderer ≠ Exporter** (khác abstraction, gọi chung Output Targets). Render Plan là data: cùng state → byte-identical plan, có **golden tests**. Cấm mọi tham chiếu FFmpeg/CapCut trong core.
- **CapCutProjectAdapter — điều khoản rủi ro:**
  - Format nội bộ CapCut PC là **version-specific và KHÔNG tài liệu; tên file/cấu trúc chính xác CHƯA XÁC NHẬN** (không hard-code `draft.json` trong spec).
  - **Task bắt buộc trước khi code adapter (Sprint 3):** tạo project CapCut PC mẫu bằng tay → mở draft folder → viết spec từ **fixture thực tế**.
  - Pin `capcut_versions_supported`; ngoài danh sách → cảnh báo, best-effort.
  - Hiệu ứng không map được → degrade có **export report**; luôn có fallback MP4 (FFmpeg) + SRT.
  - CapCut đổi format = sửa adapter, không bao giờ sửa Render Plan/core.

---

## 9. AI Interface — theo capability

```python
class LayoutEngine(Protocol):
    def detect(self, request: LayoutRequest) -> LayoutResult: ...

class OcrEngine(Protocol):
    def extract(self, request: OcrRequest) -> OcrResult: ...

class ScriptEngine(Protocol):
    def produce(self, request: ScriptRequest) -> ScriptResult: ...
# ScriptRequest: mode (manual_script|translate|ai_narrate),
#   texts, source/target_language, glossary, style_preset,
#   panel_image (chỉ ai_narrate), story_context (chỉ ai_narrate, optional)

class TtsEngine(Protocol):
    def synthesize(self, request: TtsRequest) -> TtsResult: ...
# TtsRequest: speaker, language, text, emotion, speed, reference_voice
# Providers: edge-tts | elevenlabs | openai | vieneu-local | kokoro-local ...
```

```yaml
script:
  mode: manual_script        # manual_script | translate | ai_narrate
  translate:
    engine: llama_cpp
    model: phi-4-mini        # đề xuất — không phải của MagaRecap
    quantization: Q4_K_M
    gpu_layers: auto
  ai_narrate:                # extension — chỉ đọc khi mode=ai_narrate
    engine: cloud
    vision: true
    style_preset: youtube_recap_vi
tts:
  provider: edge-tts
  fallback_provider: vieneu-local
privacy: local_only          # local_only | cloud_allowed
```

**Model/provider đề xuất cho tool này — KHÔNG phải công nghệ công bố của MagaRecap:**

| Capability | Default (local-first) | Option |
|---|---|---|
| Layout detect | manga-image-translator detector | — |
| OCR | manga-ocr | PaddleOCR-VL-For-Manga |
| Script translate | Phi-4-mini Q4_K_M | Qwen3 4B / cloud |
| Script ai_narrate (ext.) | Cloud vision LLM | — (local vision 4GB không đủ chất lượng) |
| TTS | Edge TTS / VieNeu (VI), Kokoro (EN) | ElevenLabs, OpenAI, Chatterbox |

---

## 10. Benchmark — đo pipeline thực

```text
Layout   pages/min, precision khung
OCR      pages/min, CPU%, RAM, VRAM, accuracy
Script   (translate) tokens/sec | (ai_narrate) panels/min + USD/chapter
TTS      RTF theo provider, RAM, VRAM, quality
Render   1080p 30/60fps, CPU time, GPU(NVENC) time
Export   thời gian sinh bundle, tỉ lệ hiệu ứng map được sang CapCut
```

Chuẩn output: **1 chapter thực tế end-to-end** (mode mặc định của parity — manual/translate — phải đo được **$0 cloud cost**).

---

## 11. Roadmap

```text
Sprint 0 — KHÓA SCHEMA (DoD bên dưới)
├── 4 staged artifact schema + story.* reserved (+depends_on, manifest embedded)
├── HỆ ID 2 TẦNG: AI hash ID + persistent anchors (indirection, history, locked)
├── Quy ước bbox duy nhất
├── Reconcile policy (IoU match → anchor remap + orphaned anchors)
├── project.json schema (anchors, layout/script overrides, registry user-owned,
│   animation templates, snapshot sync + sync_policy, story metadata đa chapter)
├── Migration policy (N-1, one-way)
├── Job system: per-item + idempotency + engine_lock (+ cost field)
├── AI interfaces (Layout/Ocr/Script/Tts Protocol; Tts multi-provider)
├── Benchmark harness + gen_report.py (không block Sprint 1)
└── Hardware detection (gpu_layers auto, NVENC detect)

Sprint 1
├── Import connectors: Local Folder (HakuNeko: stub interface, làm sau)
├── Panel + Timeline model (+ animation templates)
├── Render Plan (deterministic, golden tests, target-neutral)
└── FFmpeg Renderer → MP4 (câm, chưa AI)

Sprint 2
├── Layout batch + LAYOUT EDITOR UI (xóa/gộp/vẽ, reading order, auto-w/h)
├── OCR batch trên resolved layout
├── Import + reconcile → anchor remap + orphaned UI
├── Review UI (text override)
└── SRT export

Sprint 3 — PARITY CORE
├── Script stage: MANUAL_SCRIPT import (mapping theo panel + review UI)
├── Script stage: TRANSLATE mode (local LLM, glossary, context)
├── CapCut fixture task (tạo project mẫu, dựng spec từ draft thực tế)
└── CapCut Project Exporter (pinned versions, export report, fallback MP4+SRT)

Sprint 4
├── TTS multi-provider + audio slicer
├── Timeline sync (sync_policy → snapshot) + Resync diff UI
├── Bulk apply animation template
└── First end-to-end benchmark (manual/translate mode, $0 cloud)

Sprint 5 — EXTENSION (không chặn parity)
├── ai_narrate mode (cloud vision + cost estimate + provenance)
├── story.* artifact (beats, character state) làm input cho ai_narrate
├── Voice assignment nâng cao trên registry
└── Full pipeline polish

Backlog (product features — không thuộc architecture core):
Story Manager UI, bulk chapter creation, job status/quota dashboard,
search & replace (regex), keyboard shortcut map, directory settings UI,
HakuNeko connector, URL import, import keyframe template từ CapCut.
```

**Sprint 0 Definition of Done** (pass đủ 7 bằng test thật mới khóa schema):
- (a) 5 artifact schema (kể cả story reserved) + project.json có JSON Schema validation;
- (b) test reconcile 2 lần layout/OCR khác segmentation → anchor remap đúng, override/clip không phải sửa;
- (c) test đổi tên/resize ảnh nguồn → AI ID đổi nhưng anchor + overrides sống sót qua reconcile;
- (d) test job crash-resume giữ engine_lock;
- (e) test re-run TTS không dịch chuyển timeline khi chưa Resync;
- (f) test script units: cả 3 mode cho ra cùng schema, unit anchor ổn định khi re-run;
- (g) golden test: 1 Render Plan serialize sang FFmpeg args + CapCut export stub.

---

## 12. Rủi ro kỹ thuật & cách kiến trúc trả lời

| # | Rủi ro | Trả lời trong v5 |
|---|---|---|
| 1 | OCR/Layout không 100% | Layout Editor TRƯỚC OCR + Review UI + override tách artifact |
| 2 | AI ID hash không tuyệt đối (resize/rename nguồn) | **Persistent anchors** — overrides/timeline miễn nhiễm với ID đổi |
| 3 | 4GB VRAM không chạy nổi vision LLM | ai_narrate là extension cloud-first; parity mode 100% local |
| 4 | Chi phí cloud | Chỉ tồn tại ở extension; estimate trước, actual trong job; parity = $0 |
| 5 | Đổi model phá project đã edit | Staged artifacts + anchors + reconcile + snapshot sync |
| 6 | Batch fail giữa chừng | Per-item checkpoint + idempotent + engine_lock + atomic |
| 7 | CapCut format ngoài kiểm soát, chưa xác nhận | Exporter tách core, spec từ fixture thực tế, pinned versions, report, fallback MP4+SRT |
| 8 | Bbox mơ hồ | Một quy ước `[x,y,w,h]` theo ảnh gốc |
| 9 | Override mồ côi | Orphaned anchors surface lên UI, không mất âm thầm |
| 10 | Script không tỷ lệ 1-1 với bubble | Script unit theo panel (1:N), `source_text_ids` truy vết |
| 11 | Nhầm "của MagaRecap" vs "của tool này" | Mọi model/provider đánh dấu là đề xuất; khác biệt local-first là có chủ đích |

---

**Changelog v4 → v5:**
1. 🔴 **Định vị (a) parity**: mode mặc định `manual_script`; `translate` là parity local; `ai_narrate` hạ xuống **extension Sprint 5** — pipeline đầy đủ không cần cloud.
2. 🔴 **Hệ ID 2 tầng**: persistent anchors (project-owned, history, locked) tách khỏi AI hash ID; mọi ref trong project.json đổi sang anchor; reconcile = anchor remap. Bỏ tuyên bố "anchor tuyệt đối" của v4.
3. 🟡 Thêm `manual_script` mode (engine `manual_import`, cùng schema units, immutable).
4. 🟡 `story.{ch}.vN.json` reserved (beats + character state do AI) — schema Sprint 0, impl Sprint 5; registry chỉ còn user-owned fields.
5. 🟡 CapCut: đổi thành `CapCutProjectAdapter`, bỏ khẳng định `draft.json`, thêm task fixture bắt buộc trước khi code (Sprint 3), fallback MP4+SRT.
6. 🟢 Naming: Render Plan → Output Targets = FFmpeg **Renderer** | CapCut **Exporter**.
7. 🟢 TTS multi-provider adapter (Edge TTS default); model table đánh dấu "đề xuất, không phải của MagaRecap"; HakuNeko/URL import = connector optional; Product Backlog tách riêng (Story Manager, search/replace, shortcuts...).
8. 🟢 DoD: 6 → 7 tiêu chí (thêm test anchor sống sót khi đổi tên/resize nguồn; test 3 mode cùng schema).
