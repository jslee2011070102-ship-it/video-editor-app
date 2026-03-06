"""검색결과 크롤링 모듈.

키워드별로 쿠팡 검색 결과 페이지를 순회하며 상품 목록을 수집한다.
"""
from __future__ import annotations

import asyncio
import random
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
from .parser import ProductItem, parse_search_page
from .utils import ensure_dir, make_coupang_search_url, now_iso, safe_filename


class SearchCrawler:
    """키워드 기반 검색결과 크롤러."""

    def __init__(self, browser_manager: BrowserManager, config: AppConfig) -> None:
        self.browser = browser_manager
        self.config = config

    async def crawl_keyword(
        self,
        keyword: str,
        max_pages: Optional[int] = None,
        seen_product_ids: Optional[Set[str]] = None,
    ) -> List[ProductItem]:
        """한 키워드에 대해 max_pages 페이지까지 상품을 수집한다."""
        max_pages = max_pages or self.config.max_pages_per_keyword
        seen_product_ids = seen_product_ids or set()
        all_products: List[ProductItem] = []

        logger.info(f"[검색] 키워드 시작: '{keyword}' (최대 {max_pages}페이지)")

        async with self.browser.new_page() as page:
            # 1페이지는 홈에서 검색창 직접 입력, 이후 페이지는 URL 이동
            homepage_visited = False
            for page_num in range(1, max_pages + 1):
                products = await self._crawl_page(
                    page, keyword, page_num,
                    use_search_box=(page_num == 1 and not homepage_visited),
                )
                homepage_visited = True

                if not products:
                    logger.info(
                        f"[검색] '{keyword}' page={page_num}: 상품 없음. 순회 종료."
                    )
                    break

                # 중복 제거 (product_id 기준)
                new_products = []
                for item in products:
                    pid = item.product_id
                    if pid and pid in seen_product_ids:
                        continue
                    if pid:
                        seen_product_ids.add(pid)
                    item.crawl_time = now_iso()
                    new_products.append(item)

                all_products.extend(new_products)
                logger.info(
                    f"[검색] '{keyword}' page={page_num}: "
                    f"{len(new_products)}개 수집 (누계 {len(all_products)}개)"
                )

                # 수집 제한 적용
                limit = self.config.limit_products_per_keyword
                if limit > 0 and len(all_products) >= limit:
                    logger.info(f"[검색] 수집 제한 도달: {limit}개")
                    break

                if page_num < max_pages:
                    await random_delay(
                        self.config.min_delay_sec, self.config.max_delay_sec
                    )

        logger.info(
            f"[검색] 키워드 완료: '{keyword}' → 총 {len(all_products)}개 상품"
        )
        return all_products

    async def _crawl_page(
        self, page: Page, keyword: str, page_num: int,
        use_search_box: bool = False,
    ) -> List[ProductItem]:
        """검색 결과 한 페이지를 크롤링한다."""
        url = make_coupang_search_url(keyword, page_num)

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.config.retry_count),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=retry_if_exception_type((PlaywrightTimeout, Exception)),
            reraise=True,
        ):
            with attempt:
                if use_search_box and page_num == 1:
                    # 홈페이지 먼저 방문 → 검색창에 직접 입력 (인간 행동 모방)
                    logger.debug("[검색] 홈페이지 방문 후 검색창 입력 방식 사용")
                    resp = await page.goto(
                        "https://www.coupang.com",
                        timeout=self.config.timeout_sec * 1000,
                        wait_until="load",
                    )
                    if resp and resp.status == 403:
                        logger.warning("[검색] 홈페이지 403 차단 → URL 직접 접근으로 대체")
                        use_search_box = False
                    else:
                        # 홈페이지 로딩 후 짧게 대기
                        await asyncio.sleep(random.uniform(1.5, 3.0))

                        # 검색창 찾아 입력
                        _search_selectors = [
                            "input#headerSearchInput",
                            "input[name='q']",
                            "input[placeholder*='검색']",
                            "input.search-input",
                        ]
                        search_input = None
                        for sel in _search_selectors:
                            try:
                                search_input = await page.wait_for_selector(sel, timeout=5000)
                                if search_input:
                                    break
                            except PlaywrightTimeout:
                                continue

                        if search_input:
                            await search_input.click()
                            await asyncio.sleep(random.uniform(0.3, 0.7))
                            await search_input.type(keyword, delay=random.randint(50, 120))
                            await asyncio.sleep(random.uniform(0.3, 0.6))
                            await page.keyboard.press("Enter")
                            logger.debug(f"[검색] 검색창 입력 완료: '{keyword}'")
                        else:
                            logger.debug("[검색] 검색창 미발견 → URL 직접 접근")
                            use_search_box = False

                if not use_search_box or page_num > 1:
                    logger.debug(f"[검색] page={page_num} URL 직접 접근: {url}")
                    response = await page.goto(
                        url,
                        timeout=self.config.timeout_sec * 1000,
                        wait_until="load",
                    )
                    if response is None:
                        raise RuntimeError(f"응답이 없습니다: {url}")
                    status = response.status
                    if status == 403:
                        logger.warning(f"[검색] 403 차단됨. keyword={keyword}, page={page_num}")
                        return []
                    if status >= 400:
                        raise RuntimeError(f"HTTP {status}: {url}")

                # JS 렌더링 완료 대기
                _product_candidate_selectors = [
                    "li[class*='search-product']",
                    "li[class*='baby-product']",
                    "ul[class*='product-list'] li",
                    "a[href*='/vp/products/']",
                ]
                for _sel in _product_candidate_selectors:
                    try:
                        await page.wait_for_selector(_sel, timeout=10000, state="attached")
                        logger.debug(f"[검색] JS 렌더링 확인: '{_sel}'")
                        break
                    except PlaywrightTimeout:
                        continue
                else:
                    logger.debug("[검색] 상품 선택자 대기 실패 → 3초 추가 대기")
                    await asyncio.sleep(3)

                # 차단 페이지 감지
                if await self._is_blocked(page):
                    logger.warning(f"[검색] 차단 감지. keyword={keyword}, page={page_num}")
                    return []

                html = await page.content()

                # 검색결과 HTML 스냅샷 저장 (파서 디버깅용)
                if self.config.save_html_snapshot:
                    raw_dir = ensure_dir(self.config.raw_dir)
                    snap_name = f"search_{safe_filename(keyword)}_p{page_num}.html"
                    (raw_dir / snap_name).write_text(html, encoding="utf-8", errors="replace")

                products = parse_search_page(html, keyword, page_num)
                return products

        return []

    async def _is_blocked(self, page: Page) -> bool:
        """캡챠 또는 차단 페이지인지 확인한다."""
        try:
            title = await page.title()
            content = await page.content()
            blocked_signals = [
                "captcha", "robot", "차단", "접근이 제한",
                "access denied", "edgesuite.net", "you don't have permission",
            ]
            title_lower = title.lower()
            content_lower = content.lower()
            return any(sig in content_lower for sig in blocked_signals) or (
                "captcha" in title_lower or "access denied" in title_lower
            )
        except Exception:
            return False


async def crawl_all_keywords(
    browser_manager: BrowserManager,
    config: AppConfig,
    keywords: List[str],
    max_pages: Optional[int] = None,
) -> List[ProductItem]:
    """모든 키워드에 대해 검색결과를 수집한다 (순차 실행)."""
    all_products: List[ProductItem] = []
    seen_product_ids: Set[str] = set()
    crawler = SearchCrawler(browser_manager, config)

    for keyword in keywords:
        try:
            products = await crawler.crawl_keyword(
                keyword, max_pages=max_pages, seen_product_ids=seen_product_ids
            )
            all_products.extend(products)
        except Exception as exc:
            logger.error(f"[검색] 키워드 실패: '{keyword}' - {exc}")

    logger.info(f"[검색] 전체 완료: 총 {len(all_products)}개 상품")
    return all_products
