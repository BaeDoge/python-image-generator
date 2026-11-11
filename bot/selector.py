"""사람이 키워드를 정하지 않아도 되는 자동 상품 선택(autopilot).
날짜 기반으로 안전한 카테고리를 돌아가며 베스트 상품 중 게시할 만한 것을 고른다."""
from __future__ import annotations

import random
import re
from datetime import date

from . import coupang, db
from .coupang import Product

# 쿠팡 파트너스 베스트 카테고리 ID. 실제 ID 는 API 응답으로 검증해 쓰세요 (안 맞으면 건너뜀).
SAFE_CATEGORIES: dict[str, str] = {
    "1013": "주방용품", "1014": "생활용품", "1015": "홈인테리어", "1016": "가전디지털",
    "1017": "스포츠/레저", "1018": "자동차용품", "1020": "완구/취미", "1021": "문구/오피스", "1029": "반려동물용품",
}

# 효능/의료/안전/성인 관련 광고 규제가 있어 자동 생성 문구로는 위험한 상품
BLOCK = re.compile(
    "건강기능|영양제|비타민|유산균|다이어트|의약|약국|콘돔|성인|담배|술|와인|맥주|소주|위스키|마스크팩|화장품|세럼|앰플|"
    "임산부|분유|이유식|안마|의료|보청기|렌즈|혈압|혈당|탈모|관절|치료|살균제|농약"
)


def is_blocked(name: str) -> bool:
    return bool(BLOCK.search(name))


def score(p: Product) -> float:
    s = 0.0
    s += 2 if p.rocket else 0
    s += 1 if p.free_ship else 0
    if 8_000 <= p.price <= 150_000:
        s += 2
    elif p.price < 3_000:
        s -= 2
    if 8 <= len(p.name) <= 60:
        s += 1
    return s


def rank(items: list[Product], limit: int = 8) -> list[Product]:
    ok = [p for p in items if p.image and p.url and p.id and not is_blocked(p.name) and not db.is_posted(p.id)]
    ok.sort(key=lambda p: score(p) + random.random(), reverse=True)
    return ok[:limit]


def candidates(keyword: str | None = None, category: str | None = None) -> list[Product]:
    if keyword:
        return rank(coupang.search_products(keyword, limit=20))
    if category:
        return rank(coupang.best_products(category, limit=20))
    ids = list(SAFE_CATEGORIES)
    start = date.today().toordinal() % len(ids)
    for cid in ids[start:] + ids[:start]:
        try:
            ranked = rank(coupang.best_products(cid, limit=20))
        except Exception as e:  # noqa: BLE001
            print(f"[select] 카테고리 {cid}({SAFE_CATEGORIES[cid]}) 조회 실패, 다음으로: {e}")
            continue
        if ranked:
            print(f"[select] 오늘의 카테고리: {cid} {SAFE_CATEGORIES[cid]}")
            return ranked
    raise SystemExit("게시할 수 있는 상품을 찾지 못했습니다 (모든 카테고리 실패/전부 게시 이력/차단 상품).")
