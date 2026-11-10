"""쿠팡 파트너스 상품 -> (로컬 LLM) 상황 만화 스토리 -> (로컬 GPU) 컷 이미지 -> 6장 캐러셀 -> Threads 게시

사용법 (프로젝트 루트에서)
  python main.py check                                  # 환경 진단
  python main.py post --demo --no-image                 # 키 없이 스토리 텍스트만 확인
  python main.py post --demo                            # 키 없이 가짜 상품으로 6장 전체 생성 (게시 안 함)
  python main.py post --keyword "무선 청소기" --dry-run   # 실제 상품으로 생성만 (out/ 에 저장)
  python main.py post --keyword "무선 청소기"            # 실제 게시 (쿠팡/Threads/이미지호스팅 설정 필요)
  python main.py refresh-token                          # Threads 토큰 갱신
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from datetime import datetime
from io import BytesIO

import requests
from PIL import Image, ImageDraw

from bot import compose, copywriter, coupang, db, hosting, threads
from bot.config import OUT_DIR, get


def _download(url: str) -> Image.Image:
    r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return Image.open(BytesIO(r.content)).convert("RGB")


def _download_product(url: str) -> Image.Image:
    """쿠팡 CDN 썸네일은 URL 의 NNNxNNNex 부분으로 크기가 정해지므로 큰 사이즈를 먼저 시도한다."""
    big = re.sub(r"/\d+x\d+ex/", "/700x700ex/", url)
    if big != url:
        try:
            return _download(big)
        except Exception:  # noqa: BLE001
            print("[warn] 큰 상품 이미지를 받지 못해 원본 사이즈 사용")
    return _download(url)


def _demo_product_image() -> Image.Image:
    img = Image.new("RGB", (700, 700), "white")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((170, 120, 530, 600), 60, fill=(236, 112, 99), outline=(150, 60, 50), width=6)
    d.rectangle((250, 200, 450, 330), fill=(255, 235, 230))
    d.ellipse((300, 400, 400, 500), fill=(255, 255, 255))
    return img


def _pick_product(args) -> coupang.Product:
    if args.category:
        items = coupang.best_products(args.category, limit=20)
    else:
        items = coupang.search_products(args.keyword or get("DEFAULT_KEYWORD", "생활용품 추천"), limit=20)
    fresh = [p for p in items if p.image and p.url and not db.is_posted(p.id)]
    if not fresh:
        raise SystemExit("새로 게시할 상품이 없습니다 (검색 결과 없음 또는 전부 게시 이력 있음). 키워드를 바꿔보세요.")
    return random.choice(fresh[:5])


def cmd_post(args) -> None:
    if args.demo:
        args.dry_run = True
        product = coupang.Product(
            "demo1", "무선 핸디 청소기 대용량 배터리 올인원 세트", 59900, "",
            "https://link.coupang.com/demo", True, True, "가전디지털",
        )
    else:
        product = _pick_product(args)
    print(f"[1/6] 상품 선택: {product.name} / {product.price:,}원 / id={product.id}")

    link = product.url if args.demo else coupang.shorten(product.url)
    print(f"[2/6] 제휴 링크: {link}")

    story = copywriter.write_story(product, link)
    print("[3/6] 스토리 생성 완료")
    print(f"  표지 : {story['hook']}  /  부제: {story['panels'][0]['caption']}")
    for i, p in enumerate(story["panels"][1:], 2):
        print(f"  {i}장  : {p['caption']}")
    print(f"  4장  : {story['reveal']}")
    print(f"  5장  : {' | '.join(story['for_whom'])}")
    print(f"  6장  : {story['cta']}")
    print(f"  ---- 본문 ----\n{story['text']}\n  --------------")
    if args.no_image:
        return

    from bot import imagegen  # torch 를 늦게 import

    scenes = [p["scene"] for p in story["panels"]]
    print("[4/6] 만화 컷 생성 (GPU)")
    scene_imgs, seed = imagegen.generate_scenes(scenes, seed=args.seed)

    prod_img = _demo_product_image() if args.demo else _download_product(product.image)
    out_dir = OUT_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{product.id}"
    paths = compose.render_all(story, scene_imgs, prod_img, product, out_dir)
    (out_dir / "post.json").write_text(
        json.dumps({"product": product.__dict__, "link": link, "seed": seed, **story}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[5/6] 슬라이드 {len(paths)}장 합성 완료: {out_dir}")

    if args.dry_run:
        print("[dry-run] 업로드/게시를 건너뜁니다. 폴더의 slide_1~6.jpg 를 확인하세요.")
        return

    urls = [hosting.upload(p) for p in paths]
    print(f"[6/6] 이미지 {len(urls)}장 업로드 완료, Threads 게시 중...")
    post_id = threads.post_carousel(urls, story["text"])
    db.mark_posted(product.id, product.name, post_id)
    print(f"게시 완료! id={post_id} {threads.permalink(post_id) or ''}")


def cmd_check(_args) -> None:
    def run(label, fn):
        try:
            print(f"[OK]   {label}: {fn()}")
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {label}: {e}")

    def gpu():
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA 사용 불가 (torch CPU 빌드이거나 드라이버 문제)")
        free, total = torch.cuda.mem_get_info()
        return f"{torch.cuda.get_device_name(0)} / 여유 VRAM {free/2**30:.1f}GB of {total/2**30:.1f}GB"

    run("GPU", gpu)
    run("한글 폰트", lambda: compose.find_font() or (_ for _ in ()).throw(RuntimeError("없음 -> FONT_PATH 지정")))
    run("쿠팡 API", lambda: f"{len(coupang.search_products('물티슈', limit=3))}개 검색됨")
    run("로컬 LLM", lambda: copywriter.ping().strip()[-30:] or "(빈 응답: thinking 설정 확인)")
    run("Threads 토큰", lambda: threads.whoami())
    print("\n* 이미지 생성은 LLM 이 VRAM 을 쓰는 상태에서 돌아갑니다. 여유 VRAM 이 10GB 미만이면 IMAGE_CPU_OFFLOAD=1 권장.")


def cmd_refresh(_args) -> None:
    j = threads.refresh_token()
    print("새 토큰을 .env 의 THREADS_ACCESS_TOKEN 에 붙여넣으세요:")
    print(j.get("access_token"), f"\n(유효기간 {int(j.get('expires_in', 0)) // 86400}일)")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("post", help="상품 선택 -> 스토리/이미지 생성 -> Threads 캐러셀 게시")
    p.add_argument("--keyword", help="쿠팡 검색 키워드")
    p.add_argument("--category", help="쿠팡 카테고리 ID (예: 1013 주방용품) - 베스트 상품에서 선택")
    p.add_argument("--dry-run", action="store_true", help="업로드/게시 없이 out/ 에만 저장")
    p.add_argument("--demo", action="store_true", help="쿠팡/Threads 키 없이 가짜 상품으로 전체 생성 테스트")
    p.add_argument("--no-image", action="store_true", help="스토리(텍스트)만 생성해서 확인")
    p.add_argument("--seed", type=int, help="이미지 시드 고정")
    p.set_defaults(fn=cmd_post)

    sub.add_parser("check", help="환경 진단").set_defaults(fn=cmd_check)
    sub.add_parser("refresh-token", help="Threads 장기 토큰 갱신").set_defaults(fn=cmd_refresh)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
