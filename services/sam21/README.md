# OpenCut SAM 2.1 Local

Dịch vụ local dùng `sam2.1_hiera_tiny` để tách người/vật khỏi ảnh hoặc video. Model chạy trên CPU, không gửi media lên máy chủ bên ngoài.

## Cài trên Windows

### Cách dễ nhất

Tại thư mục gốc của OpenCut, nhấp đúp `CAI-DAT-OPENCUT.bat`. Bộ cài sẽ tự kiểm tra và cài Python 3.11, FFmpeg, Bun, thư viện OpenCut, SAM 2.1 Tiny, sau đó tạo biểu tượng **OpenCut SAM 2.1** ngoài Desktop.

Những lần sau chỉ cần mở biểu tượng Desktop hoặc nhấp đúp `MO-OPENCUT.bat`.

### Cài thủ công

Yêu cầu:

- Python 3.11 x64
- FFmpeg có trong `PATH`
- Khoảng 6 GB dung lượng trống cho môi trường Python và model

Mở PowerShell trong thư mục này:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup-windows.ps1
.\start-windows.ps1
```

Dịch vụ chạy tại `http://127.0.0.1:8788`. Giữ cửa sổ PowerShell này mở khi dùng tab **Xóa nền AI** trong OpenCut.

## Luồng sử dụng

1. Chọn ảnh hoặc video trên timeline.
2. Mở tab **Xóa nền AI** ở bảng thuộc tính bên phải.
3. Bấm vào người/vật cần giữ lại trên ảnh xem trước.
4. Chọn nền trong suốt, màu đơn hoặc ảnh nền.
5. Bấm **Tách nền AI**. Kết quả được thêm vào Media để kéo lại timeline.

Với CPU, nên dùng clip 5–15 giây và độ phân giải 720p. Kết quả nền trong suốt của video dùng WebM VP9; hai chế độ thay nền xuất MP4 H.264.
