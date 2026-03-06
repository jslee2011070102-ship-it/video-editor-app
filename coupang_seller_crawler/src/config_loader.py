"""설정 파일 로딩 모듈.

settings.yaml 과 .env 파일을 읽어 AppConfig 객체로 반환한다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import yaml
from dotenv import load_dotenv


@dataclass
class AppConfig:
    """전체 애플리케이션 설정."""

    # 크롤링
    max_pages_per_keyword: int = 30
    headless: bool = True
    min_delay_sec: float = 2.0
    max_delay_sec: float = 5.0
    retry_count: int = 3
    concurrency: int = 2
    timeout_sec: int = 25

    # 저장 옵션
    save_html_snapshot: bool = True
    export_csv: bool = True
    export_excel: bool = True
    export_sqlite: bool = True

    # 실행 모드
    resume_mode: bool = True

    # 브라우저 설정
    browser_type: str = "chromium"
    user_agent: str = ""
    viewport_width: int = 1280
    viewport_height: int = 800

    # 경로
    data_dir: str = "data"
    raw_dir: str = "data/raw"
    processed_dir: str = "data/processed"
    exports_dir: str = "data/exports"
    logs_dir: str = "data/logs"

    # SQLite
    sqlite_db_name: str = "coupang_sellers.db"

    # 로그
    log_level: str = "INFO"
    log_to_file: bool = True

    # 수집 제한 (0이면 무제한)
    limit_products_per_keyword: int = 0

    # CLI 오버라이드용 (설정 파일에는 없음)
    keywords: List[str] = field(default_factory=list)


def load_config(settings_path: str | Path = "config/settings.yaml") -> AppConfig:
    """settings.yaml 과 .env 를 읽어 AppConfig 를 반환한다."""
    load_dotenv()

    cfg = AppConfig()
    settings_path = Path(settings_path)

    if settings_path.exists():
        with open(settings_path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}

        for key, value in data.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)

    # 환경변수 오버라이드
    if os.getenv("LOG_LEVEL"):
        cfg.log_level = os.environ["LOG_LEVEL"]

    if os.getenv("USER_AGENT"):
        cfg.user_agent = os.environ["USER_AGENT"]

    return cfg


def load_keywords(keywords_path: str | Path) -> List[str]:
    """키워드 파일을 읽어 리스트로 반환한다.

    # 으로 시작하는 줄과 빈 줄은 무시한다.
    """
    keywords_path = Path(keywords_path)
    if not keywords_path.exists():
        raise FileNotFoundError(f"키워드 파일을 찾을 수 없습니다: {keywords_path}")

    keywords: List[str] = []
    with open(keywords_path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                keywords.append(stripped)

    return keywords
