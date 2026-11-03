"""เว็บแอปสร้างคอนเทนต์ affiliate: แคปชัน + เสียงพากย์ + วิดีโอสไลด์"""
import asyncio
import shutil
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from . import ai, db, tts, video  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"
UPLOAD_DIR = db.DATA_DIR / "uploads"
OUTPUT_DIR = db.DATA_DIR / "outputs"
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
PLATFORMS = {"shopee", "tiktok_shop"}

app = FastAPI(title="Affiliate Content Studio")
db.init()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=db.DATA_DIR), name="media")


def media_url(path: str | None) -> str | None:
    if not path:
        return None
    return "/media/" + Path(path).resolve().relative_to(db.DATA_DIR.resolve()).as_posix()


def to_public(p: dict) -> dict:
    return {
        **p,
        "image_urls": [media_url(i) for i in p["images"]],
        "audio_url": media_url(p["audio_path"]),
        "video_url": media_url(p["video_path"]),
    }


# ---------- งานเบื้องหลัง ----------

def render_media(pid: int) -> None:
    """สร้างเสียงพากย์ + วิดีโอ จากคอนเทนต์ที่มีอยู่"""
    p = db.get_product(pid)
    out_dir = OUTPUT_DIR / str(pid)
    out_dir.mkdir(parents=True, exist_ok=True)
    audio, srt, mp4 = out_dir / "voice.mp3", out_dir / "voice.srt", out_dir / "video.mp4"

    asyncio.run(tts.synthesize(p["content"]["voice_script"], audio, srt))
    video.make_video(p["images"], audio, srt, p["content"].get("hook", ""), mp4)
    db.update_product(pid, status="done", error=None, audio_path=str(audio), video_path=str(mp4))


def run_pipeline(pid: int, regenerate_text: bool) -> None:
    try:
        if regenerate_text:
            content = ai.generate_content(db.get_product(pid))
            db.update_product(pid, content=content)
        render_media(pid)
    except Exception as e:  # แสดงข้อผิดพลาดให้ผู้ใช้เห็นในหน้าเว็บ
        db.update_product(pid, status="error", error=str(e))


# ---------- API ----------

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/products")
def list_products():
    return [to_public(p) for p in db.list_products()]


@app.get("/api/products/{pid}")
def get_product(pid: int):
    p = db.get_product(pid)
    if not p:
        raise HTTPException(404, "ไม่พบสินค้า")
    return to_public(p)


@app.post("/api/products")
async def create_product(
    platform: str = Form(...),
    name: str = Form(...),
    price: str = Form(""),
    highlights: str = Form(""),
    affiliate_link: str = Form(""),
    images: list[UploadFile] = File(...),
):
    if platform not in PLATFORMS:
        raise HTTPException(400, "แพลตฟอร์มต้องเป็น shopee หรือ tiktok_shop")
    if not images or not images[0].filename:
        raise HTTPException(400, "ต้องอัปโหลดรูปสินค้าอย่างน้อย 1 รูป")

    saved = []
    for f in images:
        if f.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(400, f"ไฟล์ {f.filename} ไม่ใช่รูป JPG/PNG/WEBP")
        ext = Path(f.filename).suffix.lower() or ".jpg"
        dest = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        saved.append(str(dest))

    pid = db.create_product(platform, name.strip(), price.strip(), highlights.strip(),
                            affiliate_link.strip(), saved)
    return to_public(db.get_product(pid))


@app.post("/api/products/{pid}/generate")
def generate(pid: int, background: BackgroundTasks):
    """ให้ AI คิดคอนเทนต์ใหม่ทั้งหมด แล้วทำเสียง + วิดีโอ"""
    if not db.get_product(pid):
        raise HTTPException(404, "ไม่พบสินค้า")
    db.update_product(pid, status="processing", error=None)
    background.add_task(run_pipeline, pid, True)
    return {"ok": True}


class ContentEdit(BaseModel):
    hook: str
    voice_script: str
    caption_facebook: str
    caption_tiktok: str
    hashtags: list[str]


@app.put("/api/products/{pid}/content")
def save_content(pid: int, body: ContentEdit, background: BackgroundTasks):
    """บันทึกคอนเทนต์ที่แก้เอง แล้วทำเสียง + วิดีโอใหม่ (ไม่เรียก AI)"""
    if not db.get_product(pid):
        raise HTTPException(404, "ไม่พบสินค้า")
    db.update_product(pid, content=body.model_dump(), status="processing", error=None)
    background.add_task(run_pipeline, pid, False)
    return {"ok": True}


@app.delete("/api/products/{pid}")
def delete_product(pid: int):
    p = db.get_product(pid)
    if not p:
        raise HTTPException(404, "ไม่พบสินค้า")
    for img in p["images"]:
        Path(img).unlink(missing_ok=True)
    shutil.rmtree(OUTPUT_DIR / str(pid), ignore_errors=True)
    db.delete_product(pid)
    return {"ok": True}
