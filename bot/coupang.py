"""쿠팡 파트너스 오픈 API (HMAC-SHA256 인증)."""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import requests

from .config import get, need

DOMAIN = "https://api-gateway.coupang.com"
# 문서 버전에 따라 경로에 /v1 이 붙기도 하고 안 붙기도 해서 둘 다 시도한다.
_PREFIXES = [
    "/v2/providers/affiliate_open_api/apis/openapi/v1",
    "/v2/providers/affiliate_open_api/apis/openapi",
]
_prefix_cache: str | None = None


@dataclass
class Product:
    id: str
    name: str
    price: int
    image: str
    url: str  # 파트너스 추적 코드가 붙은 링크
    rocket: bool
    free_ship: bool
    category: str

    @classmethod
    def from_api(cls, d: dict) -> "Product":
        return cls(
            id=str(d.get("productId", "")),
            name=str(d.get("productName", "")).strip(),
            price=int(float(d.get("productPrice") or 0)),
            image=str(d.get("productImage", "")),
            url=str(d.get("productUrl", "")),
            rocket=bool(d.get("isRocket")),
            free_ship=bool(d.get("isFreeShipping")),
            category=str(d.get("categoryName", "")),
        )


def _auth(method: str, path: str, query: str) -> str:
    now = time.gmtime()
    signed = time.strftime("%y%m%d", now) + "T" + time.strftime("%H%M%S", now) + "Z"
    message = signed + method + path + query  # query 는 '?' 제외
    sig = hmac.new(need("COUPANG_SECRET_KEY").encode(), message.encode(), hashlib.sha256).hexdigest()
    return (
        f"CEA algorithm=HmacSHA256, access-key={need('COUPANG_ACCESS_KEY')}, "
        f"signed-date={signed}, signature={sig}"
    )


def _call(method: str, endpoint: str, params: dict | None = None, body: dict | None = None):
    global _prefix_cache
    prefixes = [_prefix_cache] if _prefix_cache else _PREFIXES
    last_text = ""
    for prefix in prefixes:
        path = prefix + endpoint
        query = urlencode(params) if params else ""
        url = DOMAIN + path + (f"?{query}" if query else "")
        headers = {
            "Authorization": _auth(method, path, query),
            "Content-Type": "application/json;charset=UTF-8",
        }
        r = requests.request(method, url, headers=headers, json=body, timeout=30)
        if r.status_code == 404 and len(prefixes) > 1:
            last_text = r.text[:200]
            continue
        try:
            j = r.json()
        except ValueError:
            raise RuntimeError(f"쿠팡 API 응답 파싱 실패 {r.status_code}: {r.text[:200]}")
        if r.status_code != 200 or str(j.get("rCode")) != "0":
            raise RuntimeError(f"쿠팡 API 오류 {r.status_code}: {j}")
        _prefix_cache = prefix
        return j.get("data")
    raise RuntimeError(f"쿠팡 API 경로를 찾지 못했습니다(404). 공식 문서의 최신 경로를 확인하세요. {last_text}")


def _to_products(data) -> list[Product]:
    items = data.get("productData", []) if isinstance(data, dict) else (data or [])
    return [Product.from_api(d) for d in items]


def _params(**kw) -> dict:
    p = {k: v for k, v in kw.items() if v not in (None, "")}
    sub = get("COUPANG_SUB_ID")
    if sub:
        p["subId"] = sub
    return p


def search_products(keyword: str, limit: int = 10) -> list[Product]:
    return _to_products(_call("GET", "/products/search", _params(keyword=keyword, limit=limit)))


def best_products(category_id: str, limit: int = 20) -> list[Product]:
    return _to_products(_call("GET", f"/products/bestcategories/{category_id}", _params(limit=limit)))


def shorten(url: str) -> str:
    """딥링크 API로 단축 링크 생성. 실패하면 원래 링크를 그대로 쓴다."""
    try:
        data = _call("POST", "/deeplink", body={"coupangUrls": [url]})
        if data and data[0].get("shortenUrl"):
            return data[0]["shortenUrl"]
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 딥링크 단축 실패, 원본 링크 사용: {e}")
    return url
