"""Windows local test interface for sequential folder-to-SRT conversion."""
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / ".logs"
LOG_DIR.mkdir(exist_ok=True)
# pythonw has no console streams. Third-party libraries still write to them.
if sys.stdout is None:
    sys.stdout = open(LOG_DIR / "runtime.log", "a", encoding="utf-8", buffering=1)
if sys.stderr is None:
    sys.stderr = sys.stdout

from pipeline import process_folder


class QueueHandler(logging.Handler):
    def __init__(self, events):
        super().__init__()
        self.events = events
        self.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record):
        self.events.put(("log", self.format(record)))


class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ASRTool — Tạo SRT tiếng Trung")
        self.geometry("840x600")
        self.minsize(700, 500)
        self.events = queue.Queue()
        self.running = False
        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.speaker = tk.BooleanVar(value=False)
        self.overwrite = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Chọn folder input và folder output để bắt đầu.")
        self.counter = tk.StringVar(value="0 / 0 file")
        self.controls = []
        self._build_ui()
        self._configure_logging()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(100, self._poll_events)

    def _build_ui(self):
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("TLabel", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 6))
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(7, weight=1)
        for row, label, variable in ((0, "Folder input", self.input_dir), (1, "Folder output", self.output_dir)):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=6)
            entry = ttk.Entry(frame, textvariable=variable)
            entry.grid(row=row, column=1, sticky="ew", pady=6)
            button = ttk.Button(frame, text="Chọn thư mục…", command=lambda value=variable: self._choose_folder(value))
            button.grid(row=row, column=2, padx=(10, 0), pady=6)
            self.controls.extend([entry, button])
        options = ttk.Frame(frame)
        options.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 12))
        for label, variable in (("Phân biệt người nói (CAM++)", self.speaker), ("Ghi đè SRT đã tồn tại", self.overwrite)):
            checkbox = ttk.Checkbutton(options, text=label, variable=variable)
            checkbox.pack(side="left", padx=(0, 20))
            self.controls.append(checkbox)
        self.start_button = ttk.Button(frame, text="Tạo SRT file", command=self._start)
        self.start_button.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(0, 14))
        self.controls.append(self.start_button)
        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=1)
        self.progress.grid(row=4, column=0, columnspan=2, sticky="ew")
        ttk.Label(frame, textvariable=self.counter, anchor="e").grid(row=4, column=2, sticky="e")
        ttk.Label(frame, textvariable=self.status, wraplength=760).grid(row=5, column=0, columnspan=3, sticky="w", pady=(10, 12))
        ttk.Label(frame, text="Log xử lý").grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 6))
        self.log = scrolledtext.ScrolledText(frame, state="disabled", wrap="word", font=("Consolas", 10), height=12)
        self.log.grid(row=7, column=0, columnspan=3, sticky="nsew")

    def _configure_logging(self):
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        logger.addHandler(QueueHandler(self.events))
        file_handler = RotatingFileHandler(LOG_DIR / "asrtool.log", maxBytes=5_000_000, backupCount=2, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(file_handler)

    def _choose_folder(self, variable):
        directory = filedialog.askdirectory(parent=self, title="Chọn thư mục", initialdir=variable.get() or str(ROOT))
        if directory:
            variable.set(directory)

    def _start(self):
        if self.running:
            return
        input_value = self.input_dir.get().strip()
        output_value = self.output_dir.get().strip()
        if not input_value or not Path(input_value).is_dir():
            messagebox.showerror("Folder input", "Hãy chọn folder input tồn tại.", parent=self)
            return
        if not output_value:
            messagebox.showerror("Folder output", "Hãy chọn folder output.", parent=self)
            return
        if Path(output_value).exists() and not Path(output_value).is_dir():
            messagebox.showerror("Folder output", "Đường dẫn output phải là một thư mục.", parent=self)
            return
        self.running = True
        for control in self.controls:
            control.configure(state="disabled")
        self.progress.configure(value=0, maximum=1)
        self.counter.set("0 / 0 file")
        self.status.set("Đang chuẩn bị danh sách file…")
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        # Read Tk values in the UI thread before starting the worker.
        arguments = (input_value, output_value, self.speaker.get(), self.overwrite.get())
        threading.Thread(target=self._worker, args=arguments, daemon=True).start()

    def _worker(self, input_dir, output_dir, speaker, overwrite):
        try:
            summary = process_folder(
                input_dir, output_dir, speaker=speaker, overwrite=overwrite,
                on_progress=lambda done, total, name: self.events.put(("progress", (done, total, name))),
            )
            self.events.put(("done", summary))
        except Exception as error:
            logging.getLogger("asrtool").exception("Không thể xử lý thư mục")
            self.events.put(("error", str(error)))

    def _poll_events(self):
        # Bound each UI update so a burst of model logs cannot starve Tk events.
        for _ in range(200):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.log.configure(state="normal")
                self.log.insert("end", value + "\n")
                if int(self.log.index("end-1c").split(".")[0]) > 2000:
                    self.log.delete("1.0", "201.0")
                self.log.see("end")
                self.log.configure(state="disabled")
            elif kind == "progress":
                done, total, name = value
                self.progress.configure(value=done, maximum=total)
                self.counter.set(f"{done} / {total} file")
                self.status.set(f"Đang xử lý {name}")
            elif kind in {"done", "error"}:
                self.running = False
                for control in self.controls:
                    control.configure(state="normal")
                if kind == "error":
                    self.status.set("Xử lý thất bại. Xem log để biết chi tiết.")
                    messagebox.showerror("Lỗi xử lý", value, parent=self)
                else:
                    text = f"Hoàn tất {value['total']} file. Thành công {value['success']}, bỏ qua {value['skipped']}, lỗi {value['failed']}."
                    self.status.set(text)
                    if value["failed"]:
                        messagebox.showwarning("Kết quả xử lý", text + "\nXem log để kiểm tra file lỗi.", parent=self)
                    else:
                        messagebox.showinfo("Kết quả xử lý", text, parent=self)
        self.after(100, self._poll_events)

    def _close(self):
        if self.running:
            messagebox.showinfo("Đang xử lý", "Vui lòng đợi xử lý xong trước khi đóng ứng dụng.", parent=self)
            return
        self.destroy()


if __name__ == "__main__":
    Application().mainloop()

