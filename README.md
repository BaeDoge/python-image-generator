# threads-coupang-bot — 자율 기획 + 검증 파이프라인

쿠팡 파트너스 상품을 **자동으로 고르고**, LLM 이 **컨셉·스토리·이미지 프롬프트를 스스로 기획**한 뒤,
**텍스트/이미지를 검증**해서 통과한 것만 6장짜리 Threads 캐러셀로 만듭니다. `.env` 에 상품명·프롬프트를 적을 필요가 없습니다.

```
selector(안전 카테고리 날짜 순환 + 규제 상품 차단 + 점수화)
  → planner.analyze  상품 분석 (종류/상품명 명시 사실/상황/시각 소재/위험 플래그)
  → planner.plan     컨셉(공감 포인트·말투·그림 스타일) + 6장 스토리보드 + 장면 프롬프트
  → verify(텍스트)    한자/외국 문자 혼입, 금지 표현, 길이, 반복, 영어 장면, 소재 포함 + LLM 사실/무관 장면 검수 → 위반 시 피드백 재기획
  → imagegen         장면당 N장 후보 생성 (SDXL, DPM++ Karras, fp16-fix VAE)
  → verify(이미지)    기본 품질(어둡/흰/단색/디테일) → [VLM 있으면 의미 검증] → CLIP 점수 최고 선택 → 탈락 시 단순화 장면 재생성
  → compose          단어 단위 균형 줄바꿈 + 상품 누끼 스티커(실제 상품 사진) + 생성 배경
  → verify.json 저장 → 검증 실패가 있으면 게시 차단(--force 로만 강행) → Threads 캐러셀
```

## 실행
```bat
.venv\Scripts\python main.py check
.venv\Scripts\python main.py post --demo --no-image     :: 키 없이 기획+텍스트 검증만
.venv\Scripts\python main.py post --demo                :: 키 없이 6장 전체 생성 (게시 안 함)
.venv\Scripts\python main.py post --dry-run             :: 오늘의 상품 자동 선택, 생성만
.venv\Scripts\python main.py post                       :: 자동 선택 + 검증 통과 시 게시
```
`--keyword`, `--category` 는 선택 사항입니다. 결과 폴더의 `verify.json` 에 모든 검증 점수가 남습니다.

## 검증 한계 (솔직하게)
- **VLM(이미지를 볼 수 있는 모델)이 없으면** 이미지 의미 검증은 CLIP 순위 + 기본 품질 검사까지만 합니다.
  `.env` 에 `VLM_BASE_URL` 을 설정하면 "장면과 일치/글자 포함/형태 일그러짐" 판정이 추가됩니다.
- LLM 사실 검수는 완벽하지 않습니다. 처음 며칠은 `--dry-run` 결과를 눈으로 확인하세요.
- 카테고리 ID(`bot/selector.py` 의 `SAFE_CATEGORIES`)는 실제 API 응답으로 확인이 필요합니다. 안 맞는 카테고리는 건너뜁니다.

## 테스트 (GPU/네트워크 불필요)
```bat
.venv\Scripts\python -m unittest discover -s tests -v
```

## 정책 메모
- 1~3장은 가상의 **연출 상황**이며 이미지에 "AI 생성 일러스트 · 연출 상황"이 표기됩니다.
- 실존 인물/유명인, 거짓 경험담(직접 써봤다/후기), 과장 표현은 프롬프트와 코드로 차단합니다.
- 의료/건강기능/성인/주류 등 규제 상품은 자동 선택에서 제외됩니다.
- 쿠팡 파트너스 고지 문구는 본문과 6장에 코드가 자동 삽입합니다.
