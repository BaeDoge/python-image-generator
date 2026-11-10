"""Threads Graph API: 컨테이너 생성 -> 처리 대기 -> 게시. (이미지는 공개 URL 필요, 본문 500자 제한)"""
from __future__ import annotations

import time

import requests

from .config import get, need

BASE = "https://graph.threads.net/v1.0"


def _check(r: requests.Response) -> dict:
    try:
        j = r.json()
    except ValueError:
        j = {"raw": r.text[:300]}
    if r.status_code >= 400 or "error" in j:
        raise RuntimeError(f"Threads API 오류 {r.status_code}: {j}")
    return j


def whoami() -> dict:
    r = requests.get(f"{BASE}/me", params={"fields": "id,username", "access_token": need("THREADS_ACCESS_TOKEN")}, timeout=30)
    return _check(r)


def _wait_ready(container_id: str, token: str, timeout_s: int = 90, first_wait: float = 5) -> None:
    deadline = time.time() + timeout_s
    time.sleep(first_wait)
    while time.time() < deadline:
        try:
            j = _check(requests.get(
                f"{BASE}/{container_id}",
                params={"fields": "status,error_message", "access_token": token},
                timeout=30,
            ))
        except Exception as e:  # noqa: BLE001  상태 조회가 안 되면 문서 권장대로 잠시 대기 후 진행
            print(f"[threads] 상태 조회 실패({e}) -> 30초 대기 후 게시 시도")
            time.sleep(30)
            return
        status = j.get("status")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"컨테이너 처리 실패: {j}")
        time.sleep(5)
    raise RuntimeError("컨테이너 처리 대기 시간 초과")


def post_image(image_url: str, text: str, alt_text: str | None = None) -> str:
    token = need("THREADS_ACCESS_TOKEN")
    uid = get("THREADS_USER_ID", "me")
    data = {"media_type": "IMAGE", "image_url": image_url, "text": text, "access_token": token}
    if alt_text:
        data["alt_text"] = alt_text[:1000]
    cid = _check(requests.post(f"{BASE}/{uid}/threads", data=data, timeout=60))["id"]
    _wait_ready(cid, token)
    pid = _check(requests.post(
        f"{BASE}/{uid}/threads_publish", data={"creation_id": cid, "access_token": token}, timeout=60
    ))["id"]
    return pid


def post_carousel(image_urls: list[str], text: str) -> str:
    """이미지 2~20장 캐러셀. 항목 컨테이너 생성 -> 캐러셀 컨테이너 생성 -> 게시."""
    if not 2 <= len(image_urls) <= 20:
        raise ValueError("캐러셀은 이미지 2~20장이어야 합니다")
    token = need("THREADS_ACCESS_TOKEN")
    uid = get("THREADS_USER_ID", "me")
    item_ids = []
    for url in image_urls:
        data = {"media_type": "IMAGE", "image_url": url, "is_carousel_item": "true", "access_token": token}
        item_ids.append(_check(requests.post(f"{BASE}/{uid}/threads", data=data, timeout=60))["id"])
    for iid in item_ids:
        _wait_ready(iid, token, first_wait=1)
    cdata = {"media_type": "CAROUSEL", "children": ",".join(item_ids), "text": text, "access_token": token}
    cid = _check(requests.post(f"{BASE}/{uid}/threads", data=cdata, timeout=60))["id"]
    _wait_ready(cid, token)
    return _check(requests.post(
        f"{BASE}/{uid}/threads_publish", data={"creation_id": cid, "access_token": token}, timeout=60
    ))["id"]


def permalink(post_id: str) -> str | None:
    try:
        j = _check(requests.get(
            f"{BASE}/{post_id}", params={"fields": "permalink", "access_token": need("THREADS_ACCESS_TOKEN")}, timeout=30
        ))
        return j.get("permalink")
    except Exception:  # noqa: BLE001
        return None


def refresh_token() -> dict:
    """장기 토큰(60일)을 갱신. 발급 24시간 이후 + 만료 전에만 가능."""
    r = requests.get(
        "https://graph.threads.net/refresh_access_token",
        params={"grant_type": "th_refresh_token", "access_token": need("THREADS_ACCESS_TOKEN")},
        timeout=30,
    )
    return _check(r)
