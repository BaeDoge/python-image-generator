"""스토리 캐러셀 6장을 Pillow 로 렌더링한다.
 1~3장: 생성한 만화 컷 + 한글 캡션   4장: 상품(누끼+스티커)   5장: 이런 분께   6장: 구매 안내
상품은 AI 가 그리지 않고 쿠팡 API 의 실제 상품 사진을 그대로 쓴다."""
from __future__ import annotations

import colorsys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .config import get
from .coupang import Product

W, H = 1080, 1350  # 4:5
MARGIN = 60
INK = (30, 41, 59, 255)
SUB = (71, 85, 105, 255)

_FONT_CANDIDATES = [
    "C:/Windows/Fonts/malgunbd.ttf",
    "C:/Windows/Fonts/malgun.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
]


# ───────────────────────── 공통 유틸 ─────────────────────────
def find_font() -> str | None:
    custom = get("FONT_PATH")
    for p in ([custom] if custom else []) + _FONT_CANDIDATES:
        if p and Path(p).exists():
            return p
    return None


def _font(size: int):
    p = find_font()
    if p:
        return ImageFont.truetype(p, size)
    print("[warn] 한글 폰트를 찾지 못했습니다. .env 의 FONT_PATH 를 지정하세요. (글자가 깨질 수 있음)")
    return ImageFont.load_default()


def fit_cover(img: Image.Image, w: int, h: int) -> Image.Image:
    r = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * r), round(img.height * r)), Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
        elif draw.textlength(cur + ch, font=font) <= max_w:
            cur += ch
        else:
            lines.append(cur)
            cur = ch.lstrip()
    if cur:
        lines.append(cur)
    return lines


def _ellipsize(draw, text: str, font, max_w: int, max_lines: int) -> list[str]:
    lines = _wrap(draw, text, font, max_w)
    if len(lines) <= max_lines:
        return lines
    lines = lines[:max_lines]
    last = lines[-1]
    while last and draw.textlength(last + "…", font=font) > max_w:
        last = last[:-1]
    lines[-1] = last + "…"
    return lines


def _fit_text(draw, text: str, max_w: int, max_lines: int, start: int, min_size: int):
    size = start
    while True:
        f = _font(size)
        lines = _wrap(draw, text, f, max_w)
        if len(lines) <= max_lines or size <= min_size:
            return f, lines, size
        size -= 4


def _blend(c, mix: float):  # 흰색과 섞어 파스텔로
    return tuple(int(v * (1 - mix) + 255 * mix) for v in c[:3])


def dominant_color(img: Image.Image) -> tuple[int, int, int]:
    """상품 사진에서 채도 있는 대표색을 고른다 (없으면 기본 인디고)."""
    small = img.convert("RGB").resize((64, 64))
    q = small.quantize(colors=6)
    pal = q.getpalette() or []
    for count, idx in sorted(q.getcolors() or [], reverse=True):
        r, g, b = pal[idx * 3: idx * 3 + 3]
        _, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if s > 0.28 and 0.25 < v < 0.95:
            return (r, g, b)
    return (99, 102, 241)


def gradient_bg(color) -> Image.Image:
    top = Image.new("RGB", (W, H), _blend(color, 0.90))
    bot = Image.new("RGB", (W, H), _blend(color, 0.68))
    mask = Image.linear_gradient("L").resize((W, H))
    return Image.composite(bot, top, mask)


# ───────────────────────── 상품 누끼 / 스티커 ─────────────────────────
def remove_bg(img: Image.Image) -> Image.Image | None:
    """rembg 가 설치돼 있으면 사용, 아니면 '흰 배경 상품컷' 가정의 flood-fill 누끼.
    배경이 흰색이 아니거나 결과가 이상하면 None (-> 카드형 배치로 대체)."""
    img = img.convert("RGB")
    try:
        from rembg import remove  # 선택 설치

        out = remove(img)
        return out.crop(out.getchannel("A").getbbox()) if out.getchannel("A").getbbox() else None
    except Exception:  # noqa: BLE001
        pass

    w, h = img.size
    pts = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    if any(min(img.getpixel(p)) < 225 for p in pts):
        return None  # 배경이 흰색이 아님
    marker = (255, 0, 255)
    work = img.copy()
    for p in pts:
        ImageDraw.floodfill(work, p, marker, thresh=18)
    alpha = ImageChops.difference(work, Image.new("RGB", work.size, marker)).convert("L").point(
        lambda v: 255 if v > 8 else 0
    )
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.2))
    hist = alpha.histogram()
    transparent_ratio = sum(hist[:32]) / (w * h)
    bbox = alpha.getbbox()
    if not bbox or transparent_ratio < 0.08 or transparent_ratio > 0.92:
        return None
    rgba = img.convert("RGBA")
    rgba.putalpha(alpha)
    return rgba.crop(bbox)


def _sticker(cut: Image.Image, border: int = 14) -> Image.Image:
    pad = border + 40
    base = Image.new("RGBA", (cut.width + 2 * pad, cut.height + 2 * pad), (0, 0, 0, 0))
    base.alpha_composite(cut, (pad, pad))
    a = base.getchannel("A")
    grown = a
    for _ in range(border):  # 3x3 팽창을 반복 (큰 커널보다 빠름)
        grown = grown.filter(ImageFilter.MaxFilter(3))
    white = Image.new("RGBA", base.size, (255, 255, 255, 255))
    white.putalpha(grown)
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    shadow.putalpha(grown.filter(ImageFilter.GaussianBlur(18)).point(lambda v: int(v * 0.35)))
    canvas = Image.new("RGBA", base.size, (0, 0, 0, 0))
    canvas.alpha_composite(shadow, (0, 14))
    canvas.alpha_composite(white)
    canvas.alpha_composite(base)
    return canvas


def _card_item(img: Image.Image, size: int = 640, radius: int = 40) -> Image.Image:
    """누끼가 안 될 때: 둥근 흰 카드 위에 상품 사진 + 그림자."""
    img = img.convert("RGB")
    img.thumbnail((size, size), Image.LANCZOS)
    tile = Image.new("RGB", (img.width + 40, img.height + 40), "white")
    tile.paste(img, (20, 20))
    mask = Image.new("L", tile.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, tile.width - 1, tile.height - 1), radius, fill=255)
    pad = 50
    out = Image.new("RGBA", (tile.width + 2 * pad, tile.height + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
    big = Image.new("L", out.size, 0)
    big.paste(mask, (pad, pad))
    sh.putalpha(big.filter(ImageFilter.GaussianBlur(18)).point(lambda v: int(v * 0.30)))
    out.alpha_composite(sh, (0, 12))
    out.paste(tile, (pad, pad), mask)
    return out


# ───────────────────────── 공통 오버레이 ─────────────────────────
def _dots(draw: ImageDraw.ImageDraw, page: int, total: int, accent) -> None:
    r, gap = 8, 30
    x0 = (W - (total - 1) * gap) / 2
    for i in range(total):
        c = (*accent, 255) if i == page else (255, 255, 255, 200)
        x = x0 + i * gap
        draw.ellipse((x - r, H - 44 - r, x + r, H - 44 + r), fill=c, outline=(*accent, 120))


def _panel_slide(scene_img: Image.Image, text: str, accent, page: int, total: int, cover: bool, subtitle: str = "") -> Image.Image:
    canvas = fit_cover(scene_img.convert("RGB"), W, H).convert("RGBA")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    inner_w = W - 2 * MARGIN - 80
    f, lines, size = _fit_text(d, text, inner_w, 3, 92 if cover else 64, 40)
    line_h = int(size * 1.28)
    panel_h = line_h * len(lines) + 70
    d.rounded_rectangle((MARGIN, MARGIN, W - MARGIN, MARGIN + panel_h), 40, fill=(255, 255, 255, 235))
    if cover:
        d.rounded_rectangle((MARGIN + 36, MARGIN + 26, MARGIN + 36 + 120, MARGIN + 26 + 10), 5, fill=(*accent, 255))
    y = MARGIN + 36
    for ln in lines:
        d.text(((W - d.textlength(ln, font=f)) / 2, y), ln, font=f, fill=INK)
        y += line_h
    if subtitle:  # 표지: 하단 부제(상황 제시)
        sf, slines, ssize = _fit_text(d, subtitle, W - 2 * MARGIN - 80, 2, 46, 32)
        sh = int(ssize * 1.3) * len(slines) + 50
        sy = H - 130 - sh
        d.rounded_rectangle((MARGIN, sy, W - MARGIN, sy + sh), 32, fill=(255, 255, 255, 225))
        ty = sy + 25
        for ln in slines:
            d.text(((W - d.textlength(ln, font=sf)) / 2, ty), ln, font=sf, fill=SUB)
            ty += int(ssize * 1.3)
    tag_f = _font(24)
    tag = "AI 생성 일러스트 · 연출 상황"
    tw = d.textlength(tag, font=tag_f)
    d.rounded_rectangle((MARGIN, H - 96, MARGIN + tw + 32, H - 56), 20, fill=(0, 0, 0, 120))
    d.text((MARGIN + 16, H - 90), tag, font=tag_f, fill=(255, 255, 255, 235))
    _dots(d, page, total, accent)
    return Image.alpha_composite(canvas, ov).convert("RGB")


def _badges(d, x: int, y: int, product: Product) -> None:
    f = _font(30)
    for label, color in (
        ("로켓배송", (37, 99, 235, 255)) if product.rocket else (None, None),
        ("무료배송", (22, 163, 74, 255)) if product.free_ship else (None, None),
    ):
        if not label:
            continue
        bw = int(d.textlength(label, font=f)) + 36
        d.rounded_rectangle((x, y, x + bw, y + 48), 24, fill=color)
        d.text((x + 18, y + 5), label, font=f, fill=(255, 255, 255, 255))
        x += bw + 12


def _product_slide(prod_img: Image.Image, product: Product, reveal: str, accent, page: int, total: int) -> Image.Image:
    canvas = gradient_bg(accent).convert("RGBA")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)

    f, lines, size = _fit_text(d, reveal, W - 2 * MARGIN - 40, 2, 68, 44)
    y = MARGIN + 20
    for ln in lines:
        d.text(((W - d.textlength(ln, font=f)) / 2, y), ln, font=f, fill=INK)
        y += int(size * 1.3)

    cut = remove_bg(prod_img)
    item = _sticker(cut) if cut else _card_item(prod_img)
    box_w, box_h = W - 2 * MARGIN - 60, 640
    item.thumbnail((box_w, box_h), Image.LANCZOS)
    ix, iy = (W - item.width) // 2, 230 + (box_h - item.height) // 2
    ov.alpha_composite(item, (ix, iy))

    top = H - MARGIN - 250
    d.rounded_rectangle((MARGIN, top, W - MARGIN, H - MARGIN - 40), 36, fill=(255, 255, 255, 240))
    name_f = _font(36)
    for i, ln in enumerate(_ellipsize(d, product.name, name_f, W - 2 * MARGIN - 60, 2)):
        d.text((MARGIN + 30, top + 26 + i * 46), ln, font=name_f, fill=SUB)
    if product.price > 0:
        d.text((MARGIN + 30, top + 124), f"{product.price:,}원", font=_font(60), fill=(225, 29, 72, 255))
    _badges(d, MARGIN + 30 + 380, top + 140, product)
    _dots(d, page, total, accent)
    return Image.alpha_composite(canvas, ov).convert("RGB")


def _for_whom_slide(items: list[str], accent, page: int, total: int) -> Image.Image:
    canvas = gradient_bg(accent).convert("RGBA")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    title_f = _font(72)
    t = "이런 분께 맞을 거예요"
    d.text(((W - d.textlength(t, font=title_f)) / 2, 120), t, font=title_f, fill=INK)

    y, row_h = 330, 250
    item_f = _font(46)
    for i, text in enumerate(items[:3], 1):
        d.rounded_rectangle((MARGIN, y, W - MARGIN, y + row_h - 30), 40, fill=(255, 255, 255, 240))
        cx, cy = MARGIN + 90, y + (row_h - 30) // 2
        d.ellipse((cx - 46, cy - 46, cx + 46, cy + 46), fill=(*accent, 255))
        nf = _font(52)
        d.text((cx - d.textlength(str(i), font=nf) / 2, cy - 34), str(i), font=nf, fill=(255, 255, 255, 255))
        lines = _ellipsize(d, text, item_f, W - 2 * MARGIN - 220, 2)
        ty = cy - (len(lines) * 58) / 2 + 4
        for ln in lines:
            d.text((MARGIN + 170, ty), ln, font=item_f, fill=INK)
            ty += 58
        y += row_h
    _dots(d, page, total, accent)
    return Image.alpha_composite(canvas, ov).convert("RGB")


def _cta_slide(cta: str, product: Product, accent, page: int, total: int) -> Image.Image:
    canvas = gradient_bg(accent).convert("RGBA")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.rounded_rectangle((MARGIN, 230, W - MARGIN, 1010), 56, fill=(255, 255, 255, 245))
    f, lines, size = _fit_text(d, cta, W - 2 * MARGIN - 100, 3, 80, 48)
    y = 300
    for ln in lines:
        d.text(((W - d.textlength(ln, font=f)) / 2, y), ln, font=f, fill=INK)
        y += int(size * 1.3)
    if product.price > 0:
        pf = _font(96)
        pt = f"{product.price:,}원"
        d.text(((W - d.textlength(pt, font=pf)) / 2, 640), pt, font=pf, fill=(225, 29, 72, 255))
    labels = [l for l, ok in (("로켓배송", product.rocket), ("무료배송", product.free_ship)) if ok]
    if labels:
        bf = _font(30)
        total_w = sum(int(d.textlength(l, font=bf)) + 36 + 12 for l in labels) - 12
        _badges(d, (W - total_w) // 2, 790, product)
    sf = _font(28)
    for i, line in enumerate(["링크는 게시글 본문에 있어요", "쿠팡 파트너스 활동의 일환으로 수수료를 제공받습니다"]):
        d.text(((W - d.textlength(line, font=sf)) / 2, 1080 + i * 44), line, font=sf, fill=SUB)
    _dots(d, page, total, accent)
    return Image.alpha_composite(canvas, ov).convert("RGB")


# ───────────────────────── 진입점 ─────────────────────────
def render_all(story: dict, scene_imgs: list[Image.Image], product_img: Image.Image, product: Product, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    accent = dominant_color(product_img)
    total = 6
    slides = [
        _panel_slide(scene_imgs[0], story["hook"], accent, 0, total, cover=True, subtitle=story["panels"][0]["caption"]),
        _panel_slide(scene_imgs[1], story["panels"][1]["caption"], accent, 1, total, cover=False),
        _panel_slide(scene_imgs[2], story["panels"][2]["caption"], accent, 2, total, cover=False),
        _product_slide(product_img, product, story["reveal"], accent, 3, total),
        _for_whom_slide(story["for_whom"], accent, 4, total),
        _cta_slide(story["cta"], product, accent, 5, total),
    ]
    paths = []
    for i, im in enumerate(slides, 1):
        p = out_dir / f"slide_{i}.jpg"
        im.save(p, "JPEG", quality=92)
        paths.append(p)
    return paths
