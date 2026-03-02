from __future__ import annotations

import asyncio
import logging
import random
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from .base.env import env_int, env_list, env_str

log = logging.getLogger("mcp_fetch.crawler")


class ProxyPool:
    def __init__(self, proxies: list[str] | None = None) -> None:
        self._proxies = [p for p in (proxies or []) if p]
        self._idx = 0

    def next(self) -> str | None:
        if not self._proxies:
            return None
        p = self._proxies[self._idx % len(self._proxies)]
        self._idx += 1
        return p


class HostRateLimiter:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._next_allowed: dict[str, float] = {}

    async def wait(self, host: str, *, min_delay_ms: int, max_delay_ms: int) -> None:
        delay = random.uniform(min_delay_ms, max_delay_ms) / 1000.0
        async with self._lock:
            now = time.time()
            allowed = self._next_allowed.get(host, 0.0)
            wait_time = max(0.0, allowed - now)
            self._next_allowed[host] = now + wait_time + delay

        if wait_time > 0:
            await asyncio.sleep(wait_time)


@dataclass(frozen=True)
class CrawlResult:
    ok: bool
    url: str
    final_url: str
    status: int
    headers: dict[str, str]
    html: str
    elapsed_ms: int
    error: dict[str, Any] | None = None


class PlaywrightCrawler:
    def __init__(
            self,
            *,
            default_user_agent: str,
            proxy_pool: ProxyPool,
            rate_limiter: HostRateLimiter,
            browser_name: str = "chromium",
    ) -> None:
        self._default_user_agent = default_user_agent
        self._proxy_pool = proxy_pool
        self._rate_limiter = rate_limiter
        self._browser_name = browser_name

        self._pw_lock = asyncio.Lock()
        self._install_lock = asyncio.Lock()
        self._install_attempted: set[str] = set()
        self._pw: Playwright | None = None
        self._browsers: dict[str | None, Browser] = {}
        self._custom_proxy_pools: dict[tuple[str, ...], ProxyPool] = {}
        self._active_crawls: dict[tuple[str, str | None], asyncio.Future[CrawlResult]] = {}
        self._active_crawls_lock = asyncio.Lock()

    def _is_missing_executable(self, e: Exception) -> bool:
        msg = str(e).lower()
        return "executable doesn't exist" in msg or (
                    "playwright install" in msg and ("download new browsers" in msg or "looks like playwright" in msg))

    async def _install_browser(self, name: str) -> None:
        if env_int("MCP_FETCH_AUTO_INSTALL_PLAYWRIGHT", 1) != 1:
            return
        name = name or "chromium"
        async with self._install_lock:
            if name in self._install_attempted:
                return
            self._install_attempted.add(name)

            log.warning("Installing Playwright browser %s...", name)
            cmd = [sys.executable, "-m", "playwright", "install", name]
            try:
                proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                            stderr=asyncio.subprocess.PIPE)
                timeout = env_int("MCP_FETCH_PLAYWRIGHT_INSTALL_TIMEOUT_MS", 600000) / 1000.0
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                if proc.returncode != 0:
                    raise RuntimeError(
                        f"Install failed (code={proc.returncode}): {(stderr or stdout).decode(errors='replace')[-500:]}")
            except Exception:
                self._install_attempted.discard(name)
                raise

    async def _get_playwright(self) -> Playwright:
        if self._pw is not None:
            return self._pw
        async with self._pw_lock:
            if self._pw is not None:
                return self._pw
            self._pw = await async_playwright().start()
            return self._pw

    async def _get_browser(self, proxy: str | None) -> Browser:
        if proxy in self._browsers:
            return self._browsers[proxy]
        async with self._pw_lock:
            if proxy in self._browsers:
                return self._browsers[proxy]

            # Initialize Playwright if needed (Lazy init under lock)
            if self._pw is None:
                log.debug("Starting Playwright...")
                self._pw = await async_playwright().start()
            pw = self._pw

            browser_type = getattr(pw, self._browser_name, pw.chromium)
            kwargs: dict[str, Any] = {
                "headless": True,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--start-maximized",
                ],
                "ignore_default_args": ["--enable-automation"],
            }
            if proxy:
                kwargs["proxy"] = {"server": proxy}

            log.debug("Launching browser %s (proxy=%s)...", self._browser_name, proxy)
            try:
                browser = await browser_type.launch(**kwargs)
            except Exception as e:
                if self._is_missing_executable(e) and env_int("MCP_FETCH_AUTO_INSTALL_PLAYWRIGHT", 1) == 1:
                    try:
                        await self._install_browser(self._browser_name)
                        browser = await browser_type.launch(**kwargs)
                    except Exception as install_err:
                        raise RuntimeError(f"Auto-install failed: {install_err}") from e
                else:
                    raise
            self._browsers[proxy] = browser
            return browser

    async def close(self) -> None:
        async with self._pw_lock:
            for b in list(self._browsers.values()):
                try:
                    await b.close()
                except Exception:
                    pass
            self._browsers.clear()
            if self._pw is not None:
                try:
                    await self._pw.stop()
                except Exception:
                    pass
                self._pw = None

    async def _new_context(self, browser: Browser, *, user_agent: str, extra_headers: dict[str, str]) -> BrowserContext:
        context = await browser.new_context(
            user_agent=user_agent,
            locale=env_str("MCP_FETCH_LOCALE", "zh-CN"),
            timezone_id=env_str("MCP_FETCH_TIMEZONE", "Asia/Shanghai"),
            viewport={"width": env_int("MCP_FETCH_VIEWPORT_W", 1920),
                      "height": env_int("MCP_FETCH_VIEWPORT_H", 1080)},
            extra_http_headers=extra_headers,
            java_script_enabled=True,
        )
        await context.add_init_script(
            """
            // Overwrite the `webdriver` property to avoid detection
            Object.defineProperty(navigator, 'webdriver', {
                get: () => false,
            });

            // Mock chrome object
            if (!window.chrome) {
                window.chrome = {
                    runtime: {},
                    loadTimes: function() {},
                    csi: function() {},
                    app: {}
                };
            }

            // Mock plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });

            // Mock languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['zh-CN', 'zh', 'en'],
            });
            """
        )
        return context

    async def _simulate_user(self, page: Page) -> None:
        try:
            viewport = page.viewport_size or {"width": 1366, "height": 768}
            w = int(viewport.get("width", 1366))
            h = int(viewport.get("height", 768))
            start_x = random.randint(1, max(2, w // 3))
            start_y = random.randint(1, max(2, h // 3))
            await page.mouse.move(start_x, start_y)
            steps = random.randint(8, 20)
            for _ in range(steps):
                x = random.randint(1, max(2, w - 2))
                y = random.randint(1, max(2, h - 2))
                await page.mouse.move(x, y, steps=random.randint(2, 6))
                await page.wait_for_timeout(random.randint(10, 60))
        except Exception:
            return

    async def _auto_scroll(self, page: Page, *, max_scrolls: int) -> None:
        stable = 0
        last_height = await page.evaluate("() => document.body ? document.body.scrollHeight : 0")
        for _ in range(max(0, int(max_scrolls))):
            await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(250)
            new_height = await page.evaluate("() => document.body ? document.body.scrollHeight : 0")
            if new_height == last_height:
                stable += 1
                if stable >= 2:
                    return
            else:
                stable = 0
                last_height = new_height

    async def fetch_html(
            self,
            *,
            url: str,
            headers: dict[str, str] | None = None,
            timeout_ms: float = 30000,
            wait_selector: str | None = None,
            max_scrolls: int = 8,
            min_delay_ms: int = 150,
            max_delay_ms: int = 450,
            proxy: str | None = None,
            proxy_pool: list[str] | None = None,
            user_agent: str | None = None,
    ) -> CrawlResult:
        start = time.time()
        parsed = urlparse(url)
        host = parsed.netloc or "unknown"

        log.debug("Waiting for rate limiter for %s", host)
        await self._rate_limiter.wait(host, min_delay_ms=min_delay_ms, max_delay_ms=max_delay_ms)

        if proxy is None:
            if proxy_pool is not None:
                key = tuple([p for p in proxy_pool if p])
                if key:
                    pool = self._custom_proxy_pools.get(key)
                    if pool is None:
                        pool = ProxyPool(list(key))
                        self._custom_proxy_pools[key] = pool
                    proxy = pool.next()
                else:
                    proxy = None
            else:
                env_pool = env_list("MCP_FETCH_PROXIES")
                if env_pool:
                    key = tuple(env_pool)
                    pool = self._custom_proxy_pools.get(key)
                    if pool is None:
                        pool = ProxyPool(list(key))
                        self._custom_proxy_pools[key] = pool
                    proxy = pool.next()
                else:
                    proxy = self._proxy_pool.next()

        dedup_key = (url, proxy)
        future: asyncio.Future[CrawlResult] | None = None
        owner = False

        async with self._active_crawls_lock:
            if dedup_key in self._active_crawls:
                log.info("Joining existing crawl", extra={"url": url})
                return await self._active_crawls[dedup_key]
            future = asyncio.Future()
            self._active_crawls[dedup_key] = future
            owner = True

        try:
            ua = str(user_agent or self._default_user_agent)
            extra_headers = {str(k): str(v) for k, v in (headers or {}).items() if v is not None}

            # Add standard browser headers to mimic real Chrome
            extra_headers.setdefault("accept-language",
                                     env_str("MCP_FETCH_ACCEPT_LANGUAGE", "zh-CN,zh;q=0.9,en;q=0.8") or "")
            extra_headers.setdefault("accept",
                                     "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7")
            extra_headers.setdefault("upgrade-insecure-requests", "1")

            # Client Hints (Must match the User Agent version 123)
            extra_headers.setdefault("sec-ch-ua", '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"')
            extra_headers.setdefault("sec-ch-ua-mobile", "?0")
            extra_headers.setdefault("sec-ch-ua-platform", '"Windows"')

            browser = await self._get_browser(proxy)
            context: BrowserContext | None = None
            page: Page | None = None
            resp_headers: dict[str, str] = {}
            status = 0
            final_url = url

            try:
                context = await self._new_context(browser, user_agent=ua, extra_headers=extra_headers)
                page = await context.new_page()
                if env_int("MCP_FETCH_BLOCK_RESOURCES", 0) == 1:
                    async def _route_handler(route: Any) -> None:
                        if getattr(route.request, "resource_type", "") in ("image", "media", "font"):
                            await route.abort()
                        else:
                            await route.continue_()

                    await page.route("**/*", _route_handler)
                log.debug("Navigating to %s", url)
                response = await page.goto(url, wait_until="domcontentloaded", timeout=float(timeout_ms))
                if response is not None:
                    try:
                        status = int(response.status)
                    except Exception:
                        status = 0
                    try:
                        resp_headers = {k: v for k, v in response.headers.items()}
                    except Exception:
                        resp_headers = {}
                    try:
                        final_url = response.url
                    except Exception:
                        final_url = url

                idle_timeout = min(float(timeout_ms), 5000.0)
                try:
                    await page.wait_for_load_state("networkidle", timeout=idle_timeout)
                except Exception:
                    pass

                await self._simulate_user(page)
                if wait_selector:
                    await page.wait_for_selector(str(wait_selector), timeout=float(timeout_ms))
                await self._auto_scroll(page, max_scrolls=max_scrolls)
                html = await page.content()
                elapsed_ms = int((time.time() - start) * 1000)
                result = CrawlResult(
                    ok=True,
                    url=url,
                    final_url=str(final_url),
                    status=status,
                    headers={k.lower(): v for k, v in resp_headers.items()},
                    html=html,
                    elapsed_ms=elapsed_ms,
                )
                if owner and future is not None and not future.done():
                    future.set_result(result)
                return result
            except Exception as e:
                elapsed_ms = int((time.time() - start) * 1000)
                err = {"type": type(e).__name__, "message": str(e)}
                log.warning("crawl failed", extra={"url": url, "error": err})
                error_result = CrawlResult(
                    ok=False,
                    url=url,
                    final_url=str(final_url),
                    status=status,
                    headers={k.lower(): v for k, v in resp_headers.items()},
                    html="",
                    elapsed_ms=elapsed_ms,
                    error=err,
                )
                if owner and future is not None and not future.done():
                    future.set_result(error_result)
                return error_result
            finally:
                try:
                    if page is not None:
                        await page.close()
                except Exception:
                    pass
                try:
                    if context is not None:
                        await context.close()
                except Exception:
                    pass
        finally:
            if owner:
                async with self._active_crawls_lock:
                    self._active_crawls.pop(dedup_key, None)


_default_crawler: PlaywrightCrawler | None = None
_crawler_lock = asyncio.Lock()


async def get_default_crawler() -> PlaywrightCrawler:
    global _default_crawler
    if _default_crawler is not None:
        return _default_crawler
    async with _crawler_lock:
        if _default_crawler is not None:
            return _default_crawler
        default_ua = env_str(
            "MCP_FETCH_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        ) or ""
        proxies = env_list("MCP_FETCH_PROXIES")
        pool = ProxyPool(proxies)
        _default_crawler = PlaywrightCrawler(
            default_user_agent=default_ua,
            proxy_pool=pool,
            rate_limiter=HostRateLimiter(),
            browser_name=env_str("MCP_FETCH_BROWSER", "chromium") or "chromium",
        )
        return _default_crawler


async def close_default_crawler() -> None:
    global _default_crawler
    async with _crawler_lock:
        crawler = _default_crawler
        _default_crawler = None
    if crawler is None:
        return
    await crawler.close()
