"""Threads API 는 '공개 URL' 의 이미지만 받으므로, 생성한 이미지를 어딘가에 올려 URL 을 얻는다."""
from __future__ import annotations

import base64
import hashlib
import time
from pathlib import Path

import requests

from .config import get, need


def upload(path: Path) -> str:
    provider = (get("IMAGE_HOST", "cloudinary") or "").lower()
    if provider == "cloudinary":
        return _cloudinary(path)
    if provider == "github":
        return _github(path)
    raise RuntimeError(f"지원하지 않는 IMAGE_HOST: {provider}")


def _cloudinary(path: Path) -> str:
    cloud, key, secret = need("CLOUDINARY_CLOUD_NAME"), need("CLOUDINARY_API_KEY"), need("CLOUDINARY_API_SECRET")
    ts = str(int(time.time()))
    public_id = f"threads-bot/{path.stem}"
    to_sign = f"public_id={public_id}&timestamp={ts}{secret}"
    sig = hashlib.sha1(to_sign.encode()).hexdigest()
    with open(path, "rb") as f:
        r = requests.post(
            f"https://api.cloudinary.com/v1_1/{cloud}/image/upload",
            data={"api_key": key, "timestamp": ts, "public_id": public_id, "signature": sig},
            files={"file": f},
            timeout=120,
        )
    j = r.json()
    if r.status_code != 200 or "secure_url" not in j:
        raise RuntimeError(f"Cloudinary 업로드 실패 {r.status_code}: {j}")
    return j["secure_url"]


def _github(path: Path) -> str:
    token, repo = need("GITHUB_TOKEN"), need("GITHUB_REPO")
    branch = get("GITHUB_BRANCH", "main")
    remote = f"threads-bot/{path.name}"
    r = requests.put(
        f"https://api.github.com/repos/{repo}/contents/{remote}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json={
            "message": f"add {path.name}",
            "content": base64.b64encode(path.read_bytes()).decode(),
            "branch": branch,
        },
        timeout=120,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"GitHub 업로드 실패 {r.status_code}: {r.text[:300]}")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{remote}"
