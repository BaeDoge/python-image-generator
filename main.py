"""쿠팡 파트너스 상품 자동 선택 -> LLM 이 컨셉/스토리/프롬프트를 스스로 기획 -> 검증 -> GPU 이미지 후보 생성/선별
-> 6장 캐러셀 합성 -> (선택) Threads 게시

  python main.py check                         # 환경 진단
  python main.py post --demo --no-image        # 키 없이 기획(텍스트)+검증만
  python main.py post --demo                   # 키 없이 가짜 상품으로 전체 생성 (게시 안 함)
  python main.py post --dry-run                # 오늘의 상품을 자동 선택해 생성만 (out/ 저장)
  python main.py post                          # 자동 선택 + 검증 통과 시 게시
  python main.py post --keyword "무선 청소기"   # (선택) 키워드 지정, --category 1013 도 가능
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from io import BytesIO

import requests
from PIL import Image, ImageDraw

from bot import compose, coupang, db, hosting, llm, planner, selector, styles, threads, verify
from bot.config import OUT_DIR


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


def _demo_product() -> tuple[coupang.Product, Image.Image]:
    img = Image.new("RGB", (700, 700), "white")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((170, 120, 530, 600), 60, fill=(236, 112, 99), outline=(150, 60, 50), width=6)
    d.rectangle((250, 200, 450, 330), fill=(255, 235, 230))
    d.ellipse((300, 400, 400, 500), fill=(255, 255, 255))
    p = coupang.Product("demo1", "무선 핸디 청소기 대용량 배터리 올인원 세트", 59900, "",
                        "https://link.coupang.com/demo", True, True, "가전디지털")
    return p, img


def _plan(args) -> tuple[coupang.Product, str, dict, dict, dict]:
    """상품 후보를 차례로 시도해 기획+텍스트 검증을 통과하는 첫 상품을 반환."""
    if args.demo:
        cands = [_demo_product()[0]]
    else:
        cands = selector.candidates(args.keyword, args.category)
    last_err = ""
    for product in cands[:5]:
        print(f"[1/6] 상품 후보: {product.name} / {product.price:,}원 / id={product.id}")
        link = product.url if args.demo else coupang.shorten(product.url)
        try:
            story, analysis, report = planner.build_story(product, link)
            return product, link, story, analysis, report
        except planner.SkipProduct as e:
            print(f"  -> 건너뜀: {e}")
            last_err = str(e)
        except RuntimeError as e:
            print(f"  -> 기획 실패, 다음 상품 시도: {e}")
            last_err = str(e)
    raise SystemExit(f"기획/검증을 통과한 상품이 없습니다. 마지막 사유: {last_err}")


def _generate_images(story: dict, analysis: dict, n: int, seed: int | None):
    """장면별 후보를 만들고 검증해 최선을 고른다. 탈락 장면은 단순화한 장면으로 1회 재생성."""
    from bot import imagegen  # torch 를 늦게 import

    style_id = story["concept"]["style_id"]
    scenes = [p["scene"] for p in story["panels"]] + [story["backdrop"]]
    items = [styles.build(style_id, sc) for sc in scenes]
    print(f"[4/6] 이미지 후보 생성 (스타일 {style_id}, 장면당 {n}장)")
    cands, seed = imagegen.generate_candidates(items, n=n, seed=seed)

    results = [verify.select_best(c, sc) for c, sc in zip(cands, scenes)]
    failed = [i for i, r in enumerate(results) if not r["passed"]]
    if failed:
        print(f"[verify] 탈락 장면 {[i + 1 for i in failed]} -> 단순화한 장면으로 재생성")
        simple = [styles.build(style_id, planner.simplify_scene(scenes[i], analysis["visual_motifs"])) for i in failed]
        retry, _ = imagegen.generate_candidates(simple, n=n, seed=(seed or 0) + 777)
        for i, rc, it in zip(failed, retry, simple):
            r2 = verify.select_best(rc, it["scene"])
            cands[i], results[i], scenes[i] = rc, r2, it["scene"]

    picks, critical = [], []
    for i, (c, r) in enumerate(zip(cands, results)):
        if r["passed"]:
            picks.append(c[r["best"]])
        else:
            picks.append(c[verify.least_bad(c)])
            critical.append(f"장면 {i + 1} 이미지가 검증을 통과하지 못했습니다 ({r['basic']})")
    return picks, seed, results, critical


def cmd_post(args) -> None:
    product, link, story, analysis, text_report = _plan(args)
    c = story["concept"]
    print(f"[2/6] 컨셉: {c['angle']} / 말투 {c['tone']} / 스타일 {c['style_id']}")
    print("[3/6] 스토리 기획+검증 통과")
    print(f"  표지 : {story['hook']}  /  부제: {story['panels'][0]['caption']}")
    for i, p in enumerate(story["panels"][1:], 2):
        print(f"  {i}장  : {p['caption']}")
    print(f"  4장  : {story['reveal']}\n  5장  : {' | '.join(story['for_whom'])}\n  6장  : {story['cta']}")
    print(f"  ---- 본문 ----\n{story['text']}\n  --------------")
    if args.no_image:
        return

    picks, seed, img_results, critical = _generate_images(story, analysis, args.candidates, args.seed)
    prod_img = _demo_product()[1] if args.demo else _download_product(product.image)
    out_dir = OUT_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{product.id}"
    paths = compose.render_all(story, picks[:3], prod_img, product, out_dir, backdrop=picks[3])
    semantic = any(r["semantic_verified"] for r in img_results)
    warnings = [] if semantic else ["비전 모델(VLM)이 없어 이미지 의미 검증은 CLIP 순위/기본 품질 검사만 수행됨"]
    warnings += [f"LLM 검수 미해결: {w}" for w in text_report.get("warnings", [])]
    report = {"text": text_report, "images": img_results, "critical": critical, "warnings": warnings}
    (out_dir / "verify.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (out_dir / "post.json").write_text(
        json.dumps({"product": product.__dict__, "link": link, "seed": seed, "analysis": analysis, **story},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[5/6] 슬라이드 {len(paths)}장 합성 완료: {out_dir}")
    for w in warnings:
        print(f"  [주의] {w}")
    for cr in critical:
        print(f"  [검증 실패] {cr}")

    if args.dry_run or args.demo:
        print("[dry-run] 업로드/게시를 건너뜁니다. 폴더의 slide_1~6.jpg 와 verify.json 을 확인하세요.")
        return
    if critical and not args.force:
        raise SystemExit("검증 실패 항목이 있어 게시하지 않습니다. (확인 후 강행하려면 --force)")

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
    run("로컬 LLM", lambda: llm.ping().strip()[-30:] or "(빈 응답: thinking 설정 확인)")
    run("비전 LLM(선택)", lambda: "사용 가능" if llm.vlm_available() else "미설정 -> CLIP/기본 검사만 사용")
    run("CLIP(이미지 선별)", lambda: "로드됨" if verify._load_clip() else "로드 실패 -> 순위 선별 생략")
    run("Threads 토큰", lambda: threads.whoami())


def cmd_refresh(_args) -> None:
    j = threads.refresh_token()
    print("새 토큰을 .env 의 THREADS_ACCESS_TOKEN 에 붙여넣으세요:")
    print(j.get("access_token"), f"\n(유효기간 {int(j.get('expires_in', 0)) // 86400}일)")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("post", help="자동 상품 선택 -> 기획/검증 -> 이미지 -> 캐러셀 -> 게시")
    p.add_argument("--keyword", help="(선택) 쿠팡 검색 키워드. 생략하면 자동 선택")
    p.add_argument("--category", help="(선택) 쿠팡 카테고리 ID. 생략하면 날짜별 자동 순환")
    p.add_argument("--dry-run", action="store_true", help="업로드/게시 없이 out/ 에만 저장")
    p.add_argument("--demo", action="store_true", help="쿠팡/Threads 키 없이 가짜 상품으로 전체 생성 테스트")
    p.add_argument("--no-image", action="store_true", help="기획+텍스트 검증만 실행")
    p.add_argument("--candidates", type=int, default=3, help="장면당 이미지 후보 수 (기본 3)")
    p.add_argument("--seed", type=int, help="이미지 시드 고정")
    p.add_argument("--force", action="store_true", help="검증 실패가 있어도 게시 강행")
    p.set_defaults(fn=cmd_post)

    sub.add_parser("check", help="환경 진단").set_defaults(fn=cmd_check)
    sub.add_parser("refresh-token", help="Threads 장기 토큰 갱신").set_defaults(fn=cmd_refresh)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
