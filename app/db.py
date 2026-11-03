"""เก็บข้อมูลสินค้าและคอนเทนต์ที่สร้างไว้ใน SQLite"""
import json
import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "affiliate.db"


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,          -- shopee | tiktok_shop
                name TEXT NOT NULL,
                price TEXT,
                highlights TEXT,
                affiliate_link TEXT,
                images TEXT NOT NULL,            -- JSON list ของ path รูป
                status TEXT NOT NULL DEFAULT 'new',  -- new | processing | done | error
                error TEXT,
                content TEXT,                    -- JSON ผลลัพธ์จาก Claude
                audio_path TEXT,
                video_path TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    d["images"] = json.loads(d["images"])
    d["content"] = json.loads(d["content"]) if d["content"] else None
    return d


def create_product(platform, name, price, highlights, affiliate_link, images) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO products (platform, name, price, highlights, affiliate_link, images)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (platform, name, price, highlights, affiliate_link, json.dumps(images)),
        )
        return cur.lastrowid


def get_product(pid: int) -> dict | None:
    with connect() as conn:
        return _row(conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone())


def list_products() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
        return [_row(r) for r in rows]


def update_product(pid: int, **fields) -> None:
    if "content" in fields and fields["content"] is not None:
        fields["content"] = json.dumps(fields["content"], ensure_ascii=False)
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE products SET {cols} WHERE id = ?", (*fields.values(), pid))


def delete_product(pid: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM products WHERE id = ?", (pid,))
