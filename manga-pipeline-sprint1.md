# Sprint 1 Plan: Batch Pipeline UI & Enhanced Engines

> **Mục tiêu**: Xây dựng UI điều khiển trực quan (Web-based Local Dashboard), hoàn thiện các Import Connectors (Local Folder + HakuNeko stub), nâng cấp các AI Engine adapters (Layout, Manga-OCR, Script, TTS Multi-provider) và nâng cấp Render Plan hỗ trợ Animation Templates (`zoom`, `pan`, `fade`).

---

## 1. Phân tích tác vụ & Phân công Agent (Multi-Agent Orchestration)

| Agent | Lĩnh vực phụ trách | Trách nhiệm chính trong Sprint 1 |
| :--- | :--- | :--- |
| `project-planner` | Kế hoạch & Kiến trúc | Xây dựng task breakdown, quản lý tiến độ và kiểm soát tiêu chí DoD Sprint 1 |
| `backend-specialist` | Pipeline Core & Server API | Xây dựng Import Connectors, FastAPI server / WebSocket cho batch runner, và Timeline model |
| `frontend-specialist` | UI/UX Dashboard | Xây dựng giao diện Local Dashboard hiện đại (Dark theme, hiển thị tiến độ Job, Canvas xem khung tranh, Script Editor) |
| `test-engineer` | Kiểm thử & Đảm bảo chất lượng | Viết bộ Unit & E2E tests, Golden tests cho Render Plan và chạy security scan |

---

## 2. Danh sách Task Sprint 1 Chi tiết

### Nhóm 1: Import Connectors & Quản lý Thư mục Nguồn (Backend)
- [x] **TASK-101**: Tạo Connector Protocol (`src/manga_pipeline/connectors/base.py`) chuẩn hóa interface cho mọi nguồn truyện <!-- id: 101 -->
- [x] **TASK-102**: Xây dựng `LocalFolderConnector` (`src/manga_pipeline/connectors/local_folder.py`) hỗ trợ quét ảnh (PNG/JPG/WEBP), tính SHA256 và khởi tạo chapter trong `project.json` <!-- id: 102 -->
- [x] **TASK-103**: Tạo `HakuNekoConnectorStub` (`src/manga_pipeline/connectors/hakuneko.py`) cho tích hợp sau <!-- id: 103 -->

### Nhóm 2: Timeline Model & Animation Templates (Core & Render)
- [x] **TASK-104**: Mở rộng `RenderPlan` hỗ trợ Visual Effects & Animation Templates (`tpl_slow_zoom`, `fade_in`, `pan_horizontal`) <!-- id: 104 -->
- [x] **TASK-105**: Cập nhật `FFmpegRenderer` sinh filtergraph động (`zoompan`, `fade`, `overlay`) theo Render Plan <!-- id: 105 -->
- [x] **TASK-106**: Viết Golden Tests cho Render Plan đa hiệu ứng (`tests/test_animation_render_plan.py`) <!-- id: 106 -->

### Nhóm 3: Enhanced AI Engines & Batch Job Manager (Engines)
- [x] **TASK-107**: Nâng cấp `LayoutEngine` và `MangaOcrEngine` hỗ trợ chế độ Mock/Real model switch linh hoạt <!-- id: 107 -->
- [x] **TASK-108**: Cập nhật Job Manager với SSE/WebSocket broadcast cho trạng thái tiến độ từng item (`jobs/*.json`) <!-- id: 108 -->

### Nhóm 4: Local Web UI Dashboard (Frontend & Web App)
- [x] **TASK-109**: Xây dựng FastAPI Web Service (`src/manga_pipeline/web/app.py`) cung cấp REST API + Static Server cho UI <!-- id: 109 -->
- [x] **TASK-110**: Xây dựng giao diện Dashboard Single Page (`src/manga_pipeline/web/static/`): <!-- id: 110 -->
  - **Màn hình 1: Chapter & Page Manager**: Quét thư mục ảnh, hiển thị danh sách trang.
  - **Màn hình 2: Pipeline Controller**: Nút bấm chạy từng stage (Layout -> OCR -> Script -> TTS -> Render) hoặc Run All, thanh tiến độ thời gian thực.
  - **Màn hình 3: Review & Override**: Xem trước khung tranh phát hiện được trên canvas, chỉnh sửa kịch bản / lời thoại.
  - **Màn hình 4: Media Preview & Video Player**: Nghe thử file audio TTS và phát video MP4 kết quả.
- [x] **TASK-111**: Thêm lệnh CLI `manga-pipeline ui` để khởi chạy server giao diện ngay trên localhost:8000 <!-- id: 111 -->

### Nhóm 5: Hardening, Testing & DoD Verification
- [x] **TASK-112**: Viết Unit Tests cho Connectors & Web API (`tests/test_connectors.py`, `tests/test_web_api.py`) <!-- id: 112 -->
- [x] **TASK-113**: Chạy kiểm tra toàn diện `pytest` (100% Pass) <!-- id: 113 -->
- [x] **TASK-114**: Chạy Static Type Check `mypy --strict` & `ruff check` <!-- id: 114 -->
- [x] **TASK-115**: Chạy `security_scan.py` (0 findings) <!-- id: 115 -->

---

## 3. Tiêu chí Hoàn thành Sprint 1 (Definition of Done - DoD)

| Tiêu chí | Trạng thái | Minh chứng kiểm thử |
| :--- | :---: | :--- |
| **1. Connectors** | **PASSED** | `test_connectors.py`: `LocalFolderConnector` quét ảnh PNG/JPG, tính SHA256, nạp vào `project.json`. `HakuNekoConnectorStub` sẵn sàng. |
| **2. Animation Engine** | **PASSED** | `test_animation_render_plan.py`: `RenderPlan` resolve template `zoom_in`/`fade`/`pan` thành `ResolvedTransform` xác thực và sinh video qua FFmpeg. |
| **3. Web Dashboard** | **PASSED** | `test_web_api.py` + `manga-pipeline ui`: FastAPI server phục vụ REST API + Dark Mode Web UI đầy đủ 4 màn hình. |
| **4. Code Quality & Security** | **PASSED** | 36/36 unit tests pass, `mypy --strict` pass 37 files, `ruff check` clean, `security_scan.py` đạt `[OK] SECURE`. |
