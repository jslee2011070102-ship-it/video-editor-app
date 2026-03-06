"""normalizer.py 단위 테스트."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from src.normalizer import (
    normalize_address,
    normalize_business_no,
    normalize_email,
    normalize_mail_order_license,
    normalize_name,
    normalize_phone,
)


# ──────────────────────────────────────────────────────────────────────────────
# 사업자번호 정규화 테스트
# ──────────────────────────────────────────────────────────────────────────────

class TestNormalizeBusinessNo:

    def test_formatted_input(self):
        digits, formatted = normalize_business_no("123-45-67890")
        assert digits == "1234567890"
        assert formatted == "123-45-67890"

    def test_digits_only_input(self):
        digits, formatted = normalize_business_no("1234567890")
        assert digits == "1234567890"
        assert formatted == "123-45-67890"

    def test_with_spaces(self):
        digits, formatted = normalize_business_no("123 45 67890")
        assert digits == "1234567890"

    def test_none_input(self):
        digits, formatted = normalize_business_no(None)
        assert digits is None
        assert formatted is None

    def test_empty_string(self):
        digits, formatted = normalize_business_no("")
        assert digits is None
        assert formatted is None

    def test_invalid_length(self):
        """10자리가 아닌 경우 formatted 는 None."""
        digits, formatted = normalize_business_no("12345")
        assert formatted is None

    def test_with_hyphen_in_middle(self):
        digits, _ = normalize_business_no("123-45-6789")  # 9자리
        assert _ is None  # 10자리가 아님


# ──────────────────────────────────────────────────────────────────────────────
# 전화번호 정규화 테스트
# ──────────────────────────────────────────────────────────────────────────────

class TestNormalizePhone:

    def test_basic(self):
        assert normalize_phone("02-1234-5678") == "02-1234-5678"

    def test_with_spaces(self):
        result = normalize_phone("02 1234 5678")
        assert " " not in result

    def test_mobile(self):
        assert normalize_phone("010-9876-5432") == "010-9876-5432"

    def test_with_text(self):
        """숫자/하이픈만 남김."""
        result = normalize_phone("전화: 02-1234-5678")
        assert "전화" not in result

    def test_none_input(self):
        assert normalize_phone(None) is None

    def test_empty_string(self):
        assert normalize_phone("") is None


# ──────────────────────────────────────────────────────────────────────────────
# 이메일 정규화 테스트
# ──────────────────────────────────────────────────────────────────────────────

class TestNormalizeEmail:

    def test_valid_email(self):
        email, is_valid = normalize_email("Test@Example.COM")
        assert email == "test@example.com"
        assert is_valid is True

    def test_valid_email_with_dots(self):
        email, is_valid = normalize_email("user.name+tag@domain.co.kr")
        assert is_valid is True

    def test_invalid_email_no_at(self):
        email, is_valid = normalize_email("notanemail")
        assert is_valid is False

    def test_invalid_email_no_domain(self):
        email, is_valid = normalize_email("user@")
        assert is_valid is False

    def test_none_input(self):
        email, is_valid = normalize_email(None)
        assert email is None
        assert is_valid is False

    def test_email_embedded_in_text(self):
        """텍스트 중간의 이메일 추출."""
        email, is_valid = normalize_email("문의: contact@company.com 바랍니다")
        assert email == "contact@company.com"
        assert is_valid is True

    def test_strips_whitespace(self):
        email, is_valid = normalize_email("  user@domain.com  ")
        assert email == "user@domain.com"
        assert is_valid is True


# ──────────────────────────────────────────────────────────────────────────────
# 주소 정규화 테스트
# ──────────────────────────────────────────────────────────────────────────────

class TestNormalizeAddress:

    def test_basic(self):
        result = normalize_address("서울시 강남구 테헤란로 123")
        assert result == "서울시 강남구 테헤란로 123"

    def test_removes_extra_spaces(self):
        result = normalize_address("서울시  강남구   테헤란로")
        assert "  " not in result

    def test_removes_newlines(self):
        result = normalize_address("서울시\n강남구\n테헤란로 123")
        assert "\n" not in result
        assert "서울시 강남구 테헤란로 123" == result

    def test_none_input(self):
        assert normalize_address(None) is None

    def test_empty_string(self):
        assert normalize_address("") is None


# ──────────────────────────────────────────────────────────────────────────────
# 이름 정규화 테스트
# ──────────────────────────────────────────────────────────────────────────────

class TestNormalizeName:

    def test_strips_whitespace(self):
        assert normalize_name("  주식회사 테스트  ") == "주식회사 테스트"

    def test_collapses_spaces(self):
        assert normalize_name("주식회사  테스트") == "주식회사 테스트"

    def test_none_input(self):
        assert normalize_name(None) is None

    def test_empty_string(self):
        assert normalize_name("") is None


# ──────────────────────────────────────────────────────────────────────────────
# 통신판매업 신고번호 정규화 테스트
# ──────────────────────────────────────────────────────────────────────────────

class TestNormalizeMailOrderLicense:

    def test_basic(self):
        result = normalize_mail_order_license("제2023-서울강남-1234호")
        assert result == "제2023-서울강남-1234호"

    def test_removes_extra_spaces(self):
        result = normalize_mail_order_license("제2023-서울강남-1234호  ")
        assert result == "제2023-서울강남-1234호"

    def test_none_input(self):
        assert normalize_mail_order_license(None) is None
