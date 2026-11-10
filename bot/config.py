from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

OUT_DIR = ROOT / "out"
DATA_DIR = ROOT / "data"
OUT_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)


def get(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    return v if v not in (None, "") else default


def need(name: str) -> str:
    v = get(name)
    if not v:
        raise RuntimeError(f"환경변수 {name} 가 비어 있습니다. .env 를 확인하세요.")
    return v


def flag(name: str, default: bool = False) -> bool:
    v = get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")
