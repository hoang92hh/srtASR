"""Local FunASR pipeline and sequential folder processing."""
from dataclasses import asdict
from pathlib import Path
import argparse
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
import traceback

from subtitles import aligned_tokens, build_cues, to_srt

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("MODELSCOPE_CACHE", str(ROOT / ".models" / "modelscope"))
os.environ.setdefault("HF_HOME", str(ROOT / ".models" / "huggingface"))
EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".mp4", ".mkv", ".mov", ".avi", ".webm", ".ts"}
LOG = logging.getLogger("asrtool")
for logger_name in ("httpx", "httpx2", "httpcore", "httpcore2"):
    logging.getLogger(logger_name).setLevel(logging.WARNING)


def atomic_write(destination, content):
    destination = Path(destination)
    descriptor, temporary = tempfile.mkstemp(prefix=".asr-", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def json_default(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Không thể lưu JSON cho {type(value).__name__}")


def save_json(destination, data):
    atomic_write(destination, json.dumps(data, ensure_ascii=False, indent=2, default=json_default))


def check_environment():
    import torch
    import funasr
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("Thiếu FFmpeg. Cài FFmpeg và thêm vào PATH trước khi chạy.")
    info = {"torch": torch.__version__, "funasr": funasr.__version__, "ffmpeg": ffmpeg, "cuda": torch.cuda.is_available()}
    if info["cuda"]:
        # Execute a real kernel to check support for this GPU architecture.
        tensor = torch.ones((64, 64), device="cuda")
        info["cuda_test"] = float((tensor @ tensor).sum().item())
        info["gpu"] = torch.cuda.get_device_name(0)
        info["architectures"] = torch.cuda.get_arch_list()
        torch.cuda.synchronize()
    return info


class Pipeline:
    def __init__(self, speaker=False):
        import torch
        from funasr import AutoModel
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        LOG.info("Thiết bị xử lý %s. Đang tải model, lần đầu cần kết nối mạng.", self.device)
        self.vad_options = {
            "max_single_segment_time": 30000,
            "max_end_silence_time": 300,
            "dynamic_silence": False,
        }
        options = dict(
            model="funasr/paraformer-zh", hub="hf",
            vad_model="fsmn-vad", punc_model="ct-punc",
            device=self.device, ncpu=4, disable_update=True,
            vad_kwargs=dict(self.vad_options),
        )
        if speaker:
            options["spk_model"] = "cam++"
        self.model = AutoModel(**options)
        # Retain a separate VAD result for the diagnostic JSON and timing checks.
        self.vad = AutoModel(
            model="fsmn-vad", hub="hf", device=self.device, ncpu=4,
            disable_update=True, **self.vad_options,
        )
        self.speaker = speaker

    def transcribe(self, source, output, show_speaker=False):
        import soundfile as sf
        started = time.monotonic()
        diagnostic = {
            "source": str(source.resolve()),
            "speaker_enabled": self.speaker,
            "device": self.device,
            "vad_options": dict(self.vad_options),
            "subtitle_grouping": "vad",
        }
        json_path = output / (source.stem + ".json")
        try:
            with tempfile.TemporaryDirectory(prefix="asrtool-") as directory:
                audio_path = Path(directory) / "audio.wav"
                LOG.info("%s — chuyển âm thanh sang mono 16 kHz", source.name)
                conversion = subprocess.run(
                    [shutil.which("ffmpeg"), "-nostdin", "-v", "error", "-y", "-i", str(source.resolve()),
                     "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio_path)],
                    capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if conversion.returncode:
                    raise RuntimeError("FFmpeg " + conversion.stderr.decode("utf-8", errors="replace")[-2000:])
                audio, rate = sf.read(audio_path, dtype="float32")
                diagnostic["duration_ms"] = round(len(audio) * 1000 / rate)
                if not len(audio):
                    raise ValueError("File không có dữ liệu âm thanh.")
                LOG.info("%s — kiểm tra vùng giọng nói, ngưỡng khoảng lặng 300 ms", source.name)
                vad_result = self.vad.generate(
                    input=audio, fs=rate, disable_pbar=True, **self.vad_options,
                )
                diagnostic["vad_raw"] = vad_result
                regions = vad_result[0].get("value", []) if vad_result else []
                diagnostic["vad_regions_ms"] = regions
                result = {"text": "", "timestamp": [], "sentence_info": []}
                if regions:
                    LOG.info("%s — nhận dạng, dấu câu%s", source.name, " và speaker" if self.speaker else "")
                    results = self.model.generate(
                        input=audio, fs=rate, batch_size_s=30, sentence_timestamp=True,
                        return_raw_text=True, output_timestamp=True, return_time_stamps=True,
                        disable_pbar=True, merge_vad=False, **self.vad_options,
                    )
                    diagnostic["asr_raw"] = results
                    if not results:
                        raise ValueError("Model không trả kết quả ASR.")
                    result = results[0]
                    if not result.get("text", "").strip():
                        raise ValueError("VAD phát hiện giọng nói nhưng ASR không trả text.")
                else:
                    diagnostic["asr_raw"] = [result]
                    LOG.info("%s — không phát hiện giọng nói, xuất SRT rỗng", source.name)
            # Persist raw model data before attempting strict alignment.
            save_json(json_path, diagnostic)
            tokens = aligned_tokens(result, regions)
            if tokens and tokens[-1].end > diagnostic["duration_ms"] + 100:
                raise ValueError("Timestamp vượt thời lượng âm thanh. Xem JSON.")
            cues = build_cues(tokens)
            diagnostic.update(tokens=[asdict(token) for token in tokens], cues=[asdict(cue) for cue in cues],
                              elapsed_seconds=round(time.monotonic() - started, 2), status="success")
            save_json(json_path, diagnostic)
            atomic_write(output / (source.stem + ".srt"), to_srt(cues, show_speaker))
            return len(cues)
        except Exception as error:
            diagnostic.update(status="error", error=str(error), traceback=traceback.format_exc())
            save_json(json_path, diagnostic)
            raise


def process_folder(input_dir, output_dir, speaker=False, overwrite=False, on_progress=None):
    source_dir = Path(input_dir).expanduser().resolve()
    target_dir = Path(output_dir).expanduser().resolve()
    if not source_dir.is_dir():
        raise ValueError("Folder input không tồn tại.")
    target_dir.mkdir(parents=True, exist_ok=True)
    files = sorted((item for item in source_dir.iterdir() if item.is_file() and item.suffix.lower() in EXTENSIONS),
                   key=lambda item: item.name.casefold())
    if not files:
        raise ValueError("Folder input không có file âm thanh hoặc video được hỗ trợ.")
    counts = {}
    for source in files:
        counts[source.stem.casefold()] = counts.get(source.stem.casefold(), 0) + 1
    summary = {"total": len(files), "success": 0, "failed": 0, "skipped": 0}
    pipeline = None
    for index, source in enumerate(files, 1):
        if on_progress:
            on_progress(index - 1, len(files), source.name)
        LOG.info("[%d/%d] %s", index, len(files), source.name)
        if counts[source.stem.casefold()] > 1:
            LOG.error("%s — trùng tên gốc với file khác, cùng đích %s.srt. Hãy đổi tên file.", source.name, source.stem)
            summary["failed"] += 1
        elif (target_dir / (source.stem + ".srt")).exists() and not overwrite:
            LOG.info("%s — bỏ qua vì SRT đã tồn tại", source.name)
            summary["skipped"] += 1
        else:
            try:
                if pipeline is None:
                    pipeline = Pipeline(speaker=speaker)
                cue_count = pipeline.transcribe(source, target_dir)
                LOG.info("%s — hoàn thành, %d dòng phụ đề", source.name, cue_count)
                summary["success"] += 1
            except Exception:
                LOG.exception("%s — xử lý thất bại", source.name)
                summary["failed"] += 1
        if on_progress:
            on_progress(index, len(files), source.name)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Tạo SRT tiếng Trung từ folder audio/video")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--speaker", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if arguments.check:
        print(json.dumps(check_environment(), ensure_ascii=False, indent=2))
        return
    if arguments.input is None or arguments.output is None:
        parser.error("Cần --input và --output")
    summary = process_folder(arguments.input, arguments.output, arguments.speaker, arguments.overwrite)
    print(json.dumps(summary))
    if summary["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
