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

# 기본 User-Agent (최신 Chrome 안정 버전)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/132.0.0.0 Safari/537.36"
)

# Akamai/봇 탐지 우회용 초기화 스크립트
_STEALTH_SCRIPT = """
// navigator.webdriver 완전 제거
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Chrome 런타임 객체 주입 (없으면 봇으로 인식)
window.chrome = {
    runtime: {
        onMessage: { addListener: () => {} },
        connect: () => {},
    },
    loadTimes: () => {},
    csi: () => {},
    app: {},
};

// 플러그인 배열 위장 (0개이면 봇)
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const arr = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
        ];
        arr.__proto__ = PluginArray.prototype;
        return arr;
    },
});

// 언어 설정
Object.defineProperty(navigator, 'languages', { get: () => ['ko-KR', 'ko', 'en-US', 'en'] });

// permissions API 위장
const originalQuery = window.navigator.permissions?.query;
if (originalQuery) {
    window.navigator.permissions.query = (params) =>
        params.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(params);
}

// WebGL 벤더 위장
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) return 'Intel Inc.';
    if (parameter === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.call(this, parameter);
};
"""


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
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                # Akamai/봇 탐지 우회 핵심 플래그
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-extensions",
                "--disable-default-apps",
                "--no-first-run",
                "--no-default-browser-check",
                "--window-size=1280,900",
            ],
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
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept-Encoding": "gzip, deflate, br",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Sec-Ch-Ua": '"Chromium";v="132", "Google Chrome";v="132", "Not-A.Brand";v="99"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            },
        )
        return context

    @asynccontextmanager
    async def new_page(self) -> AsyncGenerator[Page, None]:
        """컨텍스트와 페이지를 생성하고 종료 시 자동으로 정리한다."""
        context = await self.new_context()
        page = await context.new_page()

        # Akamai 봇 탐지 종합 우회 스크립트
        await page.add_init_script(_STEALTH_SCRIPT)

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
