"""상품 상세페이지 크롤링 모듈.

상품 URL 목록을 받아 각 상품의 판매자 정보를 추출한다.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Optional, Set

from loguru import logger
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .browser import BrowserManager, random_delay
from .config_loader import AppConfig
from .normalizer import normalize_observation
from .parser import ProductItem, SellerObservation, parse_seller_info
from .utils import ensure_dir, now_iso, safe_filename, url_to_hash


class ProductCrawler:
    """상품 상세페이지 크롤러."""

    def __init__(self, browser_manager: BrowserManager, config: AppConfig) -> None:
        self.browser = browser_manager
        self.config = config
        self._raw_dir = ensure_dir(self.config.raw_dir)

    async def crawl_products(
        self,
        products: List[ProductItem],
        already_done_urls: Optional[Set[str]] = None,
    ) -> tuple[List[SellerObservation], List[dict]]:
        """상품 목록에서 판매자 정보를 수집한다.

        Returns:
            (observations, failed_jobs)
        """
        already_done_urls = already_done_urls or set()
        observations: List[SellerObservation] = []
        failed_jobs: List[dict] = []

        total = len(products)
        logger.info(f"[상품] 총 {total}개 상품 상세 수집 시작")

        async with self.browser.new_page() as page:
            for idx, product in enumerate(products, start=1):
                url = product.product_url

                if url in already_done_urls:
                    logger.debug(f"[상품] 스킵 (이미 수집됨): {url}")
                    continue

                logger.info(f"[상품] ({idx}/{total}) {product.product_name[:40]}")

                obs, error = await self._crawl_single(page, product)

                if obs:
                    observations.append(obs)
                    already_done_urls.add(url)
                else:
                    failed_jobs.append({
                        "keyword": product.keyword,
                        "page": product.search_page,
                        "product_url": url,
                        "product_name": product.product_name,
                        "stage": "product",
                        "error_message": error or "unknown",
                        "retry_count": 0,
                        "logged_at": now_iso(),
                    })

                if idx < total:
                    await random_delay(
                        self.config.min_delay_sec, self.config.max_delay_sec
                    )

        logger.info(
            f"[상품] 완료: 성공 {len(observations)}개 / 실패 {len(failed_jobs)}개"
        )
        return observations, failed_jobs

    async def _crawl_single(
        self, page: Page, product: ProductItem
    ) -> tuple[Optional[SellerObservation], Optional[str]]:
        """단일 상품 상세페이지를 크롤링한다."""
        url = product.product_url

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.config.retry_count),
            wait=wait_exponential(multiplier=1, min=2, max=8),
            retry=retry_if_exception_type((PlaywrightTimeout, Exception)),
            reraise=False,
        ):
            with attempt:
                try:
                    response = await page.goto(
                        url,
                        timeout=self.config.timeout_sec * 1000,
                        wait_until="domcontentloaded",
                    )

                    if response is None:
                        raise RuntimeError("응답 없음")

                    status = response.status
                    if status == 403:
                        logger.warning(f"[상품] 403 차단: {url}")
                        return None, f"HTTP 403"
                    if status >= 400:
                        raise RuntimeError(f"HTTP {status}")

                    # 판매자 정보 섹션이 동적으로 로드될 수 있으므로 잠시 대기
                    await asyncio.sleep(1.5)

                    # 판매자 정보 섹션이 로드될 때까지 기다리기 (최대 5초)
                    try:
                        await page.wait_for_selector(
                            "div[class*='seller'], div[class*='vendor'], table[class*='seller']",
                            timeout=5000,
                        )
                    except PlaywrightTimeout:
                        pass  # 섹션이 없을 수도 있으므로 계속 진행

                    html = await page.content()

                    # HTML 스냅샷 저장
                    if self.config.save_html_snapshot:
                        await self._save_snapshot(url, html)

                    obs = parse_seller_info(
                        html,
                        product_url=url,
                        product_name=product.product_name,
                        keyword=product.keyword,
                    )

                    if obs is None:
                        logger.warning(f"[상품] 판매자 정보 없음: {url}")
                        return None, "판매자 정보 섹션 없음"

                    obs.collected_at = now_iso()
                    obs = normalize_observation(obs)
                    return obs, None

                except Exception as exc:
                    logger.warning(
                        f"[상품] 크롤링 실패 (시도 중): {url} - {exc}"
                    )
                    raise

        return None, "재시도 횟수 초과"

    async def _save_snapshot(self, url: str, html: str) -> None:
        """HTML 스냅샷을 파일로 저장한다."""
        try:
            filename = f"{url_to_hash(url)}.html"
            path = self._raw_dir / filename
            path.write_text(html, encoding="utf-8")
        except Exception as exc:
            logger.debug(f"[상품] 스냅샷 저장 실패: {exc}")


async def retry_failed_products(
    browser_manager: BrowserManager,
    config: AppConfig,
    failed_jobs: List[dict],
) -> tuple[List[SellerObservation], List[dict]]:
    """실패한 상품 목록을 재시도한다."""
    logger.info(f"[재시도] 실패 목록 재시도: {len(failed_jobs)}개")

    retry_products = [
        ProductItem(
            keyword=job.get("keyword", ""),
            search_page=job.get("page", 0),
            product_url=job["product_url"],
            product_name=job.get("product_name", ""),
        )
        for job in failed_jobs
        if job.get("product_url")
    ]

    crawler = ProductCrawler(browser_manager, config)
    return await crawler.crawl_products(retry_products)
