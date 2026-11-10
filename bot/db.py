"""이미 게시한 상품을 기록해 중복 게시를 막는다."""
from __future__ import annotations

import sqlite3
from datetime import datetime

from .config import DATA_DIR

_DB = DATA_DIR / "posted.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB)
    c.execute(
        "CREATE TABLE IF NOT EXISTS posted ("
        "product_id TEXT PRIMARY KEY, name TEXT, posted_at TEXT, threads_id TEXT)"
    )
    return c


def is_posted(product_id: str) -> bool:
    with _conn() as c:
        return c.execute("SELECT 1 FROM posted WHERE product_id=?", (product_id,)).fetchone() is not None


def mark_posted(product_id: str, name: str, threads_id: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO posted VALUES (?,?,?,?)",
            (product_id, name, datetime.now().isoformat(timespec="seconds"), threads_id),
        )
