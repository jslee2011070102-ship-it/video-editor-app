"""SQLite 저장 모듈.

products, seller_observations, sellers_master, crawl_logs, failed_jobs
테이블을 관리한다.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Generator, List, Optional

from loguru import logger

from .config_loader import AppConfig
from .deduplicator import SellerMaster
from .parser import ProductItem, SellerObservation
from .utils import ensure_dir, now_iso


DDL_PRODUCTS = """
CREATE TABLE IF NOT EXISTS products (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword          TEXT,
    search_page      INTEGER,
    rank_on_page     INTEGER,
    product_name     TEXT,
    product_url      TEXT UNIQUE,
    product_id       TEXT,
    item_id          TEXT,
    vendor_item_id   TEXT,
    category_text    TEXT,
    crawl_time       TEXT,
    created_at       TEXT DEFAULT (datetime('now','localtime'))
);
"""

DDL_SELLER_OBSERVATIONS = """
CREATE TABLE IF NOT EXISTS seller_observations (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_name                TEXT,
    representative_name        TEXT,
    business_registration_no   TEXT,
    mail_order_license_no      TEXT,
    business_address           TEXT,
    email                      TEXT,
    phone                      TEXT,
    purchase_safety_service_no TEXT,
    seller_raw_text            TEXT,
    source_product_url         TEXT,
    source_product_name        TEXT,
    source_keyword             TEXT,
    collected_at               TEXT,
    created_at                 TEXT DEFAULT (datetime('now','localtime'))
);
"""

DDL_SELLERS_MASTER = """
CREATE TABLE IF NOT EXISTS sellers_master (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_uid                 TEXT UNIQUE,
    seller_name                TEXT,
    representative_name        TEXT,
    business_registration_no   TEXT UNIQUE,
    mail_order_license_no      TEXT,
    business_address           TEXT,
    email                      TEXT,
    phone                      TEXT,
    first_seen_at              TEXT,
    last_seen_at               TEXT,
    product_count              INTEGER DEFAULT 0,
    keyword_count              INTEGER DEFAULT 0,
    source_count               INTEGER DEFAULT 0,
    notes                      TEXT,
    created_at                 TEXT DEFAULT (datetime('now','localtime'))
);
"""

DDL_CRAWL_LOGS = """
CREATE TABLE IF NOT EXISTS crawl_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    level      TEXT,
    stage      TEXT,
    message    TEXT,
    logged_at  TEXT
);
"""

DDL_FAILED_JOBS = """
CREATE TABLE IF NOT EXISTS failed_jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword       TEXT,
    page          INTEGER,
    product_url   TEXT,
    product_name  TEXT,
    stage         TEXT,
    error_message TEXT,
    retry_count   INTEGER DEFAULT 0,
    resolved      INTEGER DEFAULT 0,
    logged_at     TEXT
);
"""


class StorageManager:
    """SQLite 기반 저장소 관리자."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        db_dir = ensure_dir(config.processed_dir)
        self.db_path = db_dir / config.sqlite_db_name
        self._init_db()

    def _init_db(self) -> None:
        """데이터베이스 테이블을 초기화한다."""
        with self._conn() as conn:
            conn.executescript(
                DDL_PRODUCTS
                + DDL_SELLER_OBSERVATIONS
                + DDL_SELLERS_MASTER
                + DDL_CRAWL_LOGS
                + DDL_FAILED_JOBS
            )
        logger.info(f"[DB] 초기화 완료: {self.db_path}")

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ──────────────────────────────────────────────────────────────────────────
    # 상품 저장
    # ──────────────────────────────────────────────────────────────────────────

    def save_products(self, products: List[ProductItem]) -> int:
        """상품 목록을 저장하고 삽입된 건수를 반환한다."""
        if not products:
            return 0

        sql = """
        INSERT OR IGNORE INTO products
            (keyword, search_page, rank_on_page, product_name, product_url,
             product_id, item_id, vendor_item_id, category_text, crawl_time)
        VALUES
            (:keyword, :search_page, :rank_on_page, :product_name, :product_url,
             :product_id, :item_id, :vendor_item_id, :category_text, :crawl_time)
        """
        rows = [asdict(p) for p in products]
        with self._conn() as conn:
            cursor = conn.executemany(sql, rows)
            count = cursor.rowcount

        logger.debug(f"[DB] products 저장: {count}/{len(products)}건")
        return count

    # ──────────────────────────────────────────────────────────────────────────
    # 판매자 관측 저장
    # ──────────────────────────────────────────────────────────────────────────

    def save_observations(self, observations: List[SellerObservation]) -> int:
        """판매자 관측 목록을 저장하고 삽입된 건수를 반환한다."""
        if not observations:
            return 0

        sql = """
        INSERT INTO seller_observations
            (seller_name, representative_name, business_registration_no,
             mail_order_license_no, business_address, email, phone,
             purchase_safety_service_no, seller_raw_text, source_product_url,
             source_product_name, source_keyword, collected_at)
        VALUES
            (:seller_name, :representative_name, :business_registration_no,
             :mail_order_license_no, :business_address, :email, :phone,
             :purchase_safety_service_no, :seller_raw_text, :source_product_url,
             :source_product_name, :source_keyword, :collected_at)
        """
        rows = [asdict(o) for o in observations]
        with self._conn() as conn:
            cursor = conn.executemany(sql, rows)
            count = cursor.rowcount

        logger.debug(f"[DB] seller_observations 저장: {count}건")
        return count

    # ──────────────────────────────────────────────────────────────────────────
    # 판매자 마스터 저장
    # ──────────────────────────────────────────────────────────────────────────

    def save_sellers_master(self, masters: List[SellerMaster]) -> int:
        """통합 판매자 마스터를 저장/갱신한다."""
        if not masters:
            return 0

        sql = """
        INSERT INTO sellers_master
            (seller_uid, seller_name, representative_name, business_registration_no,
             mail_order_license_no, business_address, email, phone,
             first_seen_at, last_seen_at, product_count, keyword_count, source_count, notes)
        VALUES
            (:seller_uid, :seller_name, :representative_name, :business_registration_no,
             :mail_order_license_no, :business_address, :email, :phone,
             :first_seen_at, :last_seen_at, :product_count, :keyword_count, :source_count, :notes)
        ON CONFLICT(seller_uid) DO UPDATE SET
            seller_name              = excluded.seller_name,
            representative_name      = excluded.representative_name,
            business_registration_no = excluded.business_registration_no,
            mail_order_license_no    = excluded.mail_order_license_no,
            business_address         = excluded.business_address,
            email                    = excluded.email,
            phone                    = excluded.phone,
            last_seen_at             = excluded.last_seen_at,
            product_count            = excluded.product_count,
            keyword_count            = excluded.keyword_count,
            source_count             = excluded.source_count
        """
        rows = [asdict(m) for m in masters]
        with self._conn() as conn:
            cursor = conn.executemany(sql, rows)
            count = cursor.rowcount

        logger.debug(f"[DB] sellers_master 저장/갱신: {count}건")
        return count

    # ──────────────────────────────────────────────────────────────────────────
    # 실패 작업 저장
    # ──────────────────────────────────────────────────────────────────────────

    def save_failed_jobs(self, failed_jobs: List[dict]) -> int:
        """실패 작업 목록을 저장한다."""
        if not failed_jobs:
            return 0

        sql = """
        INSERT INTO failed_jobs
            (keyword, page, product_url, product_name, stage, error_message, retry_count, logged_at)
        VALUES
            (:keyword, :page, :product_url, :product_name, :stage, :error_message, :retry_count, :logged_at)
        """
        with self._conn() as conn:
            cursor = conn.executemany(sql, failed_jobs)
            count = cursor.rowcount

        logger.debug(f"[DB] failed_jobs 저장: {count}건")
        return count

    def load_failed_jobs(self, resolved: bool = False) -> List[dict]:
        """미해결 실패 작업 목록을 불러온다."""
        sql = "SELECT * FROM failed_jobs WHERE resolved = ?"
        with self._conn() as conn:
            rows = conn.execute(sql, (1 if resolved else 0,)).fetchall()
        return [dict(row) for row in rows]

    def mark_failed_resolved(self, job_ids: List[int]) -> None:
        """실패 작업을 해결됨으로 표시한다."""
        if not job_ids:
            return
        placeholders = ",".join("?" * len(job_ids))
        sql = f"UPDATE failed_jobs SET resolved = 1 WHERE id IN ({placeholders})"
        with self._conn() as conn:
            conn.execute(sql, job_ids)

    # ──────────────────────────────────────────────────────────────────────────
    # 로그 저장
    # ──────────────────────────────────────────────────────────────────────────

    def log_event(self, level: str, stage: str, message: str) -> None:
        """크롤링 이벤트를 DB 에 기록한다."""
        sql = "INSERT INTO crawl_logs (level, stage, message, logged_at) VALUES (?, ?, ?, ?)"
        with self._conn() as conn:
            conn.execute(sql, (level, stage, message, now_iso()))

    # ──────────────────────────────────────────────────────────────────────────
    # 조회
    # ──────────────────────────────────────────────────────────────────────────

    def get_done_product_urls(self) -> set:
        """이미 수집된 상품 URL 집합을 반환한다 (resume 모드용)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT source_product_url FROM seller_observations"
            ).fetchall()
        return {row[0] for row in rows}

    def get_stats(self) -> dict:
        """수집 통계를 반환한다."""
        with self._conn() as conn:
            products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            observations = conn.execute(
                "SELECT COUNT(*) FROM seller_observations"
            ).fetchone()[0]
            masters = conn.execute("SELECT COUNT(*) FROM sellers_master").fetchone()[0]
            failed = conn.execute(
                "SELECT COUNT(*) FROM failed_jobs WHERE resolved = 0"
            ).fetchone()[0]

        return {
            "products": products,
            "seller_observations": observations,
            "sellers_master": masters,
            "failed_jobs_pending": failed,
        }
