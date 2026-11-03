"""แปลงสคริปต์เป็นเสียงพากย์ภาษาไทยด้วย Edge TTS พร้อมไฟล์ซับ (.srt) ที่ตรงจังหวะเสียง"""
import os
from pathlib import Path

import edge_tts

DEFAULT_VOICE = "th-TH-PremwadeeNeural"


async def synthesize(text: str, audio_path: Path, srt_path: Path, voice: str | None = None) -> None:
    voice = voice or os.getenv("TTS_VOICE", DEFAULT_VOICE)
    communicate = edge_tts.Communicate(text, voice)
    submaker = edge_tts.SubMaker()
    with open(audio_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                submaker.feed(chunk)
    srt_path.write_text(submaker.get_srt(), encoding="utf-8")
