"""HTML 파싱 모듈.

검색결과 페이지와 상품 상세페이지에서 데이터를 추출한다.
parser 로직은 crawler 와 분리되어 독립적으로 테스트 가능하다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup, Tag
from loguru import logger


# ──────────────────────────────────────────────────────────────────────────────
# 데이터 클래스
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ProductItem:
    """검색결과에서 추출한 상품 정보."""
    keyword: str = ""
    search_page: int = 0
    rank_on_page: int = 0
    product_name: str = ""
    product_url: str = ""
    product_id: Optional[str] = None
    item_id: Optional[str] = None
    vendor_item_id: Optional[str] = None
    category_text: Optional[str] = None
    crawl_time: str = ""


@dataclass
class SellerObservation:
    """상품 상세페이지에서 추출한 판매자 관측 정보."""
    seller_name: Optional[str] = None
    representative_name: Optional[str] = None
    business_registration_no: Optional[str] = None
    mail_order_license_no: Optional[str] = None
    business_address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    purchase_safety_service_no: Optional[str] = None
    seller_raw_text: Optional[str] = None
    source_product_url: str = ""
    source_product_name: str = ""
    source_keyword: str = ""
    collected_at: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# 검색결과 파서
# ──────────────────────────────────────────────────────────────────────────────

COUPANG_BASE = "https://www.coupang.com"

# 검색결과 상품 카드 CSS 선택자 (여러 후보를 순서대로 시도)
SEARCH_PRODUCT_SELECTORS = [
    "li.search-product",
    "li[class*='search-product']",
    "li[class*='baby-product']",
    "div.search-product-wrap li",
    "ul.search-product-list li",
    "ul[class*='product-list'] li",
    "div[class*='product-wrap'] li",
    "ul li[class*='product']",
]

# 상품 링크 선택자
PRODUCT_LINK_SELECTORS = [
    "a.search-product-link",
    "a[class*='product-link']",
    "a[class*='baby-product-link']",
    "a[href*='/vp/products/']",
]

# 상품명 선택자
PRODUCT_NAME_SELECTORS = [
    "div.name",
    "div[class*='product-name']",
    "span.product-name",
    "dt.adUnit-string",
    "div[class*='name']",
    "span[class*='name']",
]


def parse_search_page(
    html: str,
    keyword: str,
    page_num: int,
    base_url: str = COUPANG_BASE,
) -> List[ProductItem]:
    """검색결과 HTML 에서 상품 목록을 파싱한다."""
    soup = BeautifulSoup(html, "lxml")
    products: List[ProductItem] = []

    # 1차: CSS 선택자로 카드 목록 찾기
    product_cards: List[Tag] = []
    for selector in SEARCH_PRODUCT_SELECTORS:
        cards = soup.select(selector)
        if cards:
            product_cards = cards
            logger.debug(f"검색결과 선택자 적중: '{selector}' ({len(cards)}개)")
            break

    # 2차 fallback: /vp/products/ 링크를 직접 수집 후 부모 li/div 로 역추적
    if not product_cards:
        logger.debug("선택자 실패 → /vp/products/ 링크 직접 탐색으로 전환")
        product_cards = _fallback_find_cards(soup)

    if not product_cards:
        logger.warning(f"검색결과 카드를 찾지 못했습니다. keyword={keyword}, page={page_num}")
        # 디버그용: 페이지 제목과 ul/li 구조 출력
        title = soup.find("title")
        logger.debug(f"페이지 제목: {title.get_text() if title else 'N/A'}")
        return products

    for rank, card in enumerate(product_cards, start=1):
        try:
            item = _parse_single_product_card(card, keyword, page_num, rank, base_url)
            if item:
                products.append(item)
        except Exception as exc:
            logger.warning(f"상품 카드 파싱 오류 (rank={rank}): {exc}")

    return products


def _fallback_find_cards(soup: BeautifulSoup) -> List[Tag]:
    """CSS 선택자 실패 시 /vp/products/ 링크로 상품 카드를 역추적한다."""
    seen_urls: set = set()
    cards: List[Tag] = []

    for a_tag in soup.find_all("a", href=re.compile(r"/vp/products/\d+")):
        href = a_tag.get("href", "")
        if href in seen_urls:
            continue
        seen_urls.add(href)

        # 가장 가까운 li 또는 div 부모를 카드로 사용
        parent = a_tag.find_parent("li") or a_tag.find_parent("div")
        if parent and parent not in cards:
            cards.append(parent)

    logger.debug(f"fallback 탐색: {len(cards)}개 카드 발견")
    return cards


def _parse_single_product_card(
    card: Tag,
    keyword: str,
    page_num: int,
    rank: int,
    base_url: str,
) -> Optional[ProductItem]:
    """상품 카드 하나에서 ProductItem 을 추출한다."""
    # 광고 상품 스킵 (ad 클래스 또는 data-ad 속성)
    card_classes = " ".join(card.get("class", []))
    if "ad-product" in card_classes or card.get("data-ad"):
        return None

    # 상품 링크 추출
    link_tag: Optional[Tag] = None
    for selector in PRODUCT_LINK_SELECTORS:
        link_tag = card.select_one(selector)
        if link_tag:
            break

    if not link_tag:
        return None

    href = link_tag.get("href", "")
    if not href or "/vp/products/" not in href:
        return None

    product_url = urljoin(base_url, href) if href.startswith("/") else href

    # 상품명 추출
    product_name = ""
    for selector in PRODUCT_NAME_SELECTORS:
        name_tag = card.select_one(selector)
        if name_tag:
            product_name = name_tag.get_text(strip=True)
            break

    # 식별자 추출 (URL 파싱 또는 data 속성)
    product_id = _extract_product_id_from_url(product_url)
    item_id = card.get("data-item-id") or _extract_param(product_url, "itemId")
    vendor_item_id = card.get("data-vendor-item-id") or _extract_param(
        product_url, "vendorItemId"
    )

    # 카테고리
    category_tag = card.select_one("[class*='category']")
    category_text = category_tag.get_text(strip=True) if category_tag else None

    return ProductItem(
        keyword=keyword,
        search_page=page_num,
        rank_on_page=rank,
        product_name=product_name,
        product_url=product_url,
        product_id=product_id,
        item_id=item_id,
        vendor_item_id=vendor_item_id,
        category_text=category_text,
    )


def _extract_product_id_from_url(url: str) -> Optional[str]:
    """URL 에서 상품 ID 를 추출한다. /vp/products/{product_id}"""
    match = re.search(r"/vp/products/(\d+)", url)
    return match.group(1) if match else None


def _extract_param(url: str, param: str) -> Optional[str]:
    """URL 쿼리 파라미터에서 값을 추출한다."""
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        values = params.get(param, [])
        return values[0] if values else None
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# 상품 상세페이지 판매자 정보 파서
# ──────────────────────────────────────────────────────────────────────────────

# 판매자 정보 섹션 선택자 (여러 후보를 순서대로 시도)
SELLER_SECTION_SELECTORS = [
    "div.seller-info",
    "div[class*='seller-info']",
    "div[class*='vendor-info']",
    "div.prod-seller-info",
    "table[class*='seller']",
    "#vendor-info",
]

# 라벨 → 필드 매핑 (부분 일치 허용)
LABEL_FIELD_MAP: Dict[str, str] = {
    "상호": "seller_name",
    "대표자": "representative_name",
    "사업장 소재지": "business_address",
    "사업장소재지": "business_address",
    "소재지": "business_address",
    "e-mail": "email",
    "이메일": "email",
    "email": "email",
    "연락처": "phone",
    "전화": "phone",
    "통신판매업": "mail_order_license_no",
    "사업자번호": "business_registration_no",
    "사업자 번호": "business_registration_no",
    "사업자등록번호": "business_registration_no",
    "구매안전": "purchase_safety_service_no",
}


def parse_seller_info(
    html: str,
    product_url: str = "",
    product_name: str = "",
    keyword: str = "",
) -> Optional[SellerObservation]:
    """상품 상세페이지 HTML 에서 판매자 정보를 파싱한다."""
    soup = BeautifulSoup(html, "lxml")

    seller_section = _find_seller_section(soup)
    if not seller_section:
        logger.debug(f"판매자 정보 섹션을 찾지 못했습니다: {product_url}")
        return None

    raw_text = seller_section.get_text(separator="\n", strip=True)
    obs = SellerObservation(
        seller_raw_text=raw_text,
        source_product_url=product_url,
        source_product_name=product_name,
        source_keyword=keyword,
    )

    # 라벨 기반 파싱 (테이블 구조)
    _parse_by_table(seller_section, obs)

    # 라벨 기반 파싱 (dl/dt/dd 구조)
    if not obs.seller_name:
        _parse_by_dl(seller_section, obs)

    # 라벨 기반 파싱 (div 구조 - 텍스트 검색)
    if not obs.seller_name:
        _parse_by_text_search(seller_section, obs)

    # 상호/대표자 분리
    if obs.seller_name:
        obs.seller_name, obs.representative_name = _split_seller_representative(
            obs.seller_name, obs.representative_name
        )

    return obs


def _find_seller_section(soup: BeautifulSoup) -> Optional[Tag]:
    """판매자 정보 섹션 태그를 찾는다."""
    for selector in SELLER_SECTION_SELECTORS:
        section = soup.select_one(selector)
        if section:
            logger.debug(f"판매자 섹션 선택자 적중: '{selector}'")
            return section

    # 텍스트 기반 탐색 - "판매자 정보", "사업자 정보" 포함 섹션
    for tag in soup.find_all(["div", "section", "table"]):
        text = tag.get_text()
        if any(kw in text for kw in ["사업자번호", "통신판매업", "대표자", "사업장 소재지"]):
            # 너무 큰 섹션은 제외
            if len(text) < 3000:
                return tag

    return None


def _parse_by_table(section: Tag, obs: SellerObservation) -> None:
    """테이블(tr/th/td) 구조에서 라벨-값 쌍을 추출한다."""
    rows = section.find_all("tr")
    for row in rows:
        th = row.find("th")
        td = row.find("td")
        if not th or not td:
            continue
        label = th.get_text(strip=True)
        value = td.get_text(separator=" ", strip=True)
        _assign_field(obs, label, value)


def _parse_by_dl(section: Tag, obs: SellerObservation) -> None:
    """dl/dt/dd 구조에서 라벨-값 쌍을 추출한다."""
    dt_tags = section.find_all("dt")
    for dt in dt_tags:
        dd = dt.find_next_sibling("dd")
        if not dd:
            continue
        label = dt.get_text(strip=True)
        value = dd.get_text(separator=" ", strip=True)
        _assign_field(obs, label, value)


def _parse_by_text_search(section: Tag, obs: SellerObservation) -> None:
    """텍스트 기반으로 라벨:값 패턴을 찾는다."""
    text = section.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    for i, line in enumerate(lines):
        for label, field_name in LABEL_FIELD_MAP.items():
            if label in line:
                # 같은 줄에 ':' 이후 값이 있는지 확인
                parts = re.split(r"[:：]", line, maxsplit=1)
                if len(parts) == 2:
                    value = parts[1].strip()
                    if value:
                        _safe_set(obs, field_name, value)
                        break
                # 다음 줄이 값인지 확인
                elif i + 1 < len(lines):
                    next_line = lines[i + 1]
                    if not any(k in next_line for k in LABEL_FIELD_MAP):
                        _safe_set(obs, field_name, next_line)
                        break


def _assign_field(obs: SellerObservation, label: str, value: str) -> None:
    """라벨 문자열에 대응하는 SellerObservation 필드에 값을 설정한다."""
    label_lower = label.lower().strip()
    for key, field_name in LABEL_FIELD_MAP.items():
        if key.lower() in label_lower:
            _safe_set(obs, field_name, value)
            return


def _safe_set(obs: SellerObservation, field_name: str, value: str) -> None:
    """이미 값이 있으면 덮어쓰지 않는다 (첫 번째 값 우선)."""
    current = getattr(obs, field_name, None)
    if current is None and value:
        setattr(obs, field_name, value.strip() or None)


def _split_seller_representative(
    combined: str,
    existing_representative: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """'상호 / 대표자' 형식의 문자열을 분리한다."""
    if existing_representative:
        return combined, existing_representative

    # '/' 또는 '／' 기준으로 분리
    for sep in [" / ", "／", "/"]:
        if sep in combined:
            parts = [p.strip() for p in combined.split(sep, 1)]
            if len(parts) == 2 and parts[0] and parts[1]:
                return parts[0], parts[1]

    return combined, None
