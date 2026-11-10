# threads-coupang-bot (스토리 캐러셀 버전)

쿠팡 파트너스 상품 1개로 **6장짜리 스토리 캐러셀 + 본문 + 제휴 링크**를 만들어 Threads 에 올립니다.

| 장 | 내용 | 만드는 방법 |
|---|---|---|
| 1 | 표지(공감 제목 + 상황 부제) | 로컬 GPU(SDXL) 만화 컷 + Pillow 한글 |
| 2~3 | 불편이 심해지는 순간 / 해결책을 찾아보는 장면 | 로컬 GPU(SDXL) 만화 컷 + Pillow 한글 |
| 4 | 상품 등장 (이름/가격/배송) | **실제 상품 사진** 누끼 + 스티커 효과 (AI 가 상품을 그리지 않음) |
| 5 | 이런 분께 맞을 거예요 (상황 기준 3가지) | Pillow |
| 6 | 구매 안내 + 가격 + 파트너스 고지 | Pillow |

## 설계 원칙
- 1~3장은 **가상의 연출 상황**이며 이미지에 "AI 생성 일러스트 · 연출 상황" 표기가 들어갑니다.
- 실존 인물/유명인, '직접 써봤다/후기/내돈내산' 같은 거짓 경험담, 과장 표현은 프롬프트와 코드 검증으로 차단합니다.
- 상품 설명은 상품 데이터(이름, 가격, 배송)에 있는 사실만 사용합니다.
- 쿠팡 파트너스 고지 문구는 본문과 6장에 코드가 자동 삽입합니다.

## 실행
```bat
.venv\Scripts\python main.py check
.venv\Scripts\python main.py post --demo --no-image     :: 스토리 텍스트만
.venv\Scripts\python main.py post --demo                :: 키 없이 6장 전체 생성 (out\ 에 저장)
.venv\Scripts\python main.py post --keyword "무선 청소기" --dry-run
.venv\Scripts\python main.py post --keyword "무선 청소기"
```

## 폴더 구조 (압축을 풀면 이 구조 그대로여야 합니다)
```
main.py  pyproject.toml  .env  README.md
bot\  __init__.py config.py coupang.py copywriter.py imagegen.py compose.py hosting.py threads.py db.py
```

## 선택 설치
- `rembg`: 흰 배경이 아닌 상품 사진도 누끼를 따고 싶을 때 (기본은 흰 배경 상품컷용 내장 누끼)
