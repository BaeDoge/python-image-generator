"""그림 스타일 라이브러리. 플래너(LLM)가 상품 분위기에 맞춰 style_id 를 고르고, 프롬프트는 코드가 조립한다.
(사용자가 .env 에 프롬프트를 적을 필요 없음)"""
from __future__ import annotations

import hashlib

GLOBAL_POS = (
    "bright airy lighting, high key, clean simple composition, one clear focal point, "
    "centered subject, large calm empty space at the top, no visible faces"
)
GLOBAL_NEG = (
    "text, letters, words, numbers, watermark, logo, signature, brand name, photo, photorealistic, "
    "dark, murky, muted dull colors, grainy, noisy, messy, cluttered, busy background, "
    "face close-up, deformed, extra limbs, extra fingers, blurry, low quality, cropped, celebrity"
)

STYLES: dict[str, dict[str, str]] = {
    "flat_pastel": {
        "label": "밝고 단순한 플랫 파스텔 일러스트 (생활용품·가전·정리 소재에 무난)",
        "pos": "flat vector illustration, soft pastel colors, rounded simple shapes",
        "neg": "3d render",
    },
    "paper_cut": {
        "label": "종이 오브제를 겹친 종이공예 스타일 (주방·홈인테리어·계절감)",
        "pos": "layered paper cut art, soft drop shadows, cheerful colors, handcrafted look",
        "neg": "3d render",
    },
    "isometric_room": {
        "label": "아이소메트릭 방 단면 일러스트 (가전·수납·인테리어)",
        "pos": "isometric cutaway room illustration, tidy, soft colors, clean lines",
        "neg": "",
    },
    "watercolor_soft": {
        "label": "부드러운 수채화 (감성적·여유로운 분위기)",
        "pos": "soft watercolor illustration, gentle gradients, plenty of white space",
        "neg": "3d render, harsh lines",
    },
    "retro_pop": {
        "label": "레트로 팝 플랫 일러스트 (스포츠·취미·활동적인 소재)",
        "pos": "retro pop flat illustration, bold simple shapes, warm saturated colors",
        "neg": "3d render",
    },
    "clay_3d": {
        "label": "말랑한 클레이 3D 스타일 (귀엽고 장난스러운 소재)",
        "pos": "cute soft clay 3d render, pastel colors, soft studio lighting, minimal",
        "neg": "flat, line art",
    },
}


def fallback_style(seed_text: str) -> str:
    ids = sorted(STYLES)
    return ids[int(hashlib.md5(seed_text.encode()).hexdigest(), 16) % len(ids)]


def build(style_id: str, scene: str) -> dict[str, str]:
    st = STYLES.get(style_id) or STYLES["flat_pastel"]
    neg = ", ".join(x for x in (GLOBAL_NEG, st["neg"]) if x)
    return {"prompt": f"{scene}, {st['pos']}, {GLOBAL_POS}", "negative": neg, "scene": scene}


def menu() -> str:
    return "\n".join(f'  - {k}: {v["label"]}' for k, v in STYLES.items())
