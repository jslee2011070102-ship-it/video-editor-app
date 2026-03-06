"""공통 유틸리티 모듈."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


def now_iso() -> str:
    """현재 시각을 ISO 8601 형식으로 반환한다."""
    return datetime.now().isoformat(timespec="seconds")


def ensure_dir(path: str | Path) -> Path:
    """디렉토리가 없으면 생성하고 Path 를 반환한다."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_filename(name: str, max_len: int = 80) -> str:
    """파일명에 쓸 수 없는 문자를 제거한다."""
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", name)
    return cleaned[:max_len]


def url_to_hash(url: str) -> str:
    """URL 을 짧은 SHA-256 해시 문자열로 변환한다."""
    return hashlib.sha256(url.encode()).hexdigest()[:12]


def extract_numbers_only(text: Optional[str]) -> str:
    """문자열에서 숫자만 추출한다."""
    if not text:
        return ""
    return re.sub(r"\D", "", text)


def truncate(text: Optional[str], max_len: int = 500) -> Optional[str]:
    """문자열을 최대 길이로 자른다."""
    if text is None:
        return None
    return text[:max_len] if len(text) > max_len else text


def make_coupang_search_url(keyword: str, page: int = 1) -> str:
    """쿠팡 검색 URL 을 생성한다."""
    from urllib.parse import quote_plus
    encoded = quote_plus(keyword)
    return (
        f"https://www.coupang.com/np/search"
        f"?q={encoded}&channel=user&component=&eventCategory=SRP"
        f"&trcid=&traid=&sorter=scoreDesc&minPrice=&maxPrice="
        f"&priceRange=&filterType=&listSize=36&filter=&isPriceRange=false"
        f"&brand=&offerCondition=&rating=0&page={page}"
        f"&rocketAll=false&searchIndexingToken=&backgroundColor="
    )


def dataclass_to_dict(obj: Any) -> Dict[str, Any]:
    """dataclass 객체를 dict 로 변환한다."""
    import dataclasses
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    return dict(obj)
