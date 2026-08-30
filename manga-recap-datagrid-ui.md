# Kế Hoạch Xây Dựng Giao Diện Data-Grid Centric Desktop App (Theo DESIGN.md)

> **Mục tiêu**: Chuyển đổi toàn diện giao diện Web Dashboard sang mô hình **Data-Grid Centric Desktop App** theo chuẩn trải nghiệm nguyên bản MagaRecap, hỗ trợ phím tắt siêu tốc, chuyển đổi Row Mode / Cell Mode, Context Tabs và tích hợp mượt mà với lõi Backend `project.json` (Architecture v5).

---

## 🏗️ 1. Tổng Quan Kiến Trúc Giao Diện (Global Layout)

Giao diện sẽ được tổ chức thành 4 phân vùng chính theo thiết kế Desktop chuyên nghiệp:

```text
┌───────────────────────────────────────────────────────────────────────────────┐
│ 1. TOP MENU BAR: [File]  [Cài Đặt]  [Công Cụ]  [Tài Khoản / Credit]            │
├───────────────────────────────────────────────────────────────────────────────┤
│ 2. MAIN TOOLBAR:                                                              │
│    ▶ Chạy Pipeline  | 💾 Lưu (Ctrl+S) | 🔍 Tìm Kiếm (Ctrl+F)                 │
│    TOGGLE MODE: [ 🔘 Chế độ Hàng (Row) | 🔲 Chế độ Ô (Cell) ] | 📦 Xuất      │
├───────────────────────────────────────────────┬───────────────────────────────┤
│ 3. DATA GRID (Bảng Dữ Liệu Trung Tâm)         │ 4. CONTEXT TABS (Tab Phụ Trợ) │
│    ┌──┬─────┬──────────┬──────────┬─────────┐ │  ┌─────────┬─────────┬──────┐  │
│    │# │ Ảnh │ Text Gốc │ Text Dịch│ Kịch Bản│ │  │Khung Cắt│Âm Thanh │Hiệu  │  │
│    ├──┼─────┼──────────┼──────────┼─────────┤ │  │Truyện   │(TTS)    │Ứng   │  │
│    │1 │[Img]│ ...      │ ...      │ ...     │ │  ├─────────┴─────────┴──────┤  │
│    │2 │[Img]│ ...      │ ...      │ ...     │ │  │ Panel Điều Khiển Chi Tiết│  │
│    │3 │[Img]│ ...      │ ...      │ ...     │ │  │ Theo Từng Chức Năng      │  │
│    └──┴─────┴──────────┴──────────┴─────────┘ │  └────────────────────────────┘  │
└───────────────────────────────────────────────┴───────────────────────────────┘
```

---

## 📋 2. Chi Tiết Các Giai Đoạn Triển Khai (Phased Roadmap)

### 🔹 Giai đoạn 1: Bố Cục Nền Tảng & Component Data Grid (Layout & Grid Foundation)
- **1.1. Khung Bố Cục Desktop**:
  - Xây dựng **Top Menu Bar** (File, Cài đặt, Công cụ, Help) với dropdown menu chuẩn Desktop.
  - Xây dựng **Main Toolbar** tích hợp: nút Chạy nhanh, nút Lưu (`Ctrl+S`), nút Tìm kiếm (`Ctrl+F`), công tắc chuyển đổi **Row Mode / Cell Mode**, và nút **Xuất CapCut**.
- **1.2. Bảng Dữ Liệu Trung Tâm (Data Grid)**:
  - Hiển thị danh sách các Panel theo hàng (mỗi hàng = 1 Panel / Bbox).
  - Các cột dữ liệu động:
    - `Checkbox`: Chọn hàng / Chọn nhiều hàng (Shift + Click, Ctrl + Click).
    - `STT / Reading Order`: Thứ tự đọc khung tranh.
    - `Thumbnail Ảnh`: Preview ảnh panel đã crop (click đúp để phóng to).
    - `Text Gốc (OCR)`: Văn bản trích xuất từ bubble.
    - `Text Dịch / Kịch Bản`: Câu thoại đã dịch hoặc kịch bản chỉnh sửa.
    - `Audio Clip`: Player mini nghe thử giọng đọc của dòng đó.
    - `In/Out Template`: Nhãn hiệu ứng chuyển cảnh.
    - `Keyframe Template`: Nhãn hiệu ứng Zoom / Pan.
- **1.3. Hệ Thống Dual Mode (Row Mode vs Cell Mode)**:
  - **Row Mode**: Bấm chọn cả hàng → áp dụng thao tác cho hình ảnh, TTS, hiệu ứng.
  - **Cell Mode**: Bấm chọn từng ô text → chỉnh sửa nội dung văn bản trực tiếp.

---

### 🔹 Giai đoạn 2: Trình Chỉnh Sửa Khung Tranh (Layout Editor) & Phím Tắt Hotkeys
- **2.1. Canvas Layout Preview & Vẽ Khung**:
  - Tích hợp cửa sổ / popup preview ảnh trang manga gốc.
  - Hỗ trợ **Right-Click + Drag** trực tiếp trên canvas để vẽ khung cắt mới (tự động tính Bbox).
  - Tự động sinh persistent anchor `locked: true` ghi vào `layout_overrides` trong `project.json`.
- **2.2. Hệ Thống Phím Tắt (Hotkeys Engine)**:
  - `Alt + 1`: Di chuyển panel / hàng đang chọn lên trên.
  - `Alt + 2`: Di chuyển panel / hàng đang chọn xuống dưới.
  - `Alt + 3`: Gộp các panel đang chọn thành 1 (Merge).
  - `Alt + D` hoặc `Delete`: Xóa panel / hàng đang chọn.
  - `Ctrl + S`: Lưu toàn bộ overrides & project.
  - `Ctrl + F`: Mở thanh tìm kiếm & lọc nhanh.
  - `Ctrl + Z` / `Ctrl + Shift + Z`: Undo / Redo.

---

### 🔹 Giai đoạn 3: Hệ Thống Context Tabs (Các Tab Chức Năng Phụ Trợ)
- **3.1. Tab 1 — Thao Tác Khung Truyện (Smart Cropping)**:
  - Tự động phát hiện khung tranh (Auto Layout).
  - Tùy chỉnh Margin width/height (`-15px` lọc viền).
  - Tùy chọn `Tự động full chiều rộng khi vẽ`.
  - Nút `Cắt ảnh` & `Xóa các khung cắt thừa`.
- **3.2. Tab 2 — AI Vision & OCR Operations**:
  - Chọn hàng loạt panel → Chạy OCR trích xuất chữ.
  - Lọc văn bản: Nút `Không có văn bản` để tự động chọn các hàng không có chữ (ảnh phong cảnh) và xóa nhanh.
  - Thao tác văn bản nhanh: Viết hoa đầu câu, Viết thường toàn bộ, Xóa dòng trống.
- **3.3. Tab 3 — Dịch Thuật & Kịch Bản (Translation & Script)**:
  - Popup `Dịch và viết lại`: Chọn ngôn ngữ nguồn / đích, nhập style prompt (hài hước, súc tích).
  - Tạo kịch bản tự động theo chapter.
- **3.4. Tab 4 — Tạo Âm Thanh (TTS & Audio Sync)**:
  - Dropdown chọn Voice (`vi-VN-HoaiMyNeural`, `vi-VN-NamMinhNeural`, v.v.), tốc độ đọc, khoảng lặng đầu/cuối.
  - Nút `Tạo âm thanh` cho các dòng được chọn.
  - Tính năng `Sắp xếp tự động` (Audio Sync): Tự động co giãn thời lượng timeline theo audio duration.
- **3.5. Tab 5 — Hiệu Ứng In/Out & Keyframe**:
  - 4 nút áp dụng hàng loạt: (1) Dòng chọn, (2) Tất cả dòng, (3) Ngẫu nhiên dòng chọn, (4) Ngẫu nhiên toàn bộ bảng.
  - Import Keyframe Template từ CapCut.
- **3.6. Tab 6 — Tìm Kiếm Nhanh (Quick Search)**:
  - Tìm kiếm & Thay thế (Search & Replace regex).

---

### 🔹 Giai đoạn 4: Menu Chuột Phải (Context Menu System) & Modal Cài Đặt (Settings)
- **4.1. Context Menu Phân Biệt Theo Chế Độ**:
  - Menu Chuột phải khi ở **Row Mode**: Di chuyển, Xóa, Gộp ảnh, AI Vision, Dịch kịch bản, Gán hiệu ứng.
  - Menu Chuột phải khi ở **Cell Mode**: Thao tác text, Copy, Paste, Format text.
- **4.2. Modal Cài Đặt Hệ Thống (Settings Dialog)**:
  - Tab General: Đường dẫn CapCut `.exe`, Thư mục CapCut Projects.
  - Tab Smart Cropping: Cài đặt Margin mặc định.
  - Tab Phím Tắt: Bảng ánh xạ hotkeys có thể cấu hình.

---

### 🔹 Giai đoạn 5: Kết Nối Backend Web API & Xuất Bundle CapCut
- **5.1. Bổ Sung Các API Endpoints Phục Vụ Data-Grid**:
  - `GET /api/grid-data/{chapter_id}`: Lấy dữ liệu tổng hợp dạng bảng (Panels, Texts, Audio, Effects).
  - `POST /api/panels/reorder`: Đổi thứ tự panels (`Alt+1`, `Alt+2`).
  - `POST /api/panels/merge`: Gộp nhiều panels thành 1 (`Alt+3`).
  - `POST /api/panels/delete`: Xóa panel (`Delete`).
  - `POST /api/effects/bulk-apply`: Gán template hiệu ứng hàng loạt.
- **5.2. Đồng Bộ Hóa Hoàn Toàn Với Core `project.json`**:
  - Đảm bảo mọi thao tác trên Data Grid tương thích 100% với hệ thống persistent anchors (`pa_`, `ta_`, `sa_`).
  - Nút `Xuất` kích hoạt `CapCutProjectExporter` và `SRTExporter` xuất đầy đủ bundle.

---

## 🧪 3. Kế Hoạch Kiểm Thử & Nghiệm Thu (Verification Plan)

### Automated Tests (Pytest & Playwright MCP)
1. **API Unit & Integration Tests**:
   - `test_grid_data_api()`: Kiểm tra API tổng hợp bảng dữ liệu trả về đủ các trường.
   - `test_panel_reorder_and_merge()`: Kiểm tra API hoán đổi và gộp panel cập nhật đúng `project.json`.
   - `test_bulk_effect_apply()`: Kiểm tra gán template hiệu ứng hàng loạt.
2. **Playwright E2E UI Testing**:
   - Kiểm tra chuyển đổi giữa **Row Mode** và **Cell Mode**.
   - Kiểm tra bấm phím tắt `Alt+1`, `Alt+2`, `Alt+3`, `Delete` trên Data Grid.
   - Kiểm tra chuột phải mở Context Menu và thực hiện thao tác.
   - Kiểm tra chỉnh sửa text trực tiếp trên cell và bấm `Ctrl+S` để lưu.
   - Kiểm tra Tab TTS sinh âm thanh có tiếng thật và nghe trực tiếp trên hàng.
   - Kiểm tra nút Xuất CapCut sinh đầy đủ file vào `exports/`.

---

## 🚀 Các Bước Tiếp Theo
- Người dùng xem xét và phê duyệt kế hoạch.
- Sau khi duyệt, bắt đầu tiến hành triển khai giao diện theo từng giai đoạn.
