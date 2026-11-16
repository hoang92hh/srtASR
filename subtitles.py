"""Build one Chinese subtitle cue per VAD region using aligned token times."""
from dataclasses import dataclass
import math
import re
import unicodedata


@dataclass
class Token:
    text: str
    start: int
    end: int
    speaker: str | None = None
    vad_index: int | None = None


@dataclass
class Cue:
    start: int
    end: int
    text: str
    speaker: str | None = None


def text_units(text):
    """Keep Chinese characters and Latin words aligned with Paraformer tokens."""
    units = []
    prefix = ""
    for value in re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*|[^\s]", text):
        if all(unicodedata.category(char)[0] in "PS" for char in value):
            if units:
                units[-1] += value
            else:
                prefix += value
        else:
            units.append(prefix + value)
            prefix = ""
    if prefix:
        raise ValueError("Kết quả chỉ có dấu câu, không thể căn timestamp.")
    return units


def join_units(units):
    result = ""
    for unit in units:
        if result and result[-1].isascii() and result[-1].isalnum() and unit[0].isascii() and unit[0].isalnum():
            result += " "
        result += unit
    return result


def aligned_tokens(result, vad_regions):
    sentences = result.get("sentence_info") or []
    if not sentences and result.get("text", "").strip():
        sentences = [result]
    recognized = result.get("text", "")
    segmented = "".join(sentence.get("text", "") for sentence in sentences)
    def content(text):
        return "".join(char for char in text if not char.isspace() and unicodedata.category(char)[0] not in "PS")
    if content(recognized).casefold() != content(segmented).casefold():
        raise ValueError("Text câu không khớp text tổng của ASR. Xem JSON để kiểm tra.")
    tokens = []
    speaker_names = {}
    previous_start = -1
    for sentence_index, sentence in enumerate(sentences):
        units = text_units(sentence.get("text", ""))
        times = sentence.get("timestamp") or []
        if len(units) != len(times):
            raise ValueError(
                f"Text/timestamp không khớp ({len(units)} token, {len(times)} mốc). "
                "Xem JSON để kiểm tra, chưa thể xuất SRT chính xác."
            )
        speaker_id = sentence.get("spk")
        speaker = None
        if speaker_id is not None:
            speaker = speaker_names.setdefault(str(speaker_id), f"speaker{len(speaker_names):02d}")
        for unit, pair in zip(units, times):
            if len(pair) != 2 or not all(math.isfinite(float(value)) for value in pair):
                raise ValueError("Timestamp token không hợp lệ.")
            start, end = [round(float(value)) for value in pair]
            # FunASR's frame shift can place the first token at -90 ms.
            if sentence_index == 0 and not tokens and start == -90:
                start = 0
            if start < 0 or end <= start or start < previous_start:
                raise ValueError("Timestamp token âm, đảo thứ tự hoặc không có thời lượng.")
            previous_start = start
            vad_index = None
            if vad_regions:
                overlaps = [
                    (index, max(start, int(a)), min(end, int(b)))
                    for index, (a, b) in enumerate(vad_regions)
                    if a < end and b > start
                ]
                if not overlaps:
                    raise ValueError(f"Token tại {start} ms nằm ngoài vùng VAD. Xem JSON.")
                vad_index, start, end = max(
                    overlaps, key=lambda interval: interval[2] - interval[1],
                )
            tokens.append(Token(unit, start, end, speaker, vad_index=vad_index))
    if result.get("text", "").strip() and not tokens:
        raise ValueError("ASR có text nhưng thiếu timestamp token.")
    return tokens


def build_cues(tokens):
    """Group every VAD region's tokens into one cue, retaining its token times."""
    groups = {}
    for token in tokens:
        if token.vad_index is None:
            raise ValueError("Token thiếu chỉ số vùng VAD. Cần xử lý lại file âm thanh.")
        groups.setdefault(token.vad_index, []).append(token)

    cues = []
    for vad_index in sorted(groups):
        group = groups[vad_index]
        speakers = {token.speaker for token in group}
        # Mixed-speaker regions retain detailed labels on their individual tokens.
        speaker = group[0].speaker if len(speakers) == 1 else None
        cue = Cue(
            start=group[0].start,
            end=group[-1].end,
            text=join_units([token.text for token in group]),
            speaker=speaker,
        )
        if cue.end <= cue.start:
            raise ValueError("Segment VAD không có thời lượng hợp lệ. Xem JSON.")
        if cues and cue.start < cues[-1].end:
            raise ValueError("Các segment VAD có timestamp chồng lấn. Xem JSON.")
        cues.append(cue)
    return cues


def format_time(milliseconds):
    seconds, milliseconds = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def to_srt(cues, show_speaker=False):
    blocks = []
    for index, cue in enumerate(cues, 1):
        text = cue.text
        if show_speaker and cue.speaker:
            text = f"[{cue.speaker}] {text}"
        blocks.append(f"{index}\n{format_time(cue.start)} --> {format_time(cue.end)}\n{text}\n")
    return "\n".join(blocks)
