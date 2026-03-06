"""쿠팡 판매자 크롤러 CLI 진입점.

사용 예시:
    python -m src.main --keywords config/keywords.txt --max-pages 20
    python -m src.main --keyword "청소용품" --max-pages 5 --headless false
    python -m src.main --retry-failed --export csv sqlite
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import List, Optional

from loguru import logger

from .browser import BrowserManager, managed_browser
from .config_loader import AppConfig, load_config, load_keywords
from .deduplicator import build_seller_master, deduplicate_products
from .exporter import DataExporter
from .parser import ProductItem, SellerObservation
from .product_crawler import ProductCrawler, retry_failed_products
from .search_crawler import crawl_all_keywords
from .storage import StorageManager
from .utils import ensure_dir, now_iso


# ──────────────────────────────────────────────────────────────────────────────
# 로깅 설정
# ──────────────────────────────────────────────────────────────────────────────

def setup_logging(config: AppConfig) -> None:
    """loguru 로거를 설정한다."""
    logger.remove()

    log_level = config.log_level.upper()
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
        colorize=True,
    )

    if config.log_to_file:
        log_dir = ensure_dir(config.logs_dir)
        log_path = log_dir / "crawler_{time:YYYY-MM-DD}.log"
        logger.add(
            str(log_path),
            level=log_level,
            rotation="1 day",
            retention="30 days",
            encoding="utf-8",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        )


# ──────────────────────────────────────────────────────────────────────────────
# CLI 파서
# ──────────────────────────────────────────────────────────────────────────────

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coupang-seller-crawler",
        description="쿠팡 검색결과 기반 판매자 DB 구축 크롤러",
    )

    # 키워드
    kw_group = parser.add_mutually_exclusive_group()
    kw_group.add_argument(
        "--keywords",
        metavar="FILE",
        help="키워드 목록 파일 경로 (기본: config/keywords.txt)",
    )
    kw_group.add_argument(
        "--keyword",
        metavar="KEYWORD",
        help="단일 키워드 직접 입력",
    )

    # 크롤링 옵션
    parser.add_argument(
        "--max-pages",
        type=int,
        metavar="N",
        help="키워드당 최대 검색 페이지 수",
    )
    parser.add_argument(
        "--headless",
        choices=["true", "false"],
        help="헤드리스 모드 (기본: true)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=None,
        help="이미 수집된 상품은 건너뜀",
    )

    # 세션 워밍업
    parser.add_argument(
        "--warmup",
        action="store_true",
        help="브라우저를 열고 쿠팡 세션을 수동으로 확립한 후 크롤링 시작",
    )

    # 실행 모드
    mode_group = parser.add_argument_group("실행 모드 (하나만 선택 가능)")
    mode_group.add_argument(
        "--only-search",
        action="store_true",
        help="검색 수집만 수행 (상품 상세 진입 안 함)",
    )
    mode_group.add_argument(
        "--only-product",
        action="store_true",
        help="상품 상세 수집만 수행 (DB 에 있는 product_url 사용)",
    )
    mode_group.add_argument(
        "--retry-failed",
        action="store_true",
        help="DB 의 실패 목록을 재시도",
    )

    # 내보내기
    parser.add_argument(
        "--export",
        nargs="+",
        choices=["csv", "excel", "sqlite"],
        help="내보낼 포맷 (기본: settings.yaml 기준)",
    )

    # 기타
    parser.add_argument(
        "--limit-products",
        type=int,
        metavar="N",
        help="키워드당 최대 수집 상품 수 (0=무제한)",
    )
    parser.add_argument(
        "--config",
        metavar="FILE",
        default="config/settings.yaml",
        help="설정 파일 경로 (기본: config/settings.yaml)",
    )

    return parser


# ──────────────────────────────────────────────────────────────────────────────
# CLI → Config 병합
# ──────────────────────────────────────────────────────────────────────────────

def apply_cli_overrides(args: argparse.Namespace, config: AppConfig) -> AppConfig:
    """CLI 인수로 AppConfig 를 오버라이드한다."""
    if args.max_pages is not None:
        config.max_pages_per_keyword = args.max_pages

    if args.headless is not None:
        config.headless = args.headless == "true"

    if args.resume:
        config.resume_mode = True

    if args.limit_products is not None:
        config.limit_products_per_keyword = args.limit_products

    if args.export:
        config.export_csv = "csv" in args.export
        config.export_excel = "excel" in args.export
        config.export_sqlite = "sqlite" in args.export

    return config


# ──────────────────────────────────────────────────────────────────────────────
# 메인 워크플로우
# ──────────────────────────────────────────────────────────────────────────────

async def run_full_pipeline(
    config: AppConfig,
    keywords: List[str],
    args: argparse.Namespace,
) -> None:
    """전체 크롤링 파이프라인을 실행한다."""
    storage = StorageManager(config)
    exporter = DataExporter(config)

    logger.info(f"[메인] 크롤링 시작 - 키워드 {len(keywords)}개")
    logger.info(f"[메인] 키워드 목록: {', '.join(keywords[:10])}" + (" ..." if len(keywords) > 10 else ""))

    all_products: List[ProductItem] = []
    all_observations: List[SellerObservation] = []
    all_failed: List[dict] = []

    async with managed_browser(config) as browser_manager:

        # ── 1. 실패 재시도 모드 ──────────────────────────────────────────────
        if args.retry_failed:
            logger.info("[메인] 실패 재시도 모드")
            failed_jobs = storage.load_failed_jobs()
            if not failed_jobs:
                logger.info("[메인] 재시도할 실패 항목이 없습니다.")
                return

            observations, new_failed = await retry_failed_products(
                browser_manager, config, failed_jobs
            )
            all_observations.extend(observations)
            all_failed.extend(new_failed)

        # ── 2. 검색 전용 모드 ────────────────────────────────────────────────
        elif args.only_search:
            logger.info("[메인] 검색 전용 모드")
            products = await crawl_all_keywords(browser_manager, config, keywords)
            all_products = deduplicate_products(products)
            if config.export_sqlite:
                storage.save_products(all_products)
            if config.export_csv or config.export_excel:
                exporter.export_products(all_products)

        # ── 3. 상품 상세 전용 모드 ───────────────────────────────────────────
        elif args.only_product:
            logger.info("[메인] 상품 상세 전용 모드 (DB 에서 URL 로드)")
            # DB 에서 product URL 목록을 읽어 ProductItem 생성
            # 간소화: products 테이블에서 로드
            with storage._conn() as conn:
                rows = conn.execute(
                    "SELECT product_url, product_name, keyword, search_page FROM products"
                ).fetchall()
            from .parser import ProductItem as PI
            products_from_db = [
                PI(
                    product_url=row[0],
                    product_name=row[1] or "",
                    keyword=row[2] or "",
                    search_page=row[3] or 0,
                )
                for row in rows
            ]
            already_done: set = set()
            if config.resume_mode:
                already_done = storage.get_done_product_urls()

            crawler = ProductCrawler(browser_manager, config)
            observations, failed = await crawler.crawl_products(
                products_from_db, already_done_urls=already_done
            )
            all_observations.extend(observations)
            all_failed.extend(failed)

        # ── 4. 전체 파이프라인 (기본) ────────────────────────────────────────
        else:
            logger.info("[메인] 전체 파이프라인 실행")

            # 4-1. 검색 수집
            products = await crawl_all_keywords(
                browser_manager, config, keywords
            )
            all_products = deduplicate_products(products)

            # 4-2. 상품 상세 수집
            already_done: set = set()
            if config.resume_mode:
                already_done = storage.get_done_product_urls()

            crawler = ProductCrawler(browser_manager, config)
            observations, failed = await crawler.crawl_products(
                all_products, already_done_urls=already_done
            )
            all_observations.extend(observations)
            all_failed.extend(failed)

    # ── 5. 통합 및 저장 ─────────────────────────────────────────────────────
    masters, _ = build_seller_master(all_observations)

    if config.export_sqlite:
        if all_products:
            storage.save_products(all_products)
        if all_observations:
            storage.save_observations(all_observations)
        if masters:
            storage.save_sellers_master(masters)
        if all_failed:
            storage.save_failed_jobs(all_failed)

    if config.export_csv or config.export_excel:
        if all_products:
            exporter.export_products(all_products)
        if all_observations:
            exporter.export_observations(all_observations)
        if masters:
            exporter.export_sellers_master(masters)
        if all_failed:
            exporter.export_failed_jobs(all_failed)

    # ── 6. 통계 ─────────────────────────────────────────────────────────────
    exporter.export_stats_report(all_products, all_observations, masters, all_failed)

    stats = storage.get_stats()
    logger.info(f"[메인] DB 통계: {stats}")
    logger.info("[메인] 완료")


# ──────────────────────────────────────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────────────────────────────────────

async def run_warmup(config: AppConfig) -> None:
    """브라우저를 열고 사용자가 쿠팡 세션을 수동으로 확립하도록 안내한다."""
    print("\n" + "=" * 60)
    print("  쿠팡 세션 워밍업 모드")
    print("=" * 60)
    print("  브라우저가 열립니다.")
    print("  1. 브라우저에서 coupang.com 에 접속하세요.")
    print("  2. 로그인 후 검색 결과가 정상으로 보이면 OK 입니다.")
    print("  3. 이 터미널로 돌아와 Enter 를 누르면 크롤링이 시작됩니다.")
    print("=" * 60 + "\n")

    manager = BrowserManager(config)
    await manager.start()

    try:
        async with manager.new_page() as page:
            await page.goto("https://www.coupang.com", wait_until="load",
                            timeout=config.timeout_sec * 1000)
            logger.info("[워밍업] 브라우저에서 coupang.com 을 확인하세요.")
            logger.info("[워밍업] 세션 확립 후 이 터미널에서 Enter 를 누르세요.")
            await asyncio.get_event_loop().run_in_executor(None, input, "  ▶ Enter 를 누르면 크롤링을 시작합니다... ")
    finally:
        await manager.stop()

    logger.info("[워밍업] 완료. 세션이 data/chrome_profile 에 저장됨.")


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    # 설정 로드
    config = load_config(args.config)
    config = apply_cli_overrides(args, config)
    setup_logging(config)

    # 키워드 결정
    if args.keyword:
        keywords = [args.keyword]
    elif args.keywords:
        keywords = load_keywords(args.keywords)
    elif not (args.retry_failed or args.only_product):
        # 기본 키워드 파일
        default_kw = Path("config/keywords.txt")
        if default_kw.exists():
            keywords = load_keywords(default_kw)
        else:
            logger.error("키워드를 지정하세요: --keyword 또는 --keywords")
            sys.exit(1)
    else:
        keywords = []

    if keywords:
        logger.info(f"[메인] 키워드 {len(keywords)}개 로드됨")

    try:
        if args.warmup:
            asyncio.run(run_warmup(config))
        asyncio.run(run_full_pipeline(config, keywords, args))
    except KeyboardInterrupt:
        logger.warning("[메인] 사용자에 의해 중단됨")
        sys.exit(0)
    except Exception as exc:
        logger.exception(f"[메인] 예기치 않은 오류: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
