"""OpenAI 호환 엔드포인트 공통 클라이언트 (텍스트 LLM + 선택적 비전 LLM)."""
from __future__ import annotations

import base64
import io
import json
import re

from openai import OpenAI
from PIL import Image

from .config import flag, get


def _client(base_url: str | None = None, api_key: str | None = None) -> OpenAI:
    return OpenAI(
        base_url=base_url or get("LLM_BASE_URL", "http://127.0.0.1:8080/v1"),
        api_key=api_key or get("LLM_API_KEY", "sk-local"),
        timeout=600,  # 로컬 모델은 느려도 괜찮음
    )


def _extra(think: bool = False) -> dict:
    if not think and flag("LLM_DISABLE_THINKING", True):
        return {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}
    return {}


def chat(messages: list[dict], max_tokens: int = 1600, temperature: float = 0.8, think: bool = False) -> str:
    resp = _client().chat.completions.create(
        model=get("LLM_MODEL", "local"),
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        **_extra(think),
    )
    return resp.choices[0].message.content or ""


def extract_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("응답에서 JSON을 찾지 못함 (content 가 비었거나 thinking 모드일 수 있음)")
    return json.loads(m.group(0))


def chat_json(messages: list[dict], max_tokens: int = 1600, temperature: float = 0.8, tries: int = 3,
              think: bool = False) -> dict:
    last: Exception | None = None
    msgs = list(messages)
    for _ in range(tries):
        raw = chat(msgs, max_tokens=max_tokens, temperature=temperature, think=think)
        try:
            return extract_json(raw)
        except Exception as e:  # noqa: BLE001
            last = e
            msgs += [
                {"role": "assistant", "content": raw or "(빈 응답)"},
                {"role": "user", "content": "JSON 객체 하나만 다시 출력하세요."},
            ]
    raise RuntimeError(f"LLM JSON 응답 실패: {last}")


def ping() -> str:
    return chat([{"role": "user", "content": "OK 라고만 답해."}], max_tokens=20, temperature=0)


# ── 선택: 비전 LLM (이미지 의미 검증용). VLM_BASE_URL 이 없으면 사용 안 함 ──
def vlm_available() -> bool:
    return bool(get("VLM_BASE_URL"))


def vlm_json(prompt: str, image: Image.Image) -> dict:
    img = image.convert("RGB")
    img.thumbnail((768, 768))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode()
    client = _client(get("VLM_BASE_URL"), get("VLM_API_KEY") or get("LLM_API_KEY", "sk-local"))
    resp = client.chat.completions.create(
        model=get("VLM_MODEL", "local"),
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        }],
        max_tokens=300,
        temperature=0,
        **_extra(),
    )
    return extract_json(resp.choices[0].message.content or "")
