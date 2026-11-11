"""상품 분석 -> 컨셉/스타일/스토리보드 자율 기획 -> 규칙+사실 검증 루프.
사용자가 상품명·프롬프트·스타일을 .env 에 적을 필요가 없다."""
from __future__ import annotations

import copy
import json
import re

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
  각 panel 의 scene 에는 분석 결과 visual_motifs 중 최소 1개를 반드시 포함하되, scene 에는 'visual motif:' 같은 설명 문구를 쓰지 말고 장면 자체만 묘사하세요. 상품 자체는 그리지 않습니다(상품 사진은 별도로 합성됨).
- 말투는 사람이 쓴 듯한 구어체(해요체 또는 반말)입니다. '~합니다/~드립니다/~소개합니다/~시작하세요' 같은 광고체·문어체 종결은 쓰지 않습니다.
- 상품의 장점은 상품명에 적힌 표현만 씁니다. '가볍다, 편리하다, 강력하다, 오래 쓴다, 수월하다' 같은 장점은 상품명에 없으면 쓰지 말고,
  대신 '이런 상황에서 필요할 수 있다', '이런 구성이다(상품명 그대로)'까지만 말합니다.
- 이모지·해시태그·링크·광고 문구는 쓰지 않습니다(코드가 따로 붙임).
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


REPAIR_SYSTEM = "당신은 한국어 카피 교정자입니다. 지시된 문제만 고치고 의미와 분량은 최대한 유지합니다. 출력은 JSON 한 개만."
REPAIR_USER = """상품명: {name}

교정할 항목:
{items}

교정 규칙:
- 한국어 문장은 해요체 또는 반말 구어체(~해요, ~거든요, ~더라, ~야)로 씁니다. '~합니다/~입니다/~습니다/~드립니다' 금지.
- 상품명에 없는 장점(가볍다, 오래 쓴다, 편리하다, 강력하다, 수월하다 등)과 숫자는 삭제하거나 '이런 상황에서 필요하다' 식의 상황 묘사로 바꿉니다.
- 한자·영어·외국 문자를 섞지 않습니다 (단, scene 항목은 영어만 씁니다).
- scene 항목은 영어 25단어 이내로 장면 자체만 묘사합니다. 'visual motif' 같은 설명 문구와 콜론은 쓰지 않습니다. 허용 소재: {motifs}
- 글자 수: {limits}
항목 이름은 위에 적힌 그대로 사용해 아래 JSON 으로만 답하세요.
{{"fixes": {{"항목이름": "고친 문장"}}}}"""

_FIELD_RE = re.compile(r"^(hook|reveal|cta|body|backdrop|panels\[\d\]\.(?:caption|scene)|for_whom\[\d\]) ")
_QUOTED = re.compile(r"'(.+?)' ->")


def _get(story: dict, key: str):
    m = re.fullmatch(r"panels\[(\d)\]\.(caption|scene)", key)
    if m:
        return story["panels"][int(m[1]) - 1][m[2]]
    m = re.fullmatch(r"for_whom\[(\d)\]", key)
    if m:
        return story["for_whom"][int(m[1]) - 1]
    return story[key]


def _set(story: dict, key: str, val: str) -> None:
    m = re.fullmatch(r"panels\[(\d)\]\.(caption|scene)", key)
    if m:
        story["panels"][int(m[1]) - 1][m[2]] = val
        return
    m = re.fullmatch(r"for_whom\[(\d)\]", key)
    if m:
        story["for_whom"][int(m[1]) - 1] = val
        return
    story[key] = val


def _keys(story: dict) -> list[str]:
    ks = ["hook", "reveal", "cta", "body", "backdrop"]
    ks += [f"panels[{i}].{f}" for i, _ in enumerate(story.get("panels") or [], 1) for f in ("caption", "scene")]
    ks += [f"for_whom[{i}]" for i, _ in enumerate(story.get("for_whom") or [], 1)]
    return ks


def _field_of(problem: str, story: dict) -> str | None:
    m = _FIELD_RE.match(problem)
    if m:
        return m.group(1)
    q = _QUOTED.search(problem)  # LLM 검수 결과: 문제 문구가 어느 필드에 들어 있는지 찾는다
    if q:
        claim = q.group(1).strip()
        for key in _keys(story):
            try:
                val = str(_get(story, key))
            except (KeyError, IndexError, TypeError):
                continue
            if claim and len(val) >= 4 and (claim in val or val in claim):
                return key
    return None


def _group(problems: list[str], story: dict) -> dict[str, list[str]] | None:
    """모든 문제가 특정 필드에 대응되면 {필드: [문제...]}, 구조 문제가 섞여 있으면 None(전체 재생성)."""
    out: dict[str, list[str]] = {}
    for pr in problems:
        key = _field_of(pr, story)
        if key is None:
            return None
        out.setdefault(key, []).append(pr)
    return out


def _soften_all(raw: dict) -> dict:
    try:
        for k in ("hook", "reveal", "cta", "body"):
            if isinstance(raw.get(k), str):
                raw[k] = verify.soften_endings(raw[k])
        for p in raw.get("panels") or []:
            if isinstance(p, dict) and isinstance(p.get("caption"), str):
                p["caption"] = verify.soften_endings(p["caption"])
    except Exception:  # noqa: BLE001
        pass
    return raw


def repair(story: dict, by_field: dict[str, list[str]], product: Product, analysis: dict, min_len: int, max_len: int) -> dict:
    """문제가 있는 필드만 LLM 에게 맡겨 고친다 (전체 JSON 재생성보다 로컬 모델에서 훨씬 안정적)."""
    items = "\n".join(f'- {k} | 현재: "{_get(story, k)}" | 문제: {"; ".join(ps)}' for k, ps in by_field.items())
    limits = f"hook·reveal 22자, cta 28자, caption 32자, for_whom 20자, body {min_len}~{max_len}자"
    d = llm.chat_json(
        [{"role": "system", "content": REPAIR_SYSTEM},
         {"role": "user", "content": REPAIR_USER.format(name=product.name, items=items, limits=limits,
                                                        motifs=", ".join(analysis.get("visual_motifs", [])))}],
        max_tokens=1200, temperature=0.3,
    )
    new = copy.deepcopy(story)
    for k, v in (d.get("fixes") or {}).items():
        if k in by_field and isinstance(v, str) and v.strip():
            _set(new, k, v.strip())
    return _soften_all(new)


def _evaluate(raw: dict, analysis: dict, product: Product, min_len: int, max_len: int, state: dict) -> tuple[dict, list[str]]:
    """확정 규칙(필수) -> LLM 검수(2회까지) 순서로 평가. 반환: (순화된 story, 문제 목록)"""
    raw = _soften_all(raw)
    hard = verify.check_story(raw, analysis, min_len, max_len, product.name, product.price)
    if hard:
        return raw, hard
    if state["soft_left"] > 0:
        try:
            soft = verify.fact_check(raw, product, analysis)
        except Exception as e:  # noqa: BLE001
            print(f"[verify] 사실/장면 검수 호출 실패(건너뜀): {e}")
            soft = []
        state["last_soft"] = soft
        if soft:
            state["soft_left"] -= 1
            return raw, soft
    return raw, []


def build_story(product: Product, link: str, max_tries: int = 6) -> tuple[dict, dict, dict]:
    """반환: (story, analysis, report). story['text'] 는 Threads 최종 본문.
    생성 -> 평가 -> (필드 단위 교정 최대 2회) -> 구조 문제일 때만 전체 재생성."""
    analysis = analyze(product)
    print(f"  분석: {analysis.get('product_type')} / 소재 {analysis['visual_motifs']} / 분위기 {analysis.get('mood')}")

    tail = f"\n\n{link}\n\n{verify.DISCLOSURE}"
    max_len = min(verify.THREADS_MAX - len(tail) - 5, 220)
    min_len = 70
    if max_len < min_len + 20:
        raise RuntimeError("링크가 너무 길어 본문 공간이 부족합니다. 딥링크 단축을 확인하세요.")

    messages = [
        {"role": "system", "content": PLAN_SYSTEM.format(persona=get("PERSONA", DEFAULT_PERSONA))},
        {"role": "user", "content": PLAN_USER.format(
            **_fmt(product), analysis=json.dumps(analysis, ensure_ascii=False),
            style_menu=styles.menu(), min_len=min_len, max_len=max_len)},
    ]
    attempts: list[dict] = []
    state = {"soft_left": 2, "last_soft": []}
    last = ""
    for n in range(1, max_tries + 1):
        raw = llm.chat_json(messages, temperature=0.8)
        repairs = 0
        while True:
            raw, problems = _evaluate(raw, analysis, product, min_len, max_len, state)
            if not problems:
                break
            by_field = _group(problems, raw) if repairs < 2 else None
            if by_field is None:
                break
            repairs += 1
            print(f"[repair] 시도 {n} 교정 {repairs}회: {', '.join(by_field)}")
            try:
                raw = repair(raw, by_field, product, analysis, min_len, max_len)
            except Exception as e:  # noqa: BLE001
                print(f"[repair] 교정 호출 실패: {e}")
                break
        attempts.append({"try": n, "repairs": repairs, "problems": problems})
        if not problems:
            story = {
                "concept": raw["concept"],
                "hook": raw["hook"].strip(),
                "panels": [{"caption": p["caption"].strip(), "scene": p["scene"].strip()} for p in raw["panels"]],
                "backdrop": raw["backdrop"].strip(),
                "reveal": raw["reveal"].strip(),
                "for_whom": [t.strip() for t in raw["for_whom"]],
                "cta": raw["cta"].strip(),
                "body": raw["body"].strip(),
            }
            story["text"] = story["body"] + tail
            assert len(story["text"]) <= verify.THREADS_MAX
            warn = state["last_soft"]
            return story, analysis, {"attempts": attempts, "fact_check": "warnings" if warn else "ok", "warnings": warn}
        last = "; ".join(problems)
        print(f"[plan] 시도 {n}/{max_tries} 반려(구조 문제): {last}")
        messages += [
            {"role": "assistant", "content": json.dumps(raw, ensure_ascii=False)},
            {"role": "user", "content": f"다음 문제를 모두 고쳐서 JSON 만 다시 출력하세요: {last}"},
        ]
    raise RuntimeError(f"스토리 기획 검증 실패: {last}")


def simplify_scene(scene: str, motifs: list[str]) -> str:
    """이미지 검증에 계속 탈락할 때 쓰는 단순화 장면 (소재 1~2개만)."""
    return f"a simple minimal {' and '.join(motifs[:2])} scene, soft light, tidy, empty center"
