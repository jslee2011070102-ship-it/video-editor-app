# 쿠팡 전체 판매자 DB 구축 크롤러

쿠팡 검색결과를 기반으로 상품을 수집하고, 각 상품 상세페이지 하단의 **판매자 정보**를 추출하여 **판매자 DB**를 구축하는 Python 크롤러입니다.

---

## 목차

1. [설치 방법](#설치-방법)
2. [실행 방법](#실행-방법)
3. [입력 파일 형식](#입력-파일-형식)
4. [출력 파일 설명](#출력-파일-설명)
5. [수집 필드 설명](#수집-필드-설명)
6. [주의사항](#주의사항)
7. [문제 해결 가이드](#문제-해결-가이드)
8. [자주 발생하는 실패 유형](#자주-발생하는-실패-유형)
9. [구조 변경 시 parser 수정 포인트](#구조-변경-시-parser-수정-포인트)
10. [실패 재시도 방법](#실패-재시도-방법)

---

## 설치 방법

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. Playwright 브라우저 설치

```bash
playwright install chromium
```

### 3. 환경변수 설정 (선택)

```bash
cp .env .env.local
# .env.local 편집 (프록시, 사용자 에이전트 등)
```

---

## 실행 방법

### 기본 실행 (키워드 파일 사용)

```bash
cd coupang_seller_crawler
python -m src.main --keywords config/keywords.txt --max-pages 20
```

### 단일 키워드 실행

```bash
python -m src.main --keyword "청소용품" --max-pages 5
```

### 헤드리스 모드 끄기 (브라우저 창 표시)

```bash
python -m src.main --keywords config/keywords.txt --headless false
```

### resume 모드 (이미 수집된 항목 건너뜀)

```bash
python -m src.main --keywords config/keywords.txt --resume
```

### 검색만 수행 (상품 상세 진입 안 함)

```bash
python -m src.main --keywords config/keywords.txt --only-search
```

### 상품 상세만 수행 (DB 에 저장된 URL 사용)

```bash
python -m src.main --only-product
```

### 실패 목록 재시도

```bash
python -m src.main --retry-failed
```

### 내보내기 포맷 지정

```bash
python -m src.main --keywords config/keywords.txt --export csv excel sqlite
```

### 수집 상품 수 제한

```bash
python -m src.main --keyword "청소용품" --limit-products 100
```

---

## 전체 옵션

```
python -m src.main [OPTIONS]

키워드 옵션 (둘 중 하나):
  --keywords FILE       키워드 목록 파일 경로
  --keyword KEYWORD     단일 키워드 직접 입력

크롤링 옵션:
  --max-pages N         키워드당 최대 검색 페이지 수
  --headless true|false 헤드리스 모드 (기본: true)
  --resume              이미 수집된 상품 건너뜀

실행 모드:
  --only-search         검색 수집만 수행
  --only-product        상품 상세 수집만 수행
  --retry-failed        실패 목록 재시도

저장 옵션:
  --export csv excel sqlite  내보낼 포맷 (복수 선택 가능)

기타:
  --limit-products N    키워드당 최대 수집 상품 수 (0=무제한)
  --config FILE         설정 파일 경로 (기본: config/settings.yaml)
```

---

## 입력 파일 형식

### config/keywords.txt

한 줄에 키워드 하나, `#` 으로 시작하는 줄은 주석입니다.

```text
# 청소용품 카테고리
청소용품
욕실세정제
주방세정제
세탁세제
```

### config/settings.yaml

```yaml
max_pages_per_keyword: 30   # 키워드당 최대 페이지
headless: true              # 헤드리스 모드
min_delay_sec: 2            # 최소 딜레이(초)
max_delay_sec: 5            # 최대 딜레이(초)
retry_count: 3              # 재시도 횟수
concurrency: 2              # 동시 실행 수
timeout_sec: 25             # 페이지 타임아웃(초)

export_csv: true
export_excel: true
export_sqlite: true
resume_mode: true
save_html_snapshot: true    # HTML 원본 저장 (구조 변경 대비)
```

---

## 출력 파일 설명

실행 후 `data/` 디렉토리에 다음 파일들이 생성됩니다.

| 파일 | 위치 | 설명 |
|------|------|------|
| `products.csv` | `data/exports/` | 검색에서 수집된 상품 목록 |
| `products.xlsx` | `data/exports/` | 상동 (Excel) |
| `seller_observations.csv` | `data/exports/` | 상품별 판매자 관측 정보 |
| `seller_observations.xlsx` | `data/exports/` | 상동 (Excel) |
| `sellers_master.csv` | `data/exports/` | 통합 판매자 DB (중복 제거) |
| `sellers_master.xlsx` | `data/exports/` | 상동 (Excel) |
| `failed_jobs.csv` | `data/exports/` | 실패한 작업 목록 |
| `stats_report.txt` | `data/exports/` | 수집 통계 리포트 |
| `coupang_sellers.db` | `data/processed/` | SQLite 전체 데이터베이스 |
| `*.html` | `data/raw/` | 상품 상세페이지 HTML 스냅샷 |
| `crawler_YYYY-MM-DD.log` | `data/logs/` | 크롤링 로그 |

---

## 수집 필드 설명

### products (상품 정보)

| 필드 | 설명 |
|------|------|
| `keyword` | 검색에 사용된 키워드 |
| `search_page` | 검색 결과 페이지 번호 |
| `rank_on_page` | 해당 페이지 내 상품 순위 |
| `product_name` | 상품명 |
| `product_url` | 상품 상세페이지 URL |
| `product_id` | 쿠팡 상품 ID |
| `item_id` | 아이템 ID |
| `vendor_item_id` | 판매자 아이템 ID |
| `category_text` | 카테고리 텍스트 (가능한 경우) |
| `crawl_time` | 수집 시각 |

### seller_observations (판매자 관측 정보)

| 필드 | 설명 |
|------|------|
| `seller_name` | 상호명 |
| `representative_name` | 대표자명 |
| `business_registration_no` | 사업자번호 (숫자만) |
| `mail_order_license_no` | 통신판매업 신고번호 |
| `business_address` | 사업장 소재지 |
| `email` | 이메일 |
| `phone` | 연락처 |
| `purchase_safety_service_no` | 구매안전 서비스 번호 |
| `seller_raw_text` | 원본 텍스트 (파싱 실패 대비) |
| `source_product_url` | 출처 상품 URL |
| `source_keyword` | 출처 검색 키워드 |
| `email_is_valid` | 이메일 형식 유효 여부 |

### sellers_master (통합 판매자 DB)

| 필드 | 설명 |
|------|------|
| `seller_uid` | 시스템 내부 고유 ID |
| `seller_name` | 상호명 |
| `representative_name` | 대표자명 |
| `business_registration_no` | 사업자번호 |
| `mail_order_license_no` | 통신판매업 신고번호 |
| `business_address` | 사업장 소재지 |
| `email` | 이메일 |
| `phone` | 연락처 |
| `first_seen_at` | 최초 수집 시각 |
| `last_seen_at` | 최근 수집 시각 |
| `product_count` | 발견된 상품 수 |
| `keyword_count` | 관련 키워드 수 |
| `source_count` | 수집된 URL 수 |

---

## 주의사항

1. **과도한 수집 금지**: 쿠팡의 이용약관을 준수하세요. 과도한 요청은 차단될 수 있습니다.
2. **딜레이 설정**: `min_delay_sec` / `max_delay_sec` 를 최소 2~5초로 유지하세요.
3. **개인정보 보호**: 수집된 개인정보(이름, 연락처 등)는 관련 법령을 준수하여 사용하세요.
4. **구조 변경 대응**: 쿠팡은 수시로 HTML 구조를 변경합니다. `save_html_snapshot: true` 설정으로 원본을 보존하세요.
5. **운영 환경**: 장시간 운영 시 IP 차단에 주의하세요. 필요시 프록시 설정을 활용하세요.

---

## 문제 해결 가이드

### 브라우저 설치 오류
```bash
playwright install chromium
# 또는
playwright install --with-deps chromium
```

### 수집이 되지 않을 때

1. `--headless false` 로 브라우저를 직접 확인하세요.
2. HTML 스냅샷(`data/raw/`)을 열어 페이지 구조를 확인하세요.
3. 로그(`data/logs/`)에서 오류 메시지를 확인하세요.

### 판매자 정보가 비어 있을 때

쿠팡은 JavaScript 로 동적 렌더링되는 경우가 있습니다.
`product_crawler.py` 의 대기 시간(`asyncio.sleep(1.5)`)을 늘려 보세요.

### 차단/캡챠 발생 시

- `min_delay_sec` / `max_delay_sec` 를 늘리세요 (예: 5~10초).
- VPN 또는 프록시를 사용하세요 (`.env` 파일 설정).
- 잠시 후 재실행하세요.

---

## 자주 발생하는 실패 유형

| 오류 유형 | 원인 | 해결책 |
|-----------|------|--------|
| `HTTP 403` | IP 차단 또는 봇 탐지 | 딜레이 증가, 프록시 사용 |
| `TimeoutError` | 네트워크 느림 또는 JS 로딩 대기 | `timeout_sec` 증가 |
| `판매자 정보 섹션 없음` | 상품 상세 구조 변경 또는 판매자가 없음 | parser 선택자 확인 |
| `응답 없음` | 네트워크 오류 | 재시도 (`--retry-failed`) |
| `사업자번호 길이 오류` | 표기 형식 변경 | normalizer.py 수정 |

---

## 구조 변경 시 parser 수정 포인트

쿠팡의 HTML 구조가 변경된 경우 `src/parser.py` 를 수정하세요.

### 검색결과 파서

`parser.py` 상단의 선택자 상수를 수정합니다:

```python
# 상품 카드 목록 선택자
SEARCH_PRODUCT_SELECTORS = [
    "li.search-product",           # ← 여기 수정
    "li[class*='search-product']",
    ...
]

# 상품 링크 선택자
PRODUCT_LINK_SELECTORS = [
    "a.search-product-link",       # ← 여기 수정
    ...
]

# 상품명 선택자
PRODUCT_NAME_SELECTORS = [
    "div.name",                    # ← 여기 수정
    ...
]
```

### 판매자 정보 파서

판매자 섹션 선택자를 수정합니다:

```python
SELLER_SECTION_SELECTORS = [
    "div.seller-info",             # ← 여기 수정
    "div[class*='seller-info']",
    ...
]
```

라벨-필드 매핑을 수정합니다:

```python
LABEL_FIELD_MAP: Dict[str, str] = {
    "상호": "seller_name",         # ← 라벨 텍스트가 변경되면 여기 수정
    "대표자": "representative_name",
    ...
}
```

> **팁**: `save_html_snapshot: true` 설정 후 수집된 HTML 파일을 열어 새로운 클래스명 또는 라벨 텍스트를 확인하세요.

---

## 실패 재시도 방법

### 방법 1: CLI 플래그 사용

```bash
python -m src.main --retry-failed
```

DB 의 `failed_jobs` 테이블에 있는 미해결 항목을 자동으로 재시도합니다.

### 방법 2: failed_jobs.csv 에서 수동 재시도

```bash
# failed_jobs.csv 확인
cat data/exports/failed_jobs.csv

# SQLite 에서 직접 조회
sqlite3 data/processed/coupang_sellers.db \
  "SELECT * FROM failed_jobs WHERE resolved = 0 LIMIT 10;"
```

### 방법 3: 특정 키워드 재실행

```bash
python -m src.main --keyword "청소용품" --max-pages 5 --resume
```

`--resume` 옵션을 사용하면 이미 수집된 상품은 건너뛰고 새로 추가된 것만 수집합니다.

---

## 디렉토리 구조

```
coupang_seller_crawler/
│
├── README.md
├── requirements.txt
├── .env
├── config/
│   ├── settings.yaml       # 크롤링 설정
│   └── keywords.txt        # 검색 키워드 목록
│
├── data/
│   ├── raw/                # HTML 스냅샷
│   ├── processed/          # SQLite DB
│   ├── exports/            # CSV / Excel / 리포트
│   └── logs/               # 로그 파일
│
├── src/
│   ├── main.py             # CLI 진입점
│   ├── config_loader.py    # 설정 로딩
│   ├── browser.py          # Playwright 관리
│   ├── search_crawler.py   # 검색결과 크롤러
│   ├── product_crawler.py  # 상품 상세 크롤러
│   ├── parser.py           # HTML 파서 (독립 모듈)
│   ├── normalizer.py       # 데이터 정규화
│   ├── deduplicator.py     # 중복 제거 / 통합
│   ├── storage.py          # SQLite 저장
│   ├── exporter.py         # CSV / Excel 내보내기
│   └── utils.py            # 공통 유틸리티
│
└── tests/
    ├── test_parser.py
    ├── test_normalizer.py
    └── test_deduplicator.py
```

---

## 테스트 실행

```bash
cd coupang_seller_crawler
pip install pytest
pytest tests/ -v
```

---

## 기술 스택

- **Python 3.11+**
- **Playwright** - 브라우저 자동화
- **BeautifulSoup4 / lxml** - HTML 파싱
- **pandas** - 데이터 처리 및 CSV/Excel 내보내기
- **SQLite** - 로컬 데이터베이스
- **openpyxl** - Excel 파일 생성
- **tenacity** - 재시도 로직
- **loguru** - 로깅
