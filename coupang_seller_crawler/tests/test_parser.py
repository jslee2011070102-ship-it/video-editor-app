"""parser.py 단위 테스트.

실서버 의존 없이 HTML 샘플로 파서를 테스트한다.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from src.parser import (
    ProductItem,
    SellerObservation,
    _extract_product_id_from_url,
    _split_seller_representative,
    parse_search_page,
    parse_seller_info,
)


# ──────────────────────────────────────────────────────────────────────────────
# 헬퍼: 테스트용 HTML 생성
# ──────────────────────────────────────────────────────────────────────────────

def make_search_html(products: list[dict]) -> str:
    """검색결과 HTML 샘플을 생성한다."""
    cards = ""
    for p in products:
        cards += f"""
        <li class="search-product">
            <a class="search-product-link" href="{p['href']}">
                <div class="name">{p['name']}</div>
            </a>
        </li>
        """
    return f"""
    <html><body>
    <ul class="search-product-list">
        {cards}
    </ul>
    </body></html>
    """


def make_seller_html(
    seller: str = "주식회사 테스트 / 홍길동",
    address: str = "서울시 강남구 테헤란로 123",
    email: str = "test@example.com",
    phone: str = "02-1234-5678",
    biz_no: str = "123-45-67890",
    license_no: str = "서울강남-2023-0001",
) -> str:
    """상품 상세페이지 판매자 정보 HTML 샘플을 생성한다."""
    return f"""
    <html><body>
    <div class="seller-info">
        <table>
            <tr><th>상호/대표자</th><td>{seller}</td></tr>
            <tr><th>사업장 소재지</th><td>{address}</td></tr>
            <tr><th>e-mail</th><td>{email}</td></tr>
            <tr><th>연락처</th><td>{phone}</td></tr>
            <tr><th>사업자번호</th><td>{biz_no}</td></tr>
            <tr><th>통신판매업 신고번호</th><td>{license_no}</td></tr>
        </table>
    </div>
    </body></html>
    """


# ──────────────────────────────────────────────────────────────────────────────
# 검색결과 파서 테스트
# ──────────────────────────────────────────────────────────────────────────────

class TestSearchPageParser:

    def test_parse_basic_products(self):
        """기본 상품 목록 파싱."""
        html = make_search_html([
            {"href": "/vp/products/12345?itemId=111", "name": "청소용품 A"},
            {"href": "/vp/products/67890?itemId=222", "name": "청소용품 B"},
        ])
        products = parse_search_page(html, keyword="청소용품", page_num=1)
        assert len(products) == 2
        assert products[0].product_name == "청소용품 A"
        assert products[1].product_name == "청소용품 B"

    def test_parse_product_id_from_url(self):
        """URL 에서 product_id 추출."""
        html = make_search_html([
            {"href": "/vp/products/99999?itemId=333", "name": "테스트 상품"},
        ])
        products = parse_search_page(html, keyword="test", page_num=1)
        assert products[0].product_id == "99999"

    def test_parse_keyword_and_page(self):
        """keyword 와 search_page 가 올바르게 설정됨."""
        html = make_search_html([
            {"href": "/vp/products/11111", "name": "상품1"},
        ])
        products = parse_search_page(html, keyword="세탁세제", page_num=3)
        assert products[0].keyword == "세탁세제"
        assert products[0].search_page == 3

    def test_parse_rank_on_page(self):
        """페이지 내 순위가 1부터 시작함."""
        html = make_search_html([
            {"href": "/vp/products/1", "name": "1등"},
            {"href": "/vp/products/2", "name": "2등"},
            {"href": "/vp/products/3", "name": "3등"},
        ])
        products = parse_search_page(html, keyword="테스트", page_num=1)
        assert products[0].rank_on_page == 1
        assert products[1].rank_on_page == 2
        assert products[2].rank_on_page == 3

    def test_empty_page_returns_empty_list(self):
        """상품이 없는 페이지는 빈 리스트 반환."""
        html = "<html><body><div>결과 없음</div></body></html>"
        products = parse_search_page(html, keyword="존재하지않는키워드xyz", page_num=1)
        assert products == []

    def test_skip_invalid_href(self):
        """유효하지 않은 href 는 건너뜀."""
        html = """
        <html><body>
        <ul class="search-product-list">
            <li class="search-product">
                <a class="search-product-link" href="/some/other/path">
                    <div class="name">잘못된 링크 상품</div>
                </a>
            </li>
        </ul>
        </body></html>
        """
        products = parse_search_page(html, keyword="테스트", page_num=1)
        assert len(products) == 0


# ──────────────────────────────────────────────────────────────────────────────
# 판매자 정보 파서 테스트
# ──────────────────────────────────────────────────────────────────────────────

class TestSellerInfoParser:

    def test_parse_basic_seller_info(self):
        """기본 판매자 정보 파싱."""
        html = make_seller_html()
        obs = parse_seller_info(html, product_url="https://test.com/product/1")
        assert obs is not None
        assert obs.business_address == "서울시 강남구 테헤란로 123"
        assert obs.email == "test@example.com"
        assert obs.phone == "02-1234-5678"

    def test_parse_seller_name_split(self):
        """상호/대표자 분리 파싱."""
        html = make_seller_html(seller="주식회사 세컨드로잉 / 유호용")
        obs = parse_seller_info(html)
        assert obs is not None
        assert obs.seller_name == "주식회사 세컨드로잉"
        assert obs.representative_name == "유호용"

    def test_parse_business_no(self):
        """사업자번호 파싱."""
        html = make_seller_html(biz_no="123-45-67890")
        obs = parse_seller_info(html)
        assert obs is not None
        assert obs.business_registration_no == "123-45-67890"

    def test_parse_mail_order_license(self):
        """통신판매업 신고번호 파싱."""
        html = make_seller_html(license_no="제2023-서울강남-1234호")
        obs = parse_seller_info(html)
        assert obs is not None
        assert obs.mail_order_license_no == "제2023-서울강남-1234호"

    def test_no_seller_section_returns_none(self):
        """판매자 섹션이 없는 HTML 은 None 반환."""
        html = "<html><body><p>상품 설명만 있는 페이지</p></body></html>"
        obs = parse_seller_info(html)
        assert obs is None

    def test_source_product_url_preserved(self):
        """source_product_url 이 올바르게 보존됨."""
        url = "https://www.coupang.com/vp/products/12345"
        html = make_seller_html()
        obs = parse_seller_info(html, product_url=url)
        assert obs is not None
        assert obs.source_product_url == url

    def test_raw_text_captured(self):
        """seller_raw_text 에 원본 텍스트가 담김."""
        html = make_seller_html(seller="테스트회사 / 김철수")
        obs = parse_seller_info(html)
        assert obs is not None
        assert obs.seller_raw_text is not None
        assert len(obs.seller_raw_text) > 0


# ──────────────────────────────────────────────────────────────────────────────
# 헬퍼 함수 테스트
# ──────────────────────────────────────────────────────────────────────────────

class TestHelpers:

    def test_extract_product_id_normal(self):
        assert _extract_product_id_from_url(
            "https://www.coupang.com/vp/products/123456789"
        ) == "123456789"

    def test_extract_product_id_with_params(self):
        assert _extract_product_id_from_url(
            "https://www.coupang.com/vp/products/987654321?itemId=111&vendorItemId=222"
        ) == "987654321"

    def test_extract_product_id_invalid_url(self):
        assert _extract_product_id_from_url("https://www.coupang.com/search") is None

    def test_split_seller_representative_slash(self):
        name, rep = _split_seller_representative("주식회사 ABC / 홍길동", None)
        assert name == "주식회사 ABC"
        assert rep == "홍길동"

    def test_split_seller_representative_no_slash(self):
        name, rep = _split_seller_representative("단일회사명", None)
        assert name == "단일회사명"
        assert rep is None

    def test_split_seller_representative_existing_rep(self):
        """이미 대표자가 있으면 분리하지 않음."""
        name, rep = _split_seller_representative("회사명 / 다른사람", "이미있는대표자")
        assert rep == "이미있는대표자"

    def test_split_seller_representative_full_width_slash(self):
        """전각 슬래시 분리."""
        name, rep = _split_seller_representative("회사명／대표자명", None)
        assert name == "회사명"
        assert rep == "대표자명"
