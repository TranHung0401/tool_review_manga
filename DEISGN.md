# DESIGN.md — UI/UX & Interaction Design

> Phân tích và mô phỏng chính xác giao diện, luồng thao tác (workflow) và phím tắt từ nguyên bản MagaRecap.
> Giao diện là dạng **Data-Grid Centric Desktop App** (Ứng dụng Desktop lấy bảng dữ liệu làm trung tâm), tối ưu cho thao tác hàng loạt và phím tắt.

---

## 1. Bố cục tổng thể (Global Layout)

Giao diện phần mềm được chia làm 4 khu vực chính:

1. **Top Menu Bar**: Chứa các menu thả xuống cơ bản (File, Cài đặt, Công cụ, Nạp Credit/Quản lý tài khoản).
2. **Main Toolbar (Thanh công cụ chính)**: Chứa các nút thao tác nhanh (Chạy, Lưu - `Ctrl+S`, Tìm kiếm - `Ctrl+F`) và **Switch Toggle Mode** cực kỳ quan trọng:
   * **Chế độ Hàng (Row Mode)**: Chọn cả hàng để thao tác với Hình ảnh, Âm thanh, Hiệu ứng.
   * **Chế độ Ô (Cell Mode)**: Chỉ chọn ô văn bản để thao tác Edit Text.
3. **Data Grid (Bảng dữ liệu trung tâm)**: Nơi hiển thị các ảnh đã cắt. Mỗi hàng (row) tương ứng với 1 Panel. Các cột có thể ẩn/hiện tùy ý (Ví dụ: Ảnh, Text gốc, Text dịch, In/Out Template, Keyframe Template).
4. **Context Tabs (Các Tab chức năng ở cạnh/dưới)**: Các tab chuyển đổi nhanh chức năng như `Thao tác khung truyện`, `Tạo âm thanh`, `Hiệu ứng In/Out`, `Keyframe`, `Tìm kiếm nhanh`.

---

## 2. Thiết kế chi tiết các Màn hình & Quy trình thao tác

### 2.1. Màn hình Cài đặt (Settings)
Gồm các cấu hình hệ thống trước khi bắt đầu dự án:
* **Tab General**:
  * `CapCut Directory`: Đường dẫn đến file `.exe` của CapCut (có nút Kính lúp để Auto-detect hoặc mở Task Manager lấy file location).
  * `CapCut Project Directory`: Đường dẫn lưu thư mục dự án CapCut (Drafts).
* **Tab Cắt ghép thông minh (Smart Cropping)**:
  * Margin Width/Height (Mặc định: `-15` để loại bỏ phần viền thừa trắng/đen).
  * `Margin khi tự vẽ khung` (Mặc định: `10` hoặc `30` - xác định độ to/nhỏ của Bbox khi dùng chuột kéo).
  * Checkbox: `Tự động full chiều rộng khi vẽ`.
* **Tab Phím tắt (Hotkeys)**: Cho phép user re-map phím tắt mặc định.

### 2.2. Giai đoạn 1: Import & Layout (Cắt ghép ảnh)
**Flow**: User kéo thả (Drag & Drop) 1 thư mục chứa ảnh truyện dài vào màn hình chính.
* **Cắt ghép thông minh (Auto Layout)**:
  * Nhấn nút `Chạy` trên Toolbar ➔ Chọn `Phát hiện khung truyện` ➔ Nhấn `Chạy`. Tool tự chia ảnh dài thành các khung hình vuông/chữ nhật ngắn.
* **Layout Editor (Thao tác khung truyện thủ công)**:
  * Trực tiếp dùng chuột: **Right-click + Kéo (Drag)** trên màn hình preview để tự vẽ một khung cắt mới (sinh ra anchor `locked: true` trong project).
  * **Hệ thống phím tắt (Thao tác siêu tốc):**
    * `Alt + 1`: Di chuyển hàng lên.
    * `Alt + 2`: Di chuyển hàng xuống.
    * `Alt + 3`: Gộp các ảnh đang chọn thành 1 (Merge).
    * `Alt + D` / `Delete`: Xóa ảnh (Xóa hàng).
    * `Alt + Q`: Cắt ảnh thủ công.
    * `D`: Chuyển sang công cụ vẽ khung.
    * `Ctrl + Z` / `Ctrl + Shift + Z`: Hoàn tác / Làm lại.
  * *Sau khi vẽ/chỉnh sửa xong:* Bôi đen các hàng ➔ Sang tab **Thao tác khung truyện** ➔ Nhấn nút `Cắt` (hoặc nhấn chuột phải ➔ `Xóa các khung cắt thừa` cho gọn gàng).

### 2.3. Giai đoạn 2: OCR & Text Operations
* **Chạy OCR (Lấy chữ từ ảnh)**:
  * Đảm bảo đang ở **Chế độ Hàng**. Bôi đen các hàng cần lấy chữ ➔ Chuột phải ➔ Chọn `AI Vision`.
  * Popup hiện ra cho chọn dịch vụ:
    * `Slow OCR`: Tốc độ chậm, tiết kiệm credit (khoảng 20.000 ảnh/gói tháng).
    * `Fast OCR`: Tốc độ nhanh.
    * Slider: Chọn `Số luồng chạy đồng thời` (Concurrent threads).
* **Lọc và dọn rác văn bản (Quick Search)**:
  * Bấm `Ctrl + F` (hoặc icon Kính lúp) mở Tab `Tìm kiếm nhanh`.
  * Đảm bảo bật **Chế độ Hàng** ➔ Nhấn nút `Không có văn bản` ➔ Tool tự động select các hàng không chứa chữ ➔ Bấm `Delete` để xóa hàng loạt các ảnh phong cảnh (nếu muốn lược bỏ).
* **Thao tác Text (Chế độ Ô)**:
  * Chuyển sang **Chế độ Ô** ➔ Chọn các ô text (cột Text Gốc hoặc Dịch) ➔ Chuột phải ➔ `Thao tác văn bản`.
  * Các tùy chọn có sẵn: *Viết thường toàn bộ, Viết hoa đầu câu, Xóa dòng trống...*

### 2.4. Giai đoạn 3: Translation & AI Script (Viết kịch bản)
* **Dịch & Viết lại (Parity - Manual/Translate mode)**:
  * Chọn các hàng ➔ Chuột phải ➔ `Dịch và viết lại`.
  * UI Popup: Chọn Ngôn ngữ gốc, Ngôn ngữ đích. (Nếu 2 ngôn ngữ giống nhau ➔ Tool chuyển sang chế độ *Viết lại/Rephrase*).
  * Input field `Yêu cầu bổ sung`: User nhập prompt (VD: *"Dịch theo phong cách hài hước", "Viết ngắn gọn hơn"*).
* **Tạo Kịch bản AI nguyên Chapter (AI Scriptwriter - Extension)**:
  * User vào `Cài đặt` ➔ `Tạo Story` ➔ `Tạo Chapter` ➔ Upload toàn bộ ảnh gốc lên server AI (Bước này tốn 10-15 phút để phân tích bối cảnh, nhân vật).
  * Tạo `Collection` mới ➔ Chọn ngôn ngữ (Tiếng Việt) ➔ Nguồn Chapter (Ví dụ: Chapter 1).
  * Nhấn `Tạo Kịch bản` ➔ Toàn bộ Text/Dialog/Narration mới sẽ được fill vào cột kịch bản một cách nhất quán (consistent).

### 2.5. Giai đoạn 4: TTS (Tạo âm thanh) & Audio Sync
Chuyển sang Tab **Tạo âm thanh** ở phía dưới hoặc bên cạnh.
* **Cấu hình TTS**:
  * Dropdown Server: Chọn nhà cung cấp (`ElevenLabs`, `VB`, `FPT`, `Open K`, hoặc `Server Tích hợp 1/2`).
  * Dropdown Voice: Chọn giọng (Ví dụ: Brian - English, Hoài My - VN).
  * Cài đặt tốc độ đọc.
  * Checkbox bắt buộc: `Khoảng lặng đầu và cuối` (Để âm thanh liền mạch hơn khi lên video).
* **Execute**: Đảm bảo chọn đúng cột chứa văn bản (Cột Text gốc hoặc Text dịch) ➔ Nhấn `Tạo âm thanh`.
* **Đồng bộ Timeline (Audio Sync / Sắp xếp)**:
  * User kéo trực tiếp file âm thanh `.mp3` / `.wav` từ máy tính vào Data Grid.
  * Mở Tab `Công cụ` ➔ Chọn `Tính năng sắp xếp` ➔ Tool tự động tính toán thời lượng Audio để giãn/thu Bbox ảnh khớp với tiếng (`duration_ms = audio.duration_ms + padding_ms`).

### 2.6. Giai đoạn 5: Animation & Keyframe
Chuyển sang Tab **Hiệu ứng In/Out** hoặc Tab **Keyframe**. Trong Data Grid bật 2 cột tương ứng (`In/Out Template`, `Keyframe Template`).
* **4 Nút Thao tác hàng loạt (Bulk Apply Buttons)**:
  1. Áp dụng 1 hiệu ứng (đang focus) cho các dòng được select.
  2. Áp dụng 1 hiệu ứng cho TẤT CẢ các dòng.
  3. Áp dụng NGẪU NHIÊN hiệu ứng cho các dòng được select.
  4. Áp dụng NGẪU NHIÊN tất cả hiệu ứng cho toàn bộ bảng (Nhanh nhất).
* **Tạo/Import Keyframe Template từ CapCut**:
  * Chức năng cực hay: User mở CapCut PC, tạo project mới (VD: `My_Zoom`), gán keyframe (Zoom/Pan) cho 1 ảnh, lưu và tắt CapCut.
  * Trong Tool: Nhấn `Import` ➔ Chọn dự án `My_Zoom` ➔ Tên template sẽ được thêm vào hệ thống để dùng cho mọi ảnh sau này.
* **Tạo Keyframe bằng Prompt AI (Optional)**:
  * Nút `Tạo tự động` ➔ Nhập yêu cầu hiệu ứng bằng text ➔ AI tự generate ra template keyframe.

### 2.7. Giai đoạn 6: Export (Xuất sang CapCut)
* Bấm nút `Xuất` (Export) ở góc trên bên phải.
* Tên Dự án: Tool sẽ tự động điền (hoặc user tự gõ, VD: `Review_Chapter_01`).
* Checkbox: `Xuất tiêu đề` (Export Text to CapCut Text Track) - Tắt đi nếu muốn edit raw, bật lên nếu muốn sub cứng.
* Nhấn `Xuất` ➔ Hệ thống chạy `CapCut Project Exporter` sinh ra file `draft.json`.
* **End flow**: User mở ứng dụng CapCut PC ➔ Thấy ngay project `Review_Chapter_01` ➔ Mở ra chèn thêm background (làm mờ), nhạc nền (BGM) và bấm Render là xong.

---

## 3. Bản đồ Menu Chuột phải (Context Menus)

**Khi click chuột phải vào HÀNG (Row Mode):**
* Di chuyển lên/xuống (`Alt+1`, `Alt+2`)
* Xóa dòng (`Delete`)
* Gộp ảnh (`Alt+3`)
* Xóa các khung cắt thừa
* AI Vision (OCR)
* Dịch và viết lại
* Áp dụng hiệu ứng In/Out ngẫu nhiên

**Khi click chuột phải vào Ô VĂN BẢN (Cell Mode):**
* Thao tác văn bản ➔ Viết hoa đầu câu / Viết thường toàn bộ / Xóa dòng trống
* Copy / Paste text

---

## 4. Mapping thiết kế UI với Kiến trúc lõi (Architecture v5)

Để dev frontend và backend hiểu nhau, đây là ánh xạ giữa UI và Core (Không hiển thị cho End-user):
* UI không bao giờ hiển thị khái niệm "Staged Artifacts" (v1, v2) hay "ID Anchor" (`pa_xxx`). Mọi thứ được giấu ngầm dưới File `project.json` để giữ UI sạch sẽ.
* Khi user vẽ khung bằng chuột (Layout Editor), UI hiển thị khung nét đứt. Dưới Core, hành động này tạo ra một `anchor` với thuộc tính `locked: true` ghi vào mục `layout_overrides` trong `project.json`.
* Khi user bấm nút `Xuất`, UI chỉ hiện tiến trình thanh trượt. Dưới Core, thao tác này gọi `Render Plan` (đã resolve overrides + templates) rồi truyền data cho `CapCut Project Adapter` để serialize thành JSON Bundle.