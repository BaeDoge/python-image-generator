"""상품 분석 -> 컨셉/스타일/스토리보드 자율 기획 -> 규칙+사실 검증 루프.
사용자가 상품명·프롬프트·스타일을 .env 에 적을 필요가 없다."""
from __future__ import annotations

from . import llm, styles, verify
from .config import get
from .coupang import Product

DEFAULT_PERSONA = "생활·가전·취미용품 정보를 정리해서 공유하는 30대 직장인 계정. 담백하고 친근한 구어체"
RISKY = {"medical", "health_claim", "adult", "child_safety"}


class SkipProduct(Exception):
    """광고 규제/안전 이슈 등으로 자동 게시에 부적합한 상품."""


ANALYZE_SYSTEM = "당신은 이커머스 상품을 분석하는 기획자입니다. 상품명에 적힌 정보만 근거로 삼고 출력은 JSON 한 개만."
ANALYZE_USER = """상품 데이터:
- 상품명: {name}
- 카테고리: {category}
- 가격: {price}원
- 로켓배송: {rocket} / 무료배송: {free_ship}

JSON 으로만 답하세요.
{{
  "product_type": "상품 종류 한 줄 (한글)",
  "explicit_facts": ["상품명에 '명시된' 사실만 (한글, 없으면 빈 배열)"],
  "typical_situations": ["이 종류의 상품이 일반적으로 필요해지는 일상 상황 3~4개 (한글, 각 20자 이내)"],
  "visual_motifs": ["그 상황에 흔히 등장하는 장소·사물 영어 단어 4~6개 (예: sofa, floor, kitchen counter). 상품과 직접 관련된 것만"],
  "mood": "cozy | fresh | playful | calm | energetic 중 하나",
  "risk_flags": ["medical | health_claim | adult | child_safety 중 해당되는 것만, 없으면 빈 배열"]
}}"""

PLAN_SYSTEM = """당신은 쇼핑 정보를 '공감되는 짧은 만화 스토리'로 풀어 Threads 캐러셀(6장)로 만드는 콘텐츠 디렉터입니다.
계정 성격: {persona}

게시물 구조: 1) 표지(제목+상황 부제) 2) 불편이 심해지는 순간 3) 해결책을 찾아보는 장면 4) 상품 등장 5) 이런 분께 6) 구매 안내
1~3장은 가상의 '연출 상황' 만화입니다. 실제 경험담이 아닙니다.

반드시 지킬 규칙:
- 상품 설명은 상품 데이터와 분석 결과의 explicit_facts 에 있는 사실만 씁니다. 스펙·효능·수치·비교우위를 지어내지 않습니다.
- '직접 써봤다/샀다/후기/내돈내산' 금지. 실존 인물·연예인·유명인 언급 금지. '최고, 1위, 무조건, 100%, 완벽' 같은 과장 금지.
- 모든 한국어 문장은 순수 한글(+숫자, 기본 문장부호)로만 씁니다. 한자·일본어·영어 단어를 섞지 않습니다.
- 캡션은 서로 다른 내용으로 이야기가 이어지게(상황 → 심화 → 탐색) 쓰고, 같은 단어를 반복하지 않습니다.
- scene 은 영어로 25단어 이내. visual_motifs 에 없는 새로운 장소·사물(예: 상품과 무관한 물건)을 추가하지 않습니다. 한 장면에 초점은 하나, 소품은 3개 이하, 사람은 뒷모습/실루엣/손만. 글자·브랜드·로고 묘사 금지.
  각 panel 의 scene 에는 분석 결과 visual_motifs 중 최소 1개를 반드시 포함하세요. 상품 자체는 그리지 않습니다(상품 사진은 별도로 합성됨).
- 말투는 자연스러운 구어체, 이모지·해시태그·링크·광고 문구는 쓰지 않습니다(코드가 따로 붙임).
- 출력은 JSON 한 개만."""

PLAN_USER = """상품 데이터: {name} / {price}원 / 카테고리 {category} / 로켓배송 {rocket} / 무료배송 {free_ship}

상품 분석:
{analysis}

사용할 수 있는 style_id:
{style_menu}

이 상품에 가장 어울리는 '컨셉'(공감 포인트, 말투, 그림 스타일)을 스스로 정하고, 아래 JSON 으로 답하세요.
{{
  "concept": {{"angle": "이 게시물이 잡는 공감 포인트 한 줄", "tone": "말투 한 줄", "style_id": "위 목록 중 하나"}},
  "hook": "1장 표지 제목 (한글 22자 이내, 공감/궁금증 유도, 가격·최상급 금지)",
  "panels": [
    {{"caption": "1장 하단 부제: 상황 제시 (한글 32자 이내)", "scene": "영어 장면 묘사"}},
    {{"caption": "2장: 불편이 심해지는 순간 (한글 32자 이내)", "scene": "영어 장면 묘사"}},
    {{"caption": "3장: 해결책을 찾아보는 장면 (한글 32자 이내)", "scene": "영어 장면 묘사"}}
  ],
  "backdrop": "4장 상품 배경용 영어 묘사: 이 상품이 쓰일 장소의 깔끔하게 비워진 배경, 중앙에 아무 물건도 없음 (25단어 이내)",
  "reveal": "4장 상품 등장 멘트 (한글 22자 이내)",
  "for_whom": ["5장 '이런 분께' 3개, 상황/니즈 기준 (각 한글 20자 이내)", "...", "..."],
  "cta": "6장 구매 안내 문구 (한글 22자 이내)",
  "body": "Threads 본문 (한글 {min_len}~{max_len}자, 2~4문장)"
}}"""


def _fmt(product: Product) -> dict:
    return dict(
        name=product.name, price=f"{product.price:,}", category=product.category or "미상",
        rocket="예" if product.rocket else "아니오", free_ship="예" if product.free_ship else "아니오",
    )


def analyze(product: Product) -> dict:
    d = llm.chat_json(
        [{"role": "system", "content": ANALYZE_SYSTEM}, {"role": "user", "content": ANALYZE_USER.format(**_fmt(product))}],
        max_tokens=900, temperature=0.3,
    )
    d["visual_motifs"] = [str(m).strip().lower() for m in d.get("visual_motifs", []) if str(m).strip().isascii()]
    if not d["visual_motifs"]:
        raise RuntimeError("상품 분석에서 visual_motifs 를 얻지 못했습니다")
    flags = {str(f).strip() for f in d.get("risk_flags", [])}
    if flags & RISKY:
        raise SkipProduct(f"위험 플래그 {sorted(flags & RISKY)}: {product.name}")
    return d


def build_story(product: Product, link: str, max_tries: int = 4) -> tuple[dict, dict, dict]:
    """반환: (story, analysis, report). story['text'] 는 Threads 최종 본문."""
    analysis = analyze(product)
    print(f"  분석: {analysis.get('product_type')} / 소재 {analysis['visual_motifs']} / 분위기 {analysis.get('mood')}")

    tail = f"\n\n{link}\n\n{verify.DISCLOSURE}"
    max_len = min(verify.THREADS_MAX - len(tail) - 5, 220)
    min_len = 70
    if max_len < min_len + 20:
        raise RuntimeError("링크가 너무 길어 본문 공간이 부족합니다. 딥링크 단축을 확인하세요.")

    import json

    messages = [
        {"role": "system", "content": PLAN_SYSTEM.format(persona=get("PERSONA", DEFAULT_PERSONA))},
        {"role": "user", "content": PLAN_USER.format(
            **_fmt(product), analysis=json.dumps(analysis, ensure_ascii=False),
            style_menu=styles.menu(), min_len=min_len, max_len=max_len)},
    ]
    attempts: list[dict] = []
    last = ""
    for n in range(1, max_tries + 1):
        raw_story = llm.chat_json(messages, temperature=0.8)
        problems = verify.check_story(raw_story, analysis, min_len, max_len)
        if not problems:
            try:
                problems = verify.fact_check(raw_story, product, analysis)
            except Exception as e:  # noqa: BLE001
                print(f"[verify] 사실/장면 검수 호출 실패(건너뜀): {e}")
        attempts.append({"try": n, "problems": problems})
        if not problems:
            story = {
                "concept": raw_story["concept"],
                "hook": raw_story["hook"].strip(),
                "panels": [{"caption": p["caption"].strip(), "scene": p["scene"].strip()} for p in raw_story["panels"]],
                "backdrop": raw_story["backdrop"].strip(),
                "reveal": raw_story["reveal"].strip(),
                "for_whom": [t.strip() for t in raw_story["for_whom"]],
                "cta": raw_story["cta"].strip(),
                "body": raw_story["body"].strip(),
            }
            story["text"] = story["body"] + tail
            assert len(story["text"]) <= verify.THREADS_MAX
            return story, analysis, {"attempts": attempts, "fact_check": "ok"}
        last = "; ".join(problems)
        print(f"[plan] 시도 {n}/{max_tries} 반려: {last}")
        messages += [
            {"role": "assistant", "content": json.dumps(raw_story, ensure_ascii=False)},
            {"role": "user", "content": f"다음 문제를 모두 고쳐서 JSON 만 다시 출력하세요: {last}"},
        ]
    raise RuntimeError(f"스토리 기획 검증 실패: {last}")


def simplify_scene(scene: str, motifs: list[str]) -> str:
    """이미지 검증에 계속 탈락할 때 쓰는 단순화 장면 (소재 1~2개만)."""
    return f"a simple minimal {' and '.join(motifs[:2])} scene, soft light, tidy, empty center"
