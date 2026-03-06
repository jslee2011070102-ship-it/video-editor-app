"""Playwright 브라우저 관리 모듈.

BrowserManager: 브라우저/컨텍스트/페이지 생성 및 종료를 담당한다.

Akamai Bot Manager 우회 전략:
  - launch_persistent_context 로 쿠키/세션이 누적되는 영구 프로파일 사용
  - channel="chrome" 으로 시스템에 설치된 실제 Google Chrome 실행
  - 실행마다 프로파일이 쌓여 점점 실제 사용자에 가까워짐
"""
from __future__ import annotations

import asyncio
import random
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Optional

from loguru import logger
from playwright.async_api import (
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

# navigator.webdriver 제거 스크립트 (최소화 - 실제 Chrome에서는 불필요하지만 안전망)
_STEALTH_SCRIPT = """
try { Object.defineProperty(navigator, 'webdriver', { get: () => undefined }); } catch(e) {}
"""


class BrowserManager:
    """Playwright 영구 컨텍스트 브라우저 관리자.

    launch_persistent_context 를 사용하여 쿠키/세션 데이터를 영구 보존한다.
    Akamai 는 쿠키가 없는 새 컨텍스트를 봇으로 식별하므로,
    프로파일 디렉토리에 데이터가 쌓일수록 차단 확률이 낮아진다.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None

    @property
    def _profile_dir(self) -> Path:
        """영구 Chrome 프로파일 디렉토리."""
        p = Path(self.config.raw_dir).parent / "chrome_profile"
        p.mkdir(parents=True, exist_ok=True)
        return p

    async def start(self) -> None:
        """Playwright 와 영구 컨텍스트를 초기화한다."""
        self._playwright = await async_playwright().start()

        user_agent = self.config.user_agent or DEFAULT_USER_AGENT
        profile_dir = str(self._profile_dir)

        common_kwargs = dict(
            headless=self.config.headless,
            user_agent=user_agent,
            viewport={
                "width": self.config.viewport_width,
                "height": self.config.viewport_height,
            },
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )

        # 1순위: 실제 설치된 Google Chrome + 영구 프로파일
        try:
            self._context = await self._playwright.chromium.launch_persistent_context(
                profile_dir,
                channel="chrome",
                ignore_default_args=["--enable-automation"],
                **common_kwargs,
            )
            logger.info(
                f"브라우저 시작: 실제 Chrome(channel=chrome) + 영구프로파일 / "
                f"headless={self.config.headless} / profile={profile_dir}"
            )
            return
        except Exception as exc:
            logger.warning(f"실제 Chrome 실패({exc}) → Playwright Chromium 번들로 대체")

        # 2순위: Playwright 번들 Chromium + 영구 프로파일 (TLS 지문은 약하지만 쿠키는 유지)
        try:
            self._context = await self._playwright.chromium.launch_persistent_context(
                profile_dir,
                ignore_default_args=["--enable-automation"],
                **common_kwargs,
            )
            logger.info(
                f"브라우저 시작: Chromium 번들 + 영구프로파일 / headless={self.config.headless}"
            )
            return
        except Exception as exc2:
            logger.warning(f"영구 컨텍스트 실패({exc2}) → 임시 컨텍스트로 대체")

        # 3순위: 완전 임시 컨텍스트 (최후 폴백)
        browser = await self._playwright.chromium.launch(
            headless=self.config.headless,
            args=common_kwargs["args"],
        )
        self._context = await browser.new_context(
            user_agent=user_agent,
            viewport=common_kwargs["viewport"],
            locale="ko-KR",
            timezone_id="Asia/Seoul",
        )
        logger.info("브라우저 시작: 임시 컨텍스트(폴백)")

    async def stop(self) -> None:
        """컨텍스트와 Playwright 를 종료한다."""
        if self._context:
            await self._context.close()
            self._context = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("브라우저 종료")

    @asynccontextmanager
    async def new_page(self) -> AsyncGenerator[Page, None]:
        """영구 컨텍스트에서 새 페이지를 열고 종료 시 닫는다."""
        if not self._context:
            raise RuntimeError("브라우저가 초기화되지 않았습니다. start()를 먼저 호출하세요.")

        page = await self._context.new_page()
        await page.add_init_script(_STEALTH_SCRIPT)

        try:
            yield page
        finally:
            await page.close()


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
