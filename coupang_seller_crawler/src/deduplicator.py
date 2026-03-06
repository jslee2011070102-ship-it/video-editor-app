"""중복 제거 및 판매자 통합 모듈.

사업자번호 기준으로 판매자를 통합하고 sellers_master 를 생성한다.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from loguru import logger

from .parser import SellerObservation
from .utils import now_iso


@dataclass
class SellerMaster:
    """통합 판매자 마스터 레코드."""
    seller_uid: str = ""
    seller_name: Optional[str] = None
    representative_name: Optional[str] = None
    business_registration_no: Optional[str] = None
    mail_order_license_no: Optional[str] = None
    business_address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    first_seen_at: str = ""
    last_seen_at: str = ""
    product_count: int = 0
    keyword_count: int = 0
    source_count: int = 0
    notes: Optional[str] = None


def build_seller_master(
    observations: List[SellerObservation],
) -> Tuple[List[SellerMaster], Dict[str, List[SellerObservation]]]:
    """관측 데이터에서 통합 판매자 마스터를 생성한다.

    Args:
        observations: 수집된 판매자 관측 목록

    Returns:
        (masters, grouped) - 마스터 레코드 목록과 그룹핑된 관측 목록
    """
    # 1순위: 사업자번호 기준 그룹핑
    # 2순위: 판매자명+대표자+전화번호 기준 그룹핑
    groups: Dict[str, List[SellerObservation]] = defaultdict(list)

    for obs in observations:
        key = _make_group_key(obs)
        groups[key].append(obs)

    masters: List[SellerMaster] = []
    for key, obs_list in groups.items():
        master = _merge_observations(obs_list)
        masters.append(master)

    logger.info(
        f"[통합] {len(observations)}개 관측 → {len(masters)}개 판매자 통합 완료"
    )
    return masters, dict(groups)


def _make_group_key(obs: SellerObservation) -> str:
    """관측값에서 그룹핑 키를 생성한다."""
    # 1순위: 사업자번호
    if obs.business_registration_no and len(obs.business_registration_no) >= 10:
        return f"biz:{obs.business_registration_no}"

    # 2순위: 판매자명 + 대표자명 + 전화번호
    name = obs.seller_name or ""
    rep = obs.representative_name or ""
    phone = obs.phone or ""
    if name or rep:
        key_parts = [p for p in [name, rep, phone] if p]
        return "name:" + "|".join(key_parts)

    # 3순위: 판매자명 + 주소 앞 20자
    addr = (obs.business_address or "")[:20]
    if name and addr:
        return f"addr:{name}|{addr}"

    # 식별 불가 → 각자 독립 키
    return f"unknown:{uuid.uuid4().hex}"


def _merge_observations(obs_list: List[SellerObservation]) -> SellerMaster:
    """동일 판매자의 여러 관측값을 하나의 SellerMaster 로 병합한다."""
    master = SellerMaster(
        seller_uid=uuid.uuid4().hex[:16],
        first_seen_at=_min_time([o.collected_at for o in obs_list]),
        last_seen_at=_max_time([o.collected_at for o in obs_list]),
    )

    # 필드별 최선값 선택
    master.seller_name = _best_value([o.seller_name for o in obs_list])
    master.representative_name = _best_value([o.representative_name for o in obs_list])
    master.business_registration_no = _best_value(
        [o.business_registration_no for o in obs_list]
    )
    master.mail_order_license_no = _best_value(
        [o.mail_order_license_no for o in obs_list]
    )
    master.business_address = _best_value([o.business_address for o in obs_list])
    master.email = _best_value([o.email for o in obs_list])
    master.phone = _best_value([o.phone for o in obs_list])

    # 통계
    master.product_count = len(obs_list)
    keywords = {o.source_keyword for o in obs_list if o.source_keyword}
    master.keyword_count = len(keywords)
    master.source_count = len({o.source_product_url for o in obs_list})

    return master


def _best_value(values: List[Optional[str]]) -> Optional[str]:
    """None 이 아닌 값 중 가장 긴 값을 반환한다 (더 완전한 정보 우선)."""
    non_null = [v for v in values if v]
    if not non_null:
        return None
    return max(non_null, key=len)


def _min_time(times: List[str]) -> str:
    """ISO 시간 문자열 목록에서 가장 빠른 시간을 반환한다."""
    valid = [t for t in times if t]
    return min(valid) if valid else now_iso()


def _max_time(times: List[str]) -> str:
    """ISO 시간 문자열 목록에서 가장 늦은 시간을 반환한다."""
    valid = [t for t in times if t]
    return max(valid) if valid else now_iso()


def deduplicate_products(
    products: List["ProductItem"],  # type: ignore[name-defined]  # noqa: F821
) -> List["ProductItem"]:  # type: ignore[name-defined]  # noqa: F821
    """product_id 기준으로 상품 중복을 제거한다."""
    from .parser import ProductItem

    seen: set = set()
    unique: List[ProductItem] = []

    for p in products:
        pid = p.product_id or p.product_url
        if pid not in seen:
            seen.add(pid)
            unique.append(p)

    removed = len(products) - len(unique)
    if removed:
        logger.info(f"[중복제거] 상품 {removed}개 제거 (원본 {len(products)}개 → {len(unique)}개)")

    return unique
