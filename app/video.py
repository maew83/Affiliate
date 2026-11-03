"""ประกอบวิดีโอแนวตั้ง 9:16 จากรูปสินค้า + เสียงพากย์ + ซับ ด้วย ffmpeg"""
import json
import os
import re
import subprocess
from pathlib import Path

WIDTH, HEIGHT, FPS = 1080, 1920, 30
MAX_SUB_CHARS = 26   # ความยาวซับต่อบรรทัด (ภาษาไทยไม่มีเว้นวรรค ต้องตัดเอง)
HOOK_SECONDS = 3.0   # แสดงข้อความ hook ด้านบนกี่วินาทีแรก


class VideoError(Exception):
    pass


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise VideoError(f"ffmpeg ล้มเหลว:\n{p.stderr[-1500:]}")
    return p.stdout


def audio_duration(path: Path) -> float:
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)])
    return float(json.loads(out)["format"]["duration"])


# ---------- ซับไตเติล ----------

def _srt_time(t: str) -> float:
    h, m, rest = t.strip().split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_srt(text: str) -> list[tuple[float, float, str]]:
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        if len(lines) >= 3 and "-->" in lines[1]:
            start, end = lines[1].split("-->")
            cues.append((_srt_time(start), _srt_time(end), " ".join(lines[2:]).strip()))
    return cues


THAI_COMBINING = set("ัิีึืฺุู็่้๊๋์ํ๎")
THAI_LEADING_VOWELS = set("เแโใไ")  # เ แ โ ใ ไ ต้องอยู่ติดพยัญชนะตัวถัดไป
THAI_FOLLOWING = set("ะาำๅ")  # ะ า ำ ๅ ต้องอยู่ติดพยัญชนะตัวก่อน


def _safe_cut(word: str, limit: int) -> int:
    """หาตำแหน่งตัดที่ไม่แยกสระ/วรรณยุกต์ออกจากพยัญชนะ"""
    cut = limit
    while cut > 1 and (
        word[cut] in THAI_COMBINING or word[cut] in THAI_FOLLOWING
        or word[cut - 1] in THAI_LEADING_VOWELS
    ):
        cut -= 1
    return cut


def _split_text(text: str, limit: int) -> list[str]:
    """ตัดข้อความยาวเป็นท่อน ๆ พยายามตัดที่ช่องว่างก่อน"""
    parts, buf = [], ""
    for word in text.split(" "):
        while len(word) > limit:  # คำไทยยาวไม่มีเว้นวรรค ตัดตามจำนวนตัวอักษร
            if buf:
                parts.append(buf)
                buf = ""
            cut = _safe_cut(word, limit)
            parts.append(word[:cut])
            word = word[cut:]
        candidate = f"{buf} {word}".strip()
        if len(candidate) > limit and buf:
            parts.append(buf)
            buf = word
        else:
            buf = candidate
    if buf:
        parts.append(buf)
    return parts


def _split_cues(cues, limit=MAX_SUB_CHARS):
    """แบ่ง cue ที่ยาวเกินเป็นหลายท่อน แล้วกระจายเวลาตามสัดส่วนความยาว"""
    result = []
    for start, end, text in cues:
        chunks = _split_text(text, limit)
        total = sum(len(c) for c in chunks) or 1
        t = start
        for c in chunks:
            dt = (end - start) * len(c) / total
            result.append((t, t + dt, c))
            t += dt
    return result


def _ass_time(sec: float) -> str:
    cs = int(round(sec * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def build_ass(cues, hook: str, font: str) -> str:
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{font},72,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,5,2,2,60,60,320,1
Style: Hook,{font},88,&H0000F0FF,&H0000F0FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,6,3,8,60,60,220,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    if hook:
        hook_lines = _split_text(hook, 18)
        lines.append(
            f"Dialogue: 1,{_ass_time(0)},{_ass_time(HOOK_SECONDS)},Hook,,0,0,0,,"
            + r"\N".join(_ass_escape(h) for h in hook_lines)
        )
    for start, end, text in _split_cues(cues):
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Sub,,0,0,0,,{_ass_escape(text)}")
    return header + "\n".join(lines) + "\n"


# ---------- ประกอบวิดีโอ ----------

def make_video(images: list[str], audio: Path, srt: Path, hook: str, out: Path) -> None:
    if not images:
        raise VideoError("ต้องมีรูปสินค้าอย่างน้อย 1 รูป")

    work = out.parent
    font = os.getenv("SUBTITLE_FONT", "Tahoma")
    cues = parse_srt(srt.read_text(encoding="utf-8")) if srt.exists() else []
    (work / "subs.ass").write_text(build_ass(cues, hook, font), encoding="utf-8")

    duration = audio_duration(audio) + 0.5
    per_image = max(duration / len(images), 1.5)

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for img in images:
        cmd += ["-loop", "1", "-t", f"{per_image:.3f}", "-i", str(Path(img).resolve())]
    cmd += ["-i", str(audio.resolve())]

    # แต่ละรูป: พื้นหลังเบลอเต็มจอ + รูปจริงวางกลาง แล้วต่อกันทั้งหมด
    filters = []
    for i in range(len(images)):
        filters.append(
            f"[{i}:v]split[a{i}][b{i}];"
            f"[a{i}]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},boxblur=30:5[bg{i}];"
            f"[b{i}]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease[fg{i}];"
            f"[bg{i}][fg{i}]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={FPS},format=yuv420p[v{i}]"
        )
    concat_in = "".join(f"[v{i}]" for i in range(len(images)))
    filters.append(f"{concat_in}concat=n={len(images)}:v=1:a=0[slides]")
    filters.append("[slides]subtitles=subs.ass[outv]")

    cmd += [
        "-filter_complex", ";".join(filters),
        "-map", "[outv]", "-map", f"{len(images)}:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest", "-movflags", "+faststart",
        str(out.resolve()),
    ]
    _run(cmd, cwd=work)
