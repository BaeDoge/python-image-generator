"""GPU/네트워크 없이 도는 로직 테스트:  python -m unittest discover -s tests -v"""
from __future__ import annotations

import json
import os
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("COUPANG_ACCESS_KEY", "AK")
os.environ.setdefault("COUPANG_SECRET_KEY", "SK")

from PIL import Image, ImageDraw  # noqa: E402

from bot import compose, llm, planner, selector, verify  # noqa: E402
from bot.coupang import Product  # noqa: E402

ANALYSIS = {"product_type": "무선 핸디 청소기", "visual_motifs": ["sofa", "floor", "dust", "living room"],
            "mood": "cozy", "risk_flags": []}

GOOD = {
    "concept": {"angle": "선 없이 가볍게 치우고 싶은 순간", "tone": "담백한 구어체", "style_id": "flat_pastel"},
    "hook": "바닥 먼지, 오늘도 못 본 척?",
    "panels": [
        {"caption": "퇴근하고 보니 바닥에 먼지가 한가득", "scene": "living room floor with scattered dust, warm light"},
        {"caption": "청소기 꺼내서 선 연결하다 지치는 저녁", "scene": "tangled cord near sofa on the floor, no people"},
        {"caption": "선 없는 청소기를 찾아보는 중", "scene": "person seen from behind on sofa holding smartphone"},
    ],
    "backdrop": "tidy bright living room corner with a sofa, empty center, soft light",
    "reveal": "그러다 눈에 들어온 건",
    "for_whom": ["선 연결이 번거로웠던 분", "좁은 집을 자주 쓸어야 하는 분", "가볍게 청소하고 싶은 분"],
    "cta": "자세한 건 링크에서 확인해요",
    "body": "퇴근하고 바닥을 보면 먼지가 은근히 신경 쓰이잖아. 선 없이 쓰는 핸디형이 요즘 눈에 많이 띄어서 가져와 봤어. 대용량 배터리 올인원 세트에 로켓배송이야.",
}


def _draw():
    return ImageDraw.Draw(Image.new("RGB", (10, 10)))


class WrapTests(unittest.TestCase):
    def test_wrap_breaks_only_between_words(self):
        f = compose._font(56)
        text = "간단히 치우려니 자꾸 미뤄지네요"
        words = set(text.split())
        for max_w in (300, 420, 560, 700):
            lines = compose._wrap(_draw(), text, f, max_w)
            for ln in lines:
                self.assertTrue(set(ln.split()) <= words, (max_w, lines))
            self.assertEqual(" ".join(lines).split(), text.split())

    def test_no_orphan_last_line(self):
        f = compose._font(56)
        d = _draw()
        text = "선 연결이 번거로웠던 분"
        # 2줄이 가능한 폭(마지막 두 단어가 한 줄에 들어가는 폭)에서는 한 글자 고아 줄이 없어야 한다
        max_w = int(d.textlength("번거로웠던 분", font=f)) + 4
        lines = compose._wrap(d, text, f, max_w)
        self.assertEqual(lines, ["선 연결이", "번거로웠던 분"])


class TextCheckTests(unittest.TestCase):
    def test_bad_chars(self):
        self.assertTrue(verify.bad_chars("沙发角落 먼지"))
        self.assertEqual(verify.bad_chars("먼지 쌓인 곳, 59,900원!"), [])

    def test_good_story_passes(self):
        self.assertEqual(verify.check_story(GOOD, ANALYSIS, 70, 220), [])

    def test_real_failure_from_first_run_is_caught(self):
        bad = json.loads(json.dumps(GOOD))
        bad["panels"][0]["caption"] = "沙发角落 먼지 쌓인 곳, 손이 안 가요"
        bad["panels"][1] = {"caption": "유모차 바퀴 먼지, 매일 매번 귀찮아요",
                            "scene": "Close-up of a stroller wheel with visible dust"}
        probs = " | ".join(verify.check_story(bad, ANALYSIS, 70, 220))
        self.assertIn("한글이 아닌 문자", probs)  # 첫 실행에서 나온 '沙发' 혼입
        # 'dust' 키워드가 들어 있어 키워드 검사는 통과하므로, 무관 장면은 LLM 의미 검수(fact_check)가 잡는다 (PlannerTests)

    def test_repeated_word(self):
        bad = json.loads(json.dumps(GOOD)); bad["hook"] = "먼지 먼지 가득"
        self.assertIn("반복", " | ".join(verify.check_story(bad, ANALYSIS, 70, 220)))

    def test_banned_and_ascii_scene(self):
        bad = json.loads(json.dumps(GOOD))
        bad["body"] = "내가 직접 써봤는데 최고였어요 " * 6
        bad["panels"][2]["scene"] = "소파에 앉은 사람 sofa"
        probs = " | ".join(verify.check_story(bad, ANALYSIS, 70, 220))
        self.assertIn("금지 표현", probs)
        self.assertIn("영어(ASCII)", probs)


class ToneAndClaimTests(unittest.TestCase):
    NAME = "무선 핸디 청소기 대용량 배터리 올인원 세트"

    def test_real_demo_output_is_now_rejected(self):
        """실제 로컬 LLM 데모 출력: 광고체 종결 + 상품명에 없는 장점이 통과했던 문구들"""
        bad = json.loads(json.dumps(GOOD))
        bad["panels"][1]["caption"] = "무거운 청소기 들고 계단 오르는 것이 힘듭니다"
        bad["panels"][2]["caption"] = "가벼운 핸디형으로 소파 틈새까지 손쉽게"
        bad["body"] = ("거실 바닥에서 소파 틈새, 차 안까지 먼지 제거가 번거로우셨나요. 대용량 배터리로 오래 쓸 수 있는 올인원 세트를 "
                       "소개합니다. 가벼운 핸디형이라 계단 난간 청소도 수월합니다.")
        probs = " | ".join(verify.check_story(bad, ANALYSIS, 70, 220, self.NAME))
        self.assertIn("광고체/문어체", probs)
        self.assertIn("가벼", probs)
        self.assertIn("수월", probs)
        self.assertIn("오래 쓸", probs)

    def test_stem_in_product_name_is_allowed(self):
        ok = json.loads(json.dumps(GOOD)); ok["cta"] = "강력한 구성 링크에서 확인"
        self.assertEqual(verify.check_story(ok, ANALYSIS, 70, 220, "강력 흡입 청소기"), [])

    def test_needs_phrase_in_for_whom_is_allowed(self):
        ok = json.loads(json.dumps(GOOD)); ok["for_whom"][2] = "가볍게 청소하고 싶은 분"
        self.assertEqual(verify.check_story(ok, ANALYSIS, 70, 220, self.NAME), [])


class LogRegressionTests(unittest.TestCase):
    """사용자 PC 의 실제 로그(2026-11-11)에서 발견된 오탐/누락을 고정"""
    NAME = "무선 핸디 청소기 대용량 배터리 올인원 세트"

    def test_claims_copied_from_product_name_are_grounded(self):
        for c in ("대용량 배터리", "올인원 세트", "대용량 배터리 올인원 세트 등장"):
            self.assertTrue(verify._grounded(c, self.NAME), c)
        for c in ("흡입력이 강력해요", "올인원 세트로 청소 부담 덜어보세요", "30분 연속 사용"):
            self.assertFalse(verify._grounded(c, self.NAME), c)

    def test_fact_check_drops_false_positives(self):
        orig = llm.chat_json
        llm.chat_json = lambda *a, **k: {"unsupported_claims": ["대용량 배터리", "올인원 세트"],
                                         "unrelated_scenes": ["a stroller wheel"]}
        try:
            probs = verify.fact_check(GOOD, Product("1", self.NAME, 59900, "i", "u", True, True, "c"), ANALYSIS)
        finally:
            llm.chat_json = orig
        self.assertEqual(len(probs), 1)
        self.assertIn("무관한 장면", probs[0])

    def test_scene_meta_leak_and_numbers_and_cta_length(self):
        bad = json.loads(json.dumps(GOOD))
        bad["panels"][0]["scene"] = "Silhouette near a sofa, visual motif: sofa and dust"
        bad["body"] = GOOD["body"] + " 30분 쓸 수 있어."
        bad["cta"] = "가" * 31
        probs = " | ".join(verify.check_story(bad, ANALYSIS, 70, 260, self.NAME, 59900))
        self.assertIn("설명 문구", probs)
        self.assertIn("숫자", probs)
        self.assertIn("cta 는 1~30자", probs)

    def test_price_and_name_numbers_allowed(self):
        ok = json.loads(json.dumps(GOOD)); ok["body"] = GOOD["body"] + " 59,900원이야."
        self.assertEqual(verify.check_story(ok, ANALYSIS, 70, 260, self.NAME, 59900), [])

    def test_planner_accepts_with_warnings_after_soft_budget(self):
        analysis = dict(ANALYSIS)
        plans = [GOOD, GOOD, GOOD]
        calls = {"facts": 0}

        def fake(messages, **kw):
            system = messages[0]["content"]
            if "상품을 분석하는 기획자" in system:
                return analysis
            if "콘텐츠 디렉터" in system:
                return plans.pop(0)
            calls["facts"] += 1
            return {"unsupported_claims": ["흡입력이 강력해요"], "unrelated_scenes": []}
        orig = llm.chat_json
        llm.chat_json = fake
        try:
            story, _, report = planner.build_story(Product("1", self.NAME, 59900, "i", "u", True, True, "c"), "https://x.co/a")
        finally:
            llm.chat_json = orig
        self.assertEqual(calls["facts"], 2)            # LLM 판정은 2회까지만 재기획에 반영
        self.assertEqual(len(report["attempts"]), 3)   # 3번째 시도는 확정 규칙만 통과하면 채택
        self.assertEqual(report["fact_check"], "warnings")
        self.assertTrue(report["warnings"])


class ImageCheckTests(unittest.TestCase):
    def test_degenerate_images_fail(self):
        for color in ((0, 0, 0), (255, 255, 255), (200, 180, 170)):
            self.assertFalse(verify.image_basic_check(Image.new("RGB", (400, 500), color))["ok"])

    def test_detailed_image_passes(self):
        rnd = random.Random(1)
        im = Image.new("RGB", (400, 500), (240, 225, 210))
        d = ImageDraw.Draw(im)
        for _ in range(120):
            x, y = rnd.randint(0, 380), rnd.randint(0, 480)
            d.ellipse((x, y, x + rnd.randint(10, 90), y + rnd.randint(10, 90)),
                      fill=tuple(rnd.randint(40, 255) for _ in range(3)))
        self.assertTrue(verify.image_basic_check(im)["ok"])

    def test_select_best_uses_clip_ranking(self):
        rnd = random.Random(2)
        def img():
            im = Image.new("RGB", (400, 500), (240, 225, 210)); d = ImageDraw.Draw(im)
            for _ in range(100):
                x, y = rnd.randint(0, 380), rnd.randint(0, 480)
                d.ellipse((x, y, x + 60, y + 60), fill=tuple(rnd.randint(40, 255) for _ in range(3)))
            return im
        imgs = [Image.new("RGB", (400, 500), (0, 0, 0)), img(), img(), img()]
        orig = verify.clip_scores
        try:
            verify.clip_scores = lambda ims, text: [0.20, 0.31, 0.25][: len(ims)]
            r = verify.select_best(imgs, "living room floor")
        finally:
            verify.clip_scores = orig
        self.assertTrue(r["passed"])
        self.assertEqual(r["best"], 2)  # 0번(검은 이미지)은 탈락, 통과 후보 중 점수 최고
        self.assertFalse(r["semantic_verified"])  # VLM 없음


class SelectorTests(unittest.TestCase):
    def test_blocked_and_ranking(self):
        self.assertTrue(selector.is_blocked("프로바이오틱스 유산균 30포"))
        self.assertFalse(selector.is_blocked("무선 핸디 청소기"))
        mk = lambda i, n, price, rocket: Product(str(i), n, price, "img", "url", rocket, True, "c")
        items = [mk(1, "유산균 영양제 세트", 20000, True), mk(2, "접이식 수납 박스 대형", 15000, True),
                 mk(3, "초저가 케이블 정리 클립", 1000, False)]
        selector.db.is_posted = lambda _id: False
        ranked = selector.rank(items)
        self.assertEqual([p.id for p in ranked][0], "2")
        self.assertNotIn("1", [p.id for p in ranked])


class PlannerTests(unittest.TestCase):
    def _product(self):
        return Product("1", "무선 핸디 청소기 대용량 배터리 올인원 세트", 59900, "img", "url", True, True, "가전디지털")

    def test_retry_loop_with_text_and_fact_checks(self):
        bad_cjk = json.loads(json.dumps(GOOD)); bad_cjk["panels"][0]["caption"] = "沙发角落 먼지 쌓인 곳"
        plans = [bad_cjk, GOOD, GOOD, GOOD]
        facts = [{"unsupported_claims": ["흡입력이 강력해요"], "unrelated_scenes": []},
                 {"unsupported_claims": [], "unrelated_scenes": ["a stroller wheel with dust"]},
                 {"unsupported_claims": [], "unrelated_scenes": []}]
        analysis = dict(ANALYSIS, explicit_facts=["대용량 배터리"], typical_situations=["바닥 청소"])

        def fake(messages, **kw):
            system = messages[0]["content"]
            if "상품을 분석하는 기획자" in system:
                return analysis
            if "콘텐츠 디렉터" in system:
                return plans.pop(0)
            return facts.pop(0)
        orig = llm.chat_json
        llm.chat_json = fake
        try:
            story, an, report = planner.build_story(self._product(), "https://link.coupang.com/x")
        finally:
            llm.chat_json = orig
        self.assertEqual(len(report["attempts"]), 4)  # 한자 반려 -> 주장 반려 -> 무관 장면 반려 -> 통과
        self.assertLessEqual(len(story["text"]), 500)
        self.assertIn(verify.DISCLOSURE, story["text"])

    def test_risky_product_is_skipped(self):
        orig = llm.chat_json
        llm.chat_json = lambda *a, **k: dict(ANALYSIS, risk_flags=["health_claim"])
        try:
            with self.assertRaises(planner.SkipProduct):
                planner.analyze(self._product())
        finally:
            llm.chat_json = orig


if __name__ == "__main__":
    unittest.main()
