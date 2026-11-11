"""생성물 검증: (1) 텍스트 규칙 (2) 사실 검증(LLM) (3) 이미지 기본 품질 (4) 이미지-장면 일치(VLM/CLIP)."""
from __future__ import annotations

import re

from PIL import Image, ImageStat

from . import llm
from .config import flag, get
from .styles import STYLES

DISCLOSURE = "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
THREADS_MAX = 500

# 거짓 경험담 / 과장 / 실존 인물 언급
BANNED = [
    "써봤", "써 봤", "직접 사용", "직접 써", "사용해봤", "사용해 봤", "구매했", "샀는데", "샀어",
    "내돈내산", "후기", "리뷰", "최고", "1위", "무조건", "100%", "완벽", "강추", "인생템", "역대급",
    "연예인", "유명인", "셀럽", "추천템",
]

# 광고체/문어체 종결 (~합니다, ~드립니다, ~소개합니다) -> 사람이 쓴 구어체가 아님
_FORMAL = re.compile(r"니다(?=[\s.!?…~]|$)")

# 상품명에 없는데 LLM 이 자주 덧붙이는 '장점' 어간. 상품명에 같은 어간이 있을 때만 허용한다.
BENEFIT_STEMS = ["가볍", "가벼", "수월", "손쉽", "간편", "편리", "강력", "오래 쓸", "오래 쓰", "깔끔하게", "튼튼", "조용", "빠르게", "효과"]

# 한글 본문에 허용할 문자 (한자/가나/기타 문자 혼입 차단 -> 렌더링 시 깨진 글자 방지)
_ALLOWED_CHAR = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ0-9A-Za-z\s.,!?~·…\-+/%()\[\]'\"“”‘’:;&×]")


def bad_chars(text: str) -> list[str]:
    return sorted({c for c in text if not _ALLOWED_CHAR.fullmatch(c)})


def _korean_fields(s: dict) -> list[tuple[str, str]]:
    out = [("hook", s.get("hook", "")), ("reveal", s.get("reveal", "")), ("cta", s.get("cta", "")), ("body", s.get("body", ""))]
    out += [(f"panels[{i}].caption", p.get("caption", "")) for i, p in enumerate(s.get("panels") or [], 1)]
    out += [(f"for_whom[{i}]", t) for i, t in enumerate(s.get("for_whom") or [], 1)]
    return [(k, str(v).strip()) for k, v in out]


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*", text)}


def check_story(s: dict, analysis: dict, min_body: int, max_body: int, product_name: str = "", price: int = 0) -> list[str]:
    """구조/문장 규칙 위반 목록 (비어 있으면 통과)."""
    out: list[str] = []
    limits = {"hook": (1, 24), "reveal": (1, 24), "cta": (1, 30), "body": (min_body, max_body)}
    allowed_nums = _numbers(product_name) | ({str(price)} if price else set())
    for key, text in _korean_fields(s):
        lo, hi = limits.get(key, (1, 22 if key.startswith("for_whom") else 34))
        if not (lo <= len(text) <= hi):
            out.append(f"{key} 는 {lo}~{hi}자여야 함 (현재 {len(text)}자)")
        bc = bad_chars(text)
        if bc:
            out.append(f"{key} 에 한글이 아닌 문자 혼입: {''.join(bc)} (한자/외국 문자 금지)")
        for w in BANNED:
            if w in text:
                out.append(f"{key} 에 금지 표현 '{w}'")
        if re.search(r"https?://|#\S", text):
            out.append(f"{key} 에 링크/해시태그 금지")
        if re.search(r"(\S{2,})\s+\1", text):
            out.append(f"{key} 에 같은 단어 반복")
        extra_nums = _numbers(text) - allowed_nums
        if extra_nums:
            out.append(f"{key} 에 상품명/가격에 없는 숫자 {sorted(extra_nums)} -> 수치 주장 금지")
        if not key.startswith("for_whom"):  # '이런 분께' 는 명사구라 제외
            if _FORMAL.search(text):
                out.append(f"{key} 에 광고체/문어체 종결(~합니다/~드립니다) 금지 -> ~해요/~거든요/~더라 같은 구어체로")
            for stem in BENEFIT_STEMS:
                if stem in text and stem not in product_name:
                    out.append(f"{key} 에 상품명에 없는 장점 표현 '{stem}…' -> 삭제하거나 상황 묘사로 바꾸기")

    panels = s.get("panels") or []
    if len(panels) != 3:
        out.append("panels 는 정확히 3개여야 함")
    caps = [str(p.get("caption", "")).strip() for p in panels]
    if len(set(caps)) != len(caps):
        out.append("panels 캡션이 서로 달라야 함")
    fw = [str(t).strip() for t in (s.get("for_whom") or [])]
    if len(fw) != 3 or len(set(fw)) != 3:
        out.append("for_whom 은 서로 다른 3개여야 함")

    motifs = [m.lower() for m in analysis.get("visual_motifs", [])]
    scenes = [(f"panels[{i}].scene", p.get("scene", "")) for i, p in enumerate(panels, 1)] + [("backdrop", s.get("backdrop", ""))]
    for key, sc in scenes:
        sc = str(sc).strip()
        if not sc:
            out.append(f"{key} 가 비어 있음")
            continue
        if "motif" in sc.lower() or ":" in sc:
            out.append(f"{key} 에 설명 문구('visual motif:' 등)/콜론 금지 -> 장면 자체만 묘사")
        if not sc.isascii():
            out.append(f"{key} 는 영어(ASCII)로만 써야 함")
        if len(sc.split()) > 28:
            out.append(f"{key} 는 28단어 이내여야 함")
        if key.startswith("panels") and motifs and not any(m in sc.lower() for m in motifs):
            out.append(f"{key} 에 상품과 관련된 소재({', '.join(motifs[:5])}) 중 하나가 들어가야 함")

    if (s.get("concept") or {}).get("style_id") not in STYLES:
        out.append(f"concept.style_id 는 {sorted(STYLES)} 중 하나여야 함")
    return out


FACT_SYSTEM = "당신은 광고 콘텐츠 검수자입니다. 근거 없는 주장과 상품과 무관한 장면만 골라냅니다. 출력은 JSON 한 개."
FACT_USER = """상품 데이터(이것만 사실로 인정):
- 상품명: {name}
- 가격: {price}원
- 로켓배송: {rocket} / 무료배송: {free_ship}
- 상품 종류: {ptype}

[검증할 문구]
{texts}

[검증할 장면 묘사(영어, 이미지 생성용)]
{scenes}

1) unsupported_claims: 문구 중 상품 데이터에 없는 '성능·스펙·효능·수치·인증·수상·비교우위·장점' 주장을 그대로 적으세요.
   상품명에서 직접 읽히지 않는 추론 장점도 주장입니다 (예: '대용량 배터리' -> '오래 쓸 수 있다', '핸디' -> '가볍다'는 근거 없음).
   상품명에 적힌 표현을 그대로 다시 쓴 것은 사실이므로 주장이 아닙니다 (예: 상품명에 '대용량 배터리'가 있으면 '대용량 배터리' 언급은 문제 아님).
   (불편한 상황 묘사, 상상해 보라는 권유, '이런 분께' 같은 공감 문구, 데이터와 맞는 가격/배송 언급은 문제 아님)
2) unrelated_scenes: 장면 묘사 중 '{ptype}' 의 사용 상황과 전혀 무관한 장소/사물이 등장하는 것만 그대로 적으세요.
   허용 소재: {motifs} (이 소재와 그 일상적 주변 사물은 무관하지 않음. 사용 전 불편한 상황으로 구식 제품이 나오는 것도 괜찮음).
   의심스러우면 적지 마세요. 확실히 무관한 경우만 적습니다.
{{"unsupported_claims": [], "unrelated_scenes": []}}"""


_STOP = {"등장", "소개", "있어요", "있네요", "이에요", "예요", "입니다", "상품", "제품", "나왔어요", "나왔네요"}


def _grounded(claim: str, name: str) -> bool:
    """검수 LLM 이 '근거 없음'으로 적은 문구가 사실은 상품명을 그대로 옮긴 것이면 True (오탐 제거)."""
    for t in re.findall(r"[가-힣A-Za-z0-9]{2,}", claim):
        forms = [f for f in (t, t[:-1], t[:-2]) if len(f) >= 2]  # 조사 제거 근사
        if any(f in name for f in forms) or any(f in _STOP for f in forms):
            continue
        return False
    return True


def fact_check(s: dict, product, analysis: dict | None = None) -> list[str]:
    """LLM 검수. 반환값은 '고쳐야 할 문제' 문장 목록 (비어 있으면 통과)."""
    analysis = analysis or {}
    think = flag("VERIFY_THINKING")  # 검수에만 thinking 사용 (느리지만 판정이 더 정확)
    texts = "\n".join(f"- {t}" for _, t in _korean_fields(s))
    scenes = "\n".join(f"- {p.get('scene', '')}" for p in (s.get("panels") or []))
    scenes += f"\n- {s.get('backdrop', '')}"
    d = llm.chat_json(
        [
            {"role": "system", "content": FACT_SYSTEM},
            {"role": "user", "content": FACT_USER.format(
                name=product.name, price=f"{product.price:,}",
                rocket="예" if product.rocket else "아니오", free_ship="예" if product.free_ship else "아니오",
                ptype=analysis.get("product_type") or product.name, motifs=", ".join(analysis.get("visual_motifs", [])),
                texts=texts, scenes=scenes)},
        ],
        think=think, max_tokens=6000 if think else 700, temperature=0,
    )
    out = [f"근거 없는 상품 주장: '{c}' -> 상품 데이터에 있는 사실만 쓰거나 삭제"
           for c in (d.get("unsupported_claims") or []) if str(c).strip() and not _grounded(str(c), product.name)]
    out += [f"상품과 무관한 장면: '{c}' -> 상품이 실제로 쓰이는 상황의 장면으로 교체"
            for c in (d.get("unrelated_scenes") or []) if str(c).strip()]
    return out


# ───────────────────────── 이미지 검증 ─────────────────────────
def image_basic_check(img: Image.Image) -> dict:
    """검은/흰/단색/디테일 부족 같은 '망한 이미지'를 걸러낸다 (의미 검증은 VLM/CLIP 몫)."""
    g = img.convert("L").resize((270, 338))
    st = ImageStat.Stat(g)
    m = {"mean": round(st.mean[0], 1), "std": round(st.stddev[0], 1), "entropy": round(g.entropy(), 2)}
    reasons = []
    if m["mean"] < 90:
        reasons.append("너무 어두움")
    if m["mean"] > 245:
        reasons.append("거의 흰색")
    if m["std"] < 30:
        reasons.append("대비 부족/거의 단색")
    if m["entropy"] < 5.0:
        reasons.append("디테일 부족")
    return {"ok": not reasons, "metrics": m, "reasons": reasons}


VLM_PROMPT = """이 이미지는 아래 장면 설명으로 생성한 일러스트입니다.
장면 설명: "{scene}"
JSON 하나로만 답하세요.
{{"matches_scene": 장면 설명과 대체로 일치하는가(true/false),
  "contains_text_or_letters": 이미지 안에 글자/숫자/로고가 보이는가,
  "deformed_objects": 사물·사람 형태가 심하게 일그러졌거나 알아볼 수 없는가,
  "bright_and_clean": 밝고 깔끔한 인상인가}}"""

_clip = None


def _load_clip():
    global _clip
    if _clip is None:
        try:
            import torch
            from transformers import CLIPModel, CLIPProcessor

            name = get("CLIP_MODEL", "openai/clip-vit-base-patch32")
            dev = "cuda" if torch.cuda.is_available() else "cpu"
            _clip = (CLIPModel.from_pretrained(name).to(dev).eval(), CLIPProcessor.from_pretrained(name), dev)
        except Exception as e:  # noqa: BLE001
            print(f"[verify] CLIP 로드 실패 -> 순위 선별 생략: {e}")
            _clip = False
    return _clip or None


def clip_scores(images: list[Image.Image], text: str) -> list[float] | None:
    c = _load_clip()
    if not c or not images:
        return None
    import torch

    model, proc, dev = c
    with torch.no_grad():
        inp = proc(text=[text], images=images, return_tensors="pt", padding=True, truncation=True).to(dev)
        out = model(**inp)
        im = out.image_embeds / out.image_embeds.norm(dim=-1, keepdim=True)
        tx = out.text_embeds / out.text_embeds.norm(dim=-1, keepdim=True)
        return (im @ tx.T).squeeze(-1).tolist()


def select_best(images: list[Image.Image], scene: str) -> dict:
    """후보 이미지들 중 통과한 것만 남기고, CLIP 점수가 가장 높은 것을 고른다."""
    basic = [image_basic_check(i) for i in images]
    cand = [k for k, b in enumerate(basic) if b["ok"]]
    vlm: dict[int, dict | None] = {}
    if llm.vlm_available():
        for k in list(cand):
            try:
                j = llm.vlm_json(VLM_PROMPT.format(scene=scene), images[k])
            except Exception as e:  # noqa: BLE001
                print(f"[verify] VLM 호출 실패(후보 {k}): {e}")
                j = None
            vlm[k] = j
            if j is not None and not (
                j.get("matches_scene") and not j.get("contains_text_or_letters") and not j.get("deformed_objects")
            ):
                cand.remove(k)
    scores = clip_scores([images[k] for k in cand], scene) if cand else None
    best = None
    if cand:
        best = cand[max(range(len(cand)), key=lambda i: scores[i])] if scores else cand[0]
    return {
        "passed": best is not None,
        "best": best,
        "basic": basic,
        "vlm": {str(k): v for k, v in vlm.items()},
        "clip": {str(k): round(s, 4) for k, s in zip(cand, scores)} if scores else None,
        "semantic_verified": bool(vlm) and any(v is not None for v in vlm.values()),
    }


def least_bad(images: list[Image.Image]) -> int:
    """모든 후보가 탈락했을 때 그나마 대비(std)가 가장 높은 것."""
    return max(range(len(images)), key=lambda i: image_basic_check(images[i])["metrics"]["std"])
