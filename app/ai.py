"""ให้ Claude ดูรูปสินค้า + ข้อมูล แล้วเขียนแคปชันและสคริปต์เสียงพากย์"""
import base64
import io
import json
from pathlib import Path

import anthropic
from PIL import Image

MODEL = "claude-opus-5-5"
MAX_IMAGES_TO_CLAUDE = 4  # ส่งรูปให้ Claude ดูไม่เกินนี้ ประหยัด token

PLATFORM_NAMES = {"shopee": "Shopee", "tiktok_shop": "TikTok Shop"}

SYSTEM_PROMPT = """คุณเป็นครีเอเตอร์สายรีวิวสินค้าภาษาไทย ทำคอนเทนต์ affiliate ลง Facebook Reels และ TikTok
กฎ:
- เขียนภาษาไทยเป็นกันเอง กระชับ ดึงดูดใน 3 วินาทีแรก
- พูดถึงเฉพาะจุดเด่นที่มีในข้อมูลหรือเห็นได้จากรูปเท่านั้น ห้ามแต่งสรรพคุณ ผลลัพธ์ หรือคำรับรองที่ไม่มีหลักฐาน
- ห้ามอ้างทางการแพทย์ ห้ามรับประกันผลลัพธ์
- ทุกแคปชันต้องบอกชัดว่าเป็นลิงก์ affiliate (เช่น "ลิงก์นายหน้า" หรือ #affiliate)
- voice_script คือข้อความที่จะถูกอ่านออกเสียง: ไม่มีอีโมจิ ไม่มีแฮชแท็ก ไม่มี URL ความยาวพูดจบประมาณ 20-40 วินาที
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "hook": {"type": "string", "description": "ประโยคเปิดคลิป สั้นมาก ใช้เป็นข้อความบนวิดีโอ"},
        "voice_script": {"type": "string"},
        "caption_facebook": {"type": "string"},
        "caption_tiktok": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["hook", "voice_script", "caption_facebook", "caption_tiktok", "hashtags"],
    "additionalProperties": False,
}


class ContentError(Exception):
    pass


def _image_block(path: str) -> dict:
    """ย่อรูปให้ไม่เกิน 1568px แล้วแปลงเป็น base64 JPEG"""
    img = Image.open(path).convert("RGB")
    img.thumbnail((1568, 1568))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.standard_b64encode(buf.getvalue()).decode("utf-8"),
        },
    }


def generate_content(product: dict) -> dict:
    client = anthropic.Anthropic()

    info = (
        f"แพลตฟอร์ม: {PLATFORM_NAMES.get(product['platform'], product['platform'])}\n"
        f"ชื่อสินค้า: {product['name']}\n"
        f"ราคา: {product.get('price') or '-'}\n"
        f"จุดเด่น: {product.get('highlights') or '-'}\n"
        f"ลิงก์ affiliate: {product.get('affiliate_link') or '-'}"
    )
    content = [_image_block(p) for p in product["images"][:MAX_IMAGES_TO_CLAUDE]]
    content.append({
        "type": "text",
        "text": f"{info}\n\nเขียนคอนเทนต์สำหรับคลิปสั้นรีวิวสินค้านี้ "
                "ใส่ลิงก์ affiliate ไว้ในแคปชัน Facebook (TikTok ไม่ต้องใส่ลิงก์ ให้ชวนกดตะกร้า/ลิงก์ในโปรไฟล์แทน)",
    })

    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM_PROMPT,
            output_config={
                "effort": "medium",
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            },
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.AuthenticationError as e:
        raise ContentError("ANTHROPIC_API_KEY ไม่ถูกต้องหรือยังไม่ได้ตั้งค่า") from e
    except anthropic.RateLimitError as e:
        raise ContentError("เรียก Claude ถี่เกินไป ลองใหม่อีกครั้งในอีกสักครู่") from e
    except anthropic.APIStatusError as e:
        raise ContentError(f"Claude API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise ContentError("เชื่อมต่อ Claude API ไม่ได้ ตรวจสอบอินเทอร์เน็ต") from e

    if response.stop_reason == "refusal":
        raise ContentError("Claude ปฏิเสธการสร้างคอนเทนต์นี้ ลองปรับข้อมูลสินค้า")
    if response.stop_reason == "max_tokens":
        raise ContentError("คำตอบยาวเกินกำหนด ลองใหม่อีกครั้ง")

    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)
