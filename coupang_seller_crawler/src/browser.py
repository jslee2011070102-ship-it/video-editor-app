"""Playwright 브라우저 관리 모듈.

BrowserManager: 브라우저/컨텍스트/페이지 생성 및 종료를 담당한다.

Akamai Bot Manager 우회 전략:
  - launch_persistent_context 로 쿠키/세션이 누적되는 영구 프로파일 사용
  - channel="chrome" 으로 시스템에 설치된 실제 Google Chrome 실행
  - ignore_default_args 로 Playwright 탐지 가능 플래그 최대 제거
  - 포괄적 stealth 스크립트로 JS 레벨 봇 탐지 우회
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

# Playwright 기본 인자 중 봇 탐지에 노출될 수 있는 플래그 목록
# ignore_default_args 에 추가하면 해당 플래그가 Chrome에 전달되지 않음
_IGNORE_DEFAULT_ARGS = [
    "--enable-automation",          # 자동화 배너 + webdriver 플래그
    "--disable-extensions",         # 실제 Chrome은 확장 프로그램 허용
    "--disable-sync",               # 실제 Chrome은 동기화 가능
    "--metrics-recording-only",     # 봇 탐지 신호
    "--no-service-autorun",         # 봇 탐지 신호
    "--password-store=basic",       # 시스템 키체인 대신 basic 사용 → 탐지 가능
    "--use-mock-keychain",          # 가짜 키체인 → 탐지 가능
    "--export-tagged-pdf",          # 불필요한 플래그
    "--disable-search-engine-choice-screen",  # 비정상 플래그
]

# 종합 스텔스 스크립트: JS 레벨 봇 탐지 우회
_STEALTH_SCRIPT = """
(function() {
  // 1. navigator.webdriver 제거
  try {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  } catch(e) {}

  // 2. CDP 추적 변수 제거 (Playwright/Selenium이 주입하는 cdc_ 변수)
  try {
    const cdcKeys = Object.keys(window).filter(k =>
      k.startsWith('cdc_') || k.includes('__playwright') || k.includes('__pw_')
    );
    cdcKeys.forEach(k => { try { delete window[k]; } catch(e) {} });
  } catch(e) {}

  // 3. window.chrome 객체 주입 (실제 Chrome에는 항상 존재)
  if (!window.chrome) {
    try {
      window.chrome = {
        app: {
          isInstalled: false,
          InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
          RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }
        },
        csi: function() {},
        loadTimes: function() { return {}; },
        runtime: {
          OnInstalledReason: {
            CHROME_UPDATE: 'chrome_update', INSTALL: 'install',
            SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update'
          },
          PlatformArch: { ARM: 'arm', ARM64: 'arm64', X86_32: 'x86-32', X86_64: 'x86-64' },
          PlatformOs: { ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', WIN: 'win' },
          RequestUpdateCheckStatus: {
            NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available'
          }
        }
      };
    } catch(e) {}
  }

  // 4. navigator.permissions.query 패치 (Notification 권한 처리)
  try {
    const origQuery = window.navigator.permissions.query;
    window.navigator.permissions.__proto__.query = function(parameters) {
      if (parameters.name === 'notifications') {
        return Promise.resolve({ state: Notification.permission });
      }
      return origQuery.call(this, parameters);
    };
  } catch(e) {}

  // 5. navigator.plugins 비어있으면 가짜 플러그인 주입
  try {
    if (navigator.plugins.length === 0) {
      Object.defineProperty(navigator, 'plugins', {
        get: () => {
          const arr = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }
          ];
          arr.item = i => arr[i];
          arr.namedItem = n => arr.find(p => p.name === n) || null;
          arr.refresh = () => {};
          return arr;
        }
      });
    }
  } catch(e) {}

  // 6. navigator.languages 보장
  try {
    if (!navigator.languages || navigator.languages.length === 0) {
      Object.defineProperty(navigator, 'languages', {
        get: () => ['ko-KR', 'ko', 'en-US', 'en']
      });
    }
  } catch(e) {}

  // 7. iframe contentWindow.navigator.webdriver 패치
  try {
    const origGetter = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentWindow').get;
    Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
      get: function() {
        const win = origGetter.call(this);
        if (win && win.navigator && win.navigator.webdriver !== undefined) {
          try { Object.defineProperty(win.navigator, 'webdriver', { get: () => undefined }); } catch(e) {}
        }
        return win;
      }
    });
  } catch(e) {}
})();
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
                ignore_default_args=_IGNORE_DEFAULT_ARGS,
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
                ignore_default_args=_IGNORE_DEFAULT_ARGS,
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

    async def _has_akamai_cookies(self) -> bool:
        """Akamai Bot Manager 쿠키(bm_sz, _abck)가 설정되어 있는지 확인한다."""
        if not self._context:
            return False
        cookies = await self._context.cookies("https://www.coupang.com")
        akamai_names = {"bm_sz", "_abck", "ak_bmsc"}
        return any(c["name"] in akamai_names for c in cookies)

    async def warmup_akamai_session(self) -> bool:
        """쿠팡 홈을 방문해 Akamai 세션 쿠키를 초기화한다.

        Returns:
            True: 쿠키가 설정됨 (차단 없음)
            False: 403 차단 또는 쿠키 미설정
        """
        if not self._context:
            return False

        # 이미 Akamai 쿠키가 있으면 스킵
        if await self._has_akamai_cookies():
            logger.debug("[웜업] Akamai 세션 쿠키 이미 존재 → 웜업 스킵")
            return True

        logger.info("[웜업] Akamai 세션 초기화 중 (coupang.com 홈 방문)...")
        page = await self._context.new_page()
        await page.add_init_script(_STEALTH_SCRIPT)

        try:
            resp = await page.goto(
                "https://www.coupang.com",
                wait_until="load",
                timeout=30000,
            )
            if resp is None or resp.status == 403:
                logger.warning("[웜업] 홈 403 차단 → 쿠키 주입 후 재시도 필요")
                return False

            # 짧은 스크롤로 인간 행동 모방
            await asyncio.sleep(random.uniform(1.5, 2.5))
            await page.evaluate("window.scrollTo({top: 300, behavior: 'smooth'})")
            await asyncio.sleep(random.uniform(0.8, 1.5))
            await page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
            await asyncio.sleep(random.uniform(0.5, 1.0))

            has_cookies = await self._has_akamai_cookies()
            if has_cookies:
                logger.info("[웜업] Akamai 세션 쿠키 설정 완료")
            else:
                logger.warning("[웜업] 홈 방문 후에도 Akamai 쿠키 없음 → 차단 상태")
            return has_cookies

        except Exception as exc:
            logger.warning(f"[웜업] 예외 발생: {exc}")
            return False
        finally:
            await page.close()

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
    """컨텍스트 매니저: BrowserManager 를 생성하고 사용 후 종료한다.

    브라우저 시작 후 Akamai 세션 웜업을 자동으로 수행한다.
    이미 쿠키가 있으면 웜업을 건너뛴다.
    """
    manager = BrowserManager(config)
    await manager.start()
    try:
        # Akamai 세션 쿠키 자동 초기화 (쿠키 없을 때만 홈 방문)
        await manager.warmup_akamai_session()
        yield manager
    finally:
        await manager.stop()
