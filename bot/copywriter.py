"""로컬 LLM(OpenAI 호환 엔드포인트)으로 '상황 만화 -> 상품 등장 -> 이런 분께 -> 구매 안내' 스토리 생성."""
from __future__ import annotations

import json
import re

from openai import OpenAI

from .config import flag, get
from .coupang import Product

DISCLOSURE = "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
THREADS_MAX = 500

# 거짓 경험담/과장/실존 인물 언급 차단
BANNED = [
    "써봤", "써 봤", "직접 사용", "직접 써", "사용해봤", "사용해 봤", "구매했", "샀는데", "샀어",
    "내돈내산", "후기", "리뷰", "최고", "1위", "무조건", "100%", "완벽", "강추", "인생템", "역대급",
    "연예인", "유명인", "셀럽", "추천템",
]

SYSTEM = """당신은 쇼핑 정보를 '공감되는 짧은 만화 스토리'로 풀어 Threads 캐러셀 게시물로 만드는 계정 운영자입니다.
계정 성격: {persona}

게시물 구조(총 6장): 1) 상황 제시 2) 불편 심화 3) 찾아보는 장면 4) 상품 등장 5) 이런 분께 6) 구매 안내
1~3장은 가상의 '연출 상황' 만화입니다. 실제 경험담이 아니라 "이런 상황이 있을 수 있다"는 공감용 장면입니다.

반드시 지킬 규칙:
- 상품 설명은 제공된 상품 데이터(이름, 가격, 배송 정보)에 있는 사실만 씁니다. 스펙·효능·수치를 지어내지 않습니다.
- '직접 써봤다/샀다/후기/내돈내산' 같은 경험담 금지. 실존 인물·연예인·유명인 언급 금지.
- '최고, 1위, 무조건, 100%, 완벽' 같은 과장·최상급 금지.
- 장면(scene)은 영어로, 사람 얼굴이 크게 보이지 않는 구도(뒷모습, 손, 멀리서 본 모습, 사물 중심)로 묘사합니다. 글자·브랜드·로고는 묘사하지 않습니다.
- 말투는 자연스러운 구어체, 이모지·해시태그·링크·광고 문구는 쓰지 않습니다(코드가 따로 붙임).
- 출력은 JSON 한 개만. 다른 설명 금지."""

USER = """상품 데이터:
- 상품명: {name}
- 가격: {price}원
- 카테고리: {category}
- 로켓배송: {rocket}
- 무료배송: {free_ship}

아래 JSON 형식으로만 답하세요.
{{
  "hook": "1장 표지 제목. 공감/궁금증 유도 (한글 22자 이내, 가격·최상급 금지)",
  "panels": [
    {{"caption": "1장(표지) 하단 부제 - 상황 제시 (한글 32자 이내)", "scene": "영어 장면 묘사 (25단어 이내)"}},
    {{"caption": "2장 불편이 심해지는 순간 (한글 32자 이내)", "scene": "영어 장면 묘사"}},
    {{"caption": "3장 해결책을 찾아보는 장면 (한글 32자 이내)", "scene": "영어 장면 묘사 (예: 뒷모습으로 스마트폰을 보는 사람)"}}
  ],
  "reveal": "4장 상품 등장 멘트 (한글 22자 이내, 예: '그러다 눈에 들어온 건')",
  "for_whom": ["5장 '이런 분께' 항목 3개. 상황/니즈 기준으로, 각 한글 20자 이내", "...", "..."],
  "cta": "6장 구매 안내 문구 (한글 22자 이내, 예: '자세한 건 링크에서 확인해요')",
  "body": "Threads 본문 (한글 {min_len}~{max_len}자, 2~4문장, 줄바꿈 가능)"
}}"""


def _client() -> OpenAI:
    return OpenAI(
        base_url=get("LLM_BASE_URL", "http://127.0.0.1:8080/v1"),
        api_key=get("LLM_API_KEY", "sk-local"),
        timeout=600,
    )


def _chat(messages: list[dict], max_tokens: int = 1400, temperature: float = 0.8) -> str:
    kwargs = {}
    if flag("LLM_DISABLE_THINKING", True):
        kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
    resp = _client().chat.completions.create(
        model=get("LLM_MODEL", "local"),
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        **kwargs,
    )
    return resp.choices[0].message.content or ""


def ping() -> str:
    return _chat([{"role": "user", "content": "OK 라고만 답해."}], max_tokens=20, temperature=0)


def _extract_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("응답에서 JSON을 찾지 못함 (content 가 비었거나 thinking 모드일 수 있음)")
    return json.loads(m.group(0))


def _s(v) -> str:
    return str(v).strip() if v is not None else ""


def _problems(d: dict, min_len: int, max_len: int) -> list[str]:
    out: list[str] = []
    texts: list[str] = []

    def chk(label: str, val: str, lo: int, hi: int):
        texts.append(val)
        if not (lo <= len(val) <= hi):
            out.append(f"{label} 는 {lo}~{hi}자여야 함 (현재 {len(val)}자)")

    chk("hook", _s(d.get("hook")), 1, 24)
    chk("reveal", _s(d.get("reveal")), 1, 24)
    chk("cta", _s(d.get("cta")), 1, 24)
    chk("body", _s(d.get("body")), min_len, max_len)

    panels = d.get("panels")
    if not isinstance(panels, list) or len(panels) != 3:
        out.append("panels 는 정확히 3개여야 함")
    else:
        for i, p in enumerate(panels, 1):
            chk(f"panels[{i}].caption", _s(p.get("caption")), 1, 34)
            if not _s(p.get("scene")):
                out.append(f"panels[{i}].scene 이 비어 있음")

    fw = d.get("for_whom")
    if not isinstance(fw, list) or len(fw) != 3:
        out.append("for_whom 은 정확히 3개여야 함")
    else:
        for i, t in enumerate(fw, 1):
            chk(f"for_whom[{i}]", _s(t), 1, 22)

    joined = " ".join(texts)
    for w in BANNED:
        if w in joined:
            out.append(f"금지 표현 '{w}' 포함")
    if re.search(r"https?://|#\S", joined):
        out.append("링크/해시태그 금지")
    return out


def write_story(product: Product, link: str, max_tries: int = 4) -> dict:
    """반환: {hook, panels[3], reveal, for_whom[3], cta, body, text}  (text = Threads 최종 본문)"""
    tail = f"\n\n{link}\n\n{DISCLOSURE}"
    max_len = min(THREADS_MAX - len(tail) - 5, 220)
    min_len = 70
    if max_len < min_len + 20:
        raise RuntimeError("링크가 너무 길어 본문 공간이 부족합니다. 딥링크 단축을 확인하세요.")

    messages = [
        {"role": "system", "content": SYSTEM.format(persona=get("PERSONA", "정보 공유 계정"))},
        {
            "role": "user",
            "content": USER.format(
                name=product.name,
                price=f"{product.price:,}",
                category=product.category or "미상",
                rocket="예" if product.rocket else "아니오",
                free_ship="예" if product.free_ship else "아니오",
                min_len=min_len,
                max_len=max_len,
            ),
        },
    ]
    last_err = ""
    for attempt in range(1, max_tries + 1):
        raw = _chat(messages)
        try:
            d = _extract_json(raw)
            problems = _problems(d, min_len, max_len)
        except Exception as e:  # noqa: BLE001
            d, problems = {}, [f"JSON 파싱 실패: {e}"]
        if not problems:
            story = {
                "hook": _s(d["hook"]),
                "panels": [{"caption": _s(p["caption"]), "scene": _s(p["scene"])} for p in d["panels"]],
                "reveal": _s(d["reveal"]),
                "for_whom": [_s(t) for t in d["for_whom"]],
                "cta": _s(d["cta"]),
                "body": _s(d["body"]),
            }
            story["text"] = story["body"] + tail
            assert len(story["text"]) <= THREADS_MAX
            return story
        last_err = "; ".join(problems)
        print(f"[copy] 시도 {attempt}/{max_tries} 실패: {last_err}")
        messages += [
            {"role": "assistant", "content": raw or "(빈 응답)"},
            {"role": "user", "content": f"다음 문제를 고쳐서 JSON만 다시 출력하세요: {last_err}"},
        ]
    raise RuntimeError(f"스토리 생성 실패: {last_err}")
