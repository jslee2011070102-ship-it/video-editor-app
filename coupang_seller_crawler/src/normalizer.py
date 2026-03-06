"""데이터 정규화 모듈.

사업자번호, 전화번호, 이메일, 주소 등을 정규화한다.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple


# ──────────────────────────────────────────────────────────────────────────────
# 사업자번호
# ──────────────────────────────────────────────────────────────────────────────

def normalize_business_no(raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """사업자번호를 정규화한다.

    Returns:
        (digits_only, formatted)  예) ("1234567890", "123-45-67890")
        값이 없거나 유효하지 않으면 (None, None)
    """
    if not raw:
        return None, None

    digits = re.sub(r"\D", "", raw)
    if len(digits) != 10:
        return digits if digits else None, None

    formatted = f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"
    return digits, formatted


# ──────────────────────────────────────────────────────────────────────────────
# 전화번호
# ──────────────────────────────────────────────────────────────────────────────

def normalize_phone(raw: Optional[str]) -> Optional[str]:
    """전화번호에서 공백 및 불필요한 문자를 제거한다."""
    if not raw:
        return None

    # 숫자, 하이픈, 괄호, + 만 남김
    cleaned = re.sub(r"[^\d\-\(\)\+]", "", raw.strip())
    return cleaned or None


# ──────────────────────────────────────────────────────────────────────────────
# 이메일
# ──────────────────────────────────────────────────────────────────────────────

EMAIL_PATTERN = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


def normalize_email(raw: Optional[str]) -> Tuple[Optional[str], bool]:
    """이메일을 정규화하고 형식 유효성을 검증한다.

    Returns:
        (normalized_email, is_valid)
    """
    if not raw:
        return None, False

    # 소문자 변환, 공백 제거
    normalized = raw.strip().lower()

    # 이메일이 문장 중간에 있을 경우 추출 시도
    match = re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", normalized)
    if match:
        normalized = match.group(0)

    is_valid = bool(EMAIL_PATTERN.match(normalized))
    return normalized, is_valid


# ──────────────────────────────────────────────────────────────────────────────
# 주소
# ──────────────────────────────────────────────────────────────────────────────

def normalize_address(raw: Optional[str]) -> Optional[str]:
    """주소에서 연속 공백 및 줄바꿈을 정리한다."""
    if not raw:
        return None

    # 줄바꿈 → 공백
    cleaned = raw.replace("\n", " ").replace("\r", " ")
    # 연속 공백 제거
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


# ──────────────────────────────────────────────────────────────────────────────
# 통신판매업 신고번호
# ──────────────────────────────────────────────────────────────────────────────

def normalize_mail_order_license(raw: Optional[str]) -> Optional[str]:
    """통신판매업 신고번호에서 불필요한 공백을 제거한다."""
    if not raw:
        return None
    return re.sub(r"\s+", " ", raw.strip()) or None


# ──────────────────────────────────────────────────────────────────────────────
# 판매자명/대표자명
# ──────────────────────────────────────────────────────────────────────────────

def normalize_name(raw: Optional[str]) -> Optional[str]:
    """이름 앞뒤 공백 제거 및 연속 공백 정리."""
    if not raw:
        return None
    return re.sub(r"\s+", " ", raw.strip()) or None


# ──────────────────────────────────────────────────────────────────────────────
# SellerObservation 전체 정규화
# ──────────────────────────────────────────────────────────────────────────────

def normalize_observation(obs: "SellerObservation") -> "SellerObservation":  # type: ignore[name-defined]  # noqa: F821
    """SellerObservation 객체의 모든 필드를 정규화한다."""
    from .parser import SellerObservation  # 순환 임포트 방지

    obs.seller_name = normalize_name(obs.seller_name)
    obs.representative_name = normalize_name(obs.representative_name)

    biz_digits, biz_formatted = normalize_business_no(obs.business_registration_no)
    obs.business_registration_no = biz_digits

    obs.phone = normalize_phone(obs.phone)

    email, _ = normalize_email(obs.email)
    obs.email = email

    obs.business_address = normalize_address(obs.business_address)
    obs.mail_order_license_no = normalize_mail_order_license(obs.mail_order_license_no)

    return obs
