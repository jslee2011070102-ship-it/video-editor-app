"""Playwright 브라우저 관리 모듈.

BrowserManager: 브라우저/컨텍스트/페이지 생성 및 종료를 담당한다.
"""
from __future__ import annotations

import asyncio
import random
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from loguru import logger
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from .config_loader import AppConfig

# 기본 User-Agent
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class BrowserManager:
    """Playwright 브라우저 생명주기를 관리한다."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None

    async def start(self) -> None:
        """Playwright 와 브라우저를 초기화한다."""
        self._playwright = await async_playwright().start()

        browser_type = self.config.browser_type.lower()
        launcher = {
            "chromium": self._playwright.chromium,
            "firefox": self._playwright.firefox,
            "webkit": self._playwright.webkit,
        }.get(browser_type, self._playwright.chromium)

        self._browser = await launcher.launch(
            headless=self.config.headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        logger.info(f"브라우저 시작: {browser_type} / headless={self.config.headless}")

    async def stop(self) -> None:
        """브라우저와 Playwright 를 종료한다."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("브라우저 종료")

    async def new_context(self) -> BrowserContext:
        """새 브라우저 컨텍스트를 생성한다."""
        if not self._browser:
            raise RuntimeError("브라우저가 초기화되지 않았습니다. start()를 먼저 호출하세요.")

        user_agent = self.config.user_agent or DEFAULT_USER_AGENT

        context = await self._browser.new_context(
            user_agent=user_agent,
            viewport={
                "width": self.config.viewport_width,
                "height": self.config.viewport_height,
            },
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            extra_http_headers={
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )
        return context

    @asynccontextmanager
    async def new_page(self) -> AsyncGenerator[Page, None]:
        """컨텍스트와 페이지를 생성하고 종료 시 자동으로 정리한다."""
        context = await self.new_context()
        page = await context.new_page()

        # 봇 탐지 우회 - navigator.webdriver 숨기기
        await page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        try:
            yield page
        finally:
            await page.close()
            await context.close()


async def random_delay(min_sec: float, max_sec: float) -> None:
    """min_sec ~ max_sec 사이의 랜덤한 시간을 대기한다."""
    delay = random.uniform(min_sec, max_sec)
    logger.debug(f"딜레이: {delay:.2f}초")
    await asyncio.sleep(delay)


@asynccontextmanager
async def managed_browser(config: AppConfig) -> AsyncGenerator[BrowserManager, None]:
    """컨텍스트 매니저: BrowserManager 를 생성하고 사용 후 종료한다."""
    manager = BrowserManager(config)
    await manager.start()
    try:
        yield manager
    finally:
        await manager.stop()
