"""deduplicator.py 단위 테스트."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from src.deduplicator import (
    SellerMaster,
    _best_value,
    _make_group_key,
    build_seller_master,
    deduplicate_products,
)
from src.parser import ProductItem, SellerObservation


# ──────────────────────────────────────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────────────────────────────────────

def make_obs(
    biz_no: str = None,
    seller_name: str = None,
    rep: str = None,
    phone: str = None,
    email: str = None,
    address: str = None,
    product_url: str = "",
    keyword: str = "",
    collected_at: str = "2024-01-01T00:00:00",
) -> SellerObservation:
    return SellerObservation(
        business_registration_no=biz_no,
        seller_name=seller_name,
        representative_name=rep,
        phone=phone,
        email=email,
        business_address=address,
        source_product_url=product_url,
        source_keyword=keyword,
        collected_at=collected_at,
    )


def make_product(product_id: str, url: str = "", keyword: str = "") -> ProductItem:
    return ProductItem(
        product_id=product_id,
        product_url=url or f"https://coupang.com/vp/products/{product_id}",
        product_name=f"상품 {product_id}",
        keyword=keyword,
    )


# ──────────────────────────────────────────────────────────────────────────────
# 그룹 키 테스트
# ──────────────────────────────────────────────────────────────────────────────

class TestMakeGroupKey:

    def test_biz_no_priority(self):
        """사업자번호가 있으면 biz: 프리픽스 키."""
        obs = make_obs(biz_no="1234567890")
        key = _make_group_key(obs)
        assert key.startswith("biz:")
        assert "1234567890" in key

    def test_short_biz_no_falls_back(self):
        """사업자번호가 10자리 미만이면 name 기준으로 fallback."""
        obs = make_obs(biz_no="12345", seller_name="테스트회사")
        key = _make_group_key(obs)
        assert key.startswith("name:")

    def test_name_key(self):
        """사업자번호 없으면 name 기준 키."""
        obs = make_obs(seller_name="주식회사ABC", rep="홍길동", phone="02-1234-5678")
        key = _make_group_key(obs)
        assert key.startswith("name:")
        assert "주식회사ABC" in key

    def test_unknown_key_for_empty(self):
        """모든 식별자가 없으면 unknown 키."""
        obs = make_obs()
        key = _make_group_key(obs)
        assert key.startswith("unknown:")


# ──────────────────────────────────────────────────────────────────────────────
# 판매자 마스터 통합 테스트
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildSellerMaster:

    def test_same_biz_no_merged(self):
        """같은 사업자번호는 하나로 통합."""
        observations = [
            make_obs(biz_no="1234567890", email="a@test.com", product_url="url1", keyword="청소"),
            make_obs(biz_no="1234567890", email="a@test.com", product_url="url2", keyword="세탁"),
        ]
        masters, groups = build_seller_master(observations)
        assert len(masters) == 1
        assert masters[0].product_count == 2

    def test_different_biz_no_separate(self):
        """다른 사업자번호는 별개 판매자."""
        observations = [
            make_obs(biz_no="1111111111", seller_name="A회사"),
            make_obs(biz_no="2222222222", seller_name="B회사"),
        ]
        masters, _ = build_seller_master(observations)
        assert len(masters) == 2

    def test_keyword_count(self):
        """키워드 수 집계."""
        observations = [
            make_obs(biz_no="9999999999", keyword="청소", product_url="u1"),
            make_obs(biz_no="9999999999", keyword="세탁", product_url="u2"),
            make_obs(biz_no="9999999999", keyword="청소", product_url="u3"),
        ]
        masters, _ = build_seller_master(observations)
        assert masters[0].keyword_count == 2  # "청소", "세탁" - 고유값

    def test_best_value_longer_wins(self):
        """더 긴 값이 선택됨."""
        observations = [
            make_obs(biz_no="1234500000", address="서울시 강남구"),
            make_obs(biz_no="1234500000", address="서울시 강남구 테헤란로 123 456빌딩 5층"),
        ]
        masters, _ = build_seller_master(observations)
        assert "테헤란로" in masters[0].business_address

    def test_seller_uid_generated(self):
        """seller_uid 가 생성됨."""
        observations = [make_obs(biz_no="5555555555", seller_name="테스트")]
        masters, _ = build_seller_master(observations)
        assert masters[0].seller_uid
        assert len(masters[0].seller_uid) > 0

    def test_first_and_last_seen(self):
        """first_seen_at / last_seen_at 이 올바르게 설정됨."""
        observations = [
            make_obs(biz_no="1111100000", collected_at="2024-01-01T00:00:00", product_url="u1"),
            make_obs(biz_no="1111100000", collected_at="2024-06-15T12:00:00", product_url="u2"),
        ]
        masters, _ = build_seller_master(observations)
        assert masters[0].first_seen_at == "2024-01-01T00:00:00"
        assert masters[0].last_seen_at == "2024-06-15T12:00:00"

    def test_empty_input(self):
        """빈 입력 → 빈 결과."""
        masters, groups = build_seller_master([])
        assert masters == []
        assert groups == {}


# ──────────────────────────────────────────────────────────────────────────────
# 상품 중복 제거 테스트
# ──────────────────────────────────────────────────────────────────────────────

class TestDeduplicateProducts:

    def test_removes_duplicates_by_product_id(self):
        """product_id 기준 중복 제거."""
        products = [
            make_product("123", keyword="청소"),
            make_product("123", keyword="세탁"),  # 중복
            make_product("456", keyword="청소"),
        ]
        unique = deduplicate_products(products)
        assert len(unique) == 2

    def test_keeps_first_occurrence(self):
        """첫 번째 항목을 보존."""
        products = [
            make_product("111", keyword="첫번째"),
            make_product("111", keyword="두번째"),
        ]
        unique = deduplicate_products(products)
        assert unique[0].keyword == "첫번째"

    def test_empty_list(self):
        """빈 입력 → 빈 출력."""
        assert deduplicate_products([]) == []

    def test_no_duplicates_unchanged(self):
        """중복 없으면 그대로."""
        products = [make_product(str(i)) for i in range(5)]
        unique = deduplicate_products(products)
        assert len(unique) == 5

    def test_no_product_id_uses_url(self):
        """product_id 없으면 URL 기준 중복 제거."""
        p1 = ProductItem(product_url="https://coupang.com/vp/products/999")
        p2 = ProductItem(product_url="https://coupang.com/vp/products/999")
        unique = deduplicate_products([p1, p2])
        assert len(unique) == 1


# ──────────────────────────────────────────────────────────────────────────────
# _best_value 테스트
# ──────────────────────────────────────────────────────────────────────────────

class TestBestValue:

    def test_returns_longest(self):
        assert _best_value(["짧음", "더 긴 값입니다", "중간"]) == "더 긴 값입니다"

    def test_ignores_none(self):
        assert _best_value([None, "유효값", None]) == "유효값"

    def test_all_none(self):
        assert _best_value([None, None]) is None

    def test_empty_list(self):
        assert _best_value([]) is None

    def test_single_value(self):
        assert _best_value(["단일"]) == "단일"
