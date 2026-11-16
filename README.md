# ASRTool

Công cụ Windows tạo phụ đề SRT tiếng Trung từ thư mục âm thanh hoặc video.

## Chạy giao diện

Mở `run.bat`, chọn **Folder input**, chọn **Folder output**, rồi nhấn **Tạo SRT file**.

Ứng dụng xử lý lần lượt các file trực tiếp trong folder input. Ví dụ `tập01.mp4` tạo `tập01.srt` và `tập01.json` trong folder output. Thanh tiến trình tính theo số file đã xử lý. Log ghi bước đang chạy và lỗi của từng file.

- Hỗ trợ WAV, MP3, FLAC, M4A, AAC, OGG, OPUS, WMA, MP4, MKV, MOV, AVI, WEBM và TS.
- Bật **Phân biệt người nói (CAM++)** để lưu speaker theo token trong JSON. Một vùng VAD có nhiều speaker được ghép thành một segment, nhãn chi tiết nằm trên từng token. Nhãn được đánh số theo lần xuất hiện trong mỗi file.
- Bật **Ghi đè SRT đã tồn tại** để xử lý lại. Mặc định bỏ qua file đã có SRT.
- Các file trùng tên gốc như `a.wav` và `a.mp4` sẽ báo lỗi để người dùng đổi tên trước khi chạy lại.
- File lỗi được ghi log rồi chuyển sang file kế tiếp. Nếu không phát hiện giọng nói, ứng dụng xuất SRT rỗng.
- Lần đầu chạy cần mạng để tải model vào `.models`. Khi đã tải đủ, model được dùng từ bộ nhớ đệm.

## Môi trường

Máy triển khai có Python 3.13, GTX 1060 6 GB, driver NVIDIA 560.94 và FFmpeg trong PATH. Script dùng PyTorch 2.6.0 + CUDA 12.4, torchaudio 2.6.0 và FunASR 1.4.26. Các phiên bản phụ thuộc đã cài được cố định trong `requirements.txt`. Model được tải từ các repository chính thức của FunASR trên Hugging Face. Chạy trong PowerShell tại thư mục dự án để thiết lập lại môi trường khi cần.

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

Kiểm tra thư viện và thực thi phép tính CUDA.

```powershell
.\.venv\Scripts\python.exe pipeline.py --check
```

## Chạy bằng dòng lệnh

```powershell
.\.venv\Scripts\python.exe pipeline.py --input "F:\audio" --output "F:\subtitles"
```

Thêm `--speaker` để bật CAM++, `--overwrite` để ghi đè SRT.

## Kiểm tra kết quả

Pipeline dùng Paraformer tiếng Trung, FSMN-VAD và CT-Punc. FSMN-VAD dùng ngưỡng khoảng lặng cố định 300 ms, với `dynamic_silence=False`, áp dụng đồng nhất cho VAD độc lập và VAD trong pipeline ASR. Mỗi vùng VAD có token tạo một segment SRT. Nội dung gồm các token trong vùng, start lấy mốc bắt đầu token đầu tiên và end lấy mốc kết thúc token cuối cùng. Dấu câu được giữ trong nội dung. Giới hạn mỗi vùng VAD là khoảng 30 giây. Timestamp token được đối chiếu và giới hạn trong vùng VAD. JSON giữ cấu hình VAD, kết quả model, các vùng VAD, token có `vad_index`, phụ đề và lỗi để truy vết. Khi text không khớp số timestamp, file được báo lỗi cùng JSON để kiểm tra.

Để tạo lại phụ đề theo cấu hình này, mở lại ứng dụng, bật **Ghi đè SRT đã tồn tại** rồi chạy lại thư mục input.

Log giao diện được lưu tại `.logs/asrtool.log`. Đầu ra bổ sung từ thư viện khi chạy bằng `run.bat` được lưu tại `.logs/runtime.log`.

Đã xác nhận phép tính CUDA trên GTX 1060 và chạy thành công mẫu tiếng Trung công khai dài 5,5 giây qua ASR/VAD/Punc, cùng một lượt bật CAM++. Kết quả được lưu tại `.venv/smoke/output` và `.venv/smoke/speaker-output`. Cần đối chiếu thêm với voice 1–3 phút và phim 2–3 người nói để đánh giá chất lượng trên dữ liệu sử dụng thực tế.

Tài liệu tham khảo

- [FunASR](https://github.com/modelscope/FunASR)
- [Các phiên bản PyTorch và lệnh cài CUDA](https://pytorch.org/get-started/previous-versions/)
# srtASR
