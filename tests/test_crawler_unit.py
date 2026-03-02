import unittest
from unittest.mock import AsyncMock, patch

from mcp_fetch.crawler import HostRateLimiter, PlaywrightCrawler, ProxyPool


class TestProxyPool(unittest.TestCase):
    def test_proxy_pool_round_robin(self) -> None:
        pool = ProxyPool(["http://a:1", "http://b:2"])
        self.assertEqual(pool.next(), "http://a:1")
        self.assertEqual(pool.next(), "http://b:2")
        self.assertEqual(pool.next(), "http://a:1")


class TestHostRateLimiter(unittest.IsolatedAsyncioTestCase):
    async def test_rate_limiter_sleeps(self) -> None:
        limiter = HostRateLimiter()
        calls: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            calls.append(float(seconds))

        with patch("mcp_fetch.crawler.asyncio.sleep", new=_fake_sleep):
            await limiter.wait("example.com", min_delay_ms=10, max_delay_ms=10)

        self.assertEqual(len(calls), 1)
        self.assertAlmostEqual(calls[0], 0.01, places=3)


class TestPlaywrightAutoInstall(unittest.IsolatedAsyncioTestCase):
    async def test_get_browser_auto_installs_and_retries(self) -> None:
        crawler = PlaywrightCrawler(
            default_user_agent="test-ua",
            proxy_pool=ProxyPool([]),
            rate_limiter=HostRateLimiter(),
        )

        fake_browser = object()
        launch = AsyncMock(side_effect=[
            Exception("BrowserType.launch: Executable doesn't exist at C:\\missing.exe"),
            fake_browser,
        ])

        class _FakeBrowserType:
            def __init__(self) -> None:
                self.launch = launch

        class _FakePlaywright:
            chromium = _FakeBrowserType()

        class _FakeAPW:
            async def start(self) -> object:
                return _FakePlaywright()

        with patch("mcp_fetch.crawler.async_playwright", new=lambda: _FakeAPW()), \
                patch.object(crawler, "_install_browser", new=AsyncMock()) as install_mock:
            b1 = await crawler._get_browser(None)
            self.assertIs(b1, fake_browser)
            self.assertEqual(launch.await_count, 2)
            install_mock.assert_awaited_once()

            b2 = await crawler._get_browser(None)
            self.assertIs(b2, fake_browser)
            self.assertEqual(launch.await_count, 2)

    async def test_get_browser_no_auto_install_re_raises(self) -> None:
        crawler = PlaywrightCrawler(
            default_user_agent="test-ua",
            proxy_pool=ProxyPool([]),
            rate_limiter=HostRateLimiter(),
        )

        launch = AsyncMock(side_effect=Exception("Executable doesn't exist at C:\\missing.exe"))

        class _FakeBrowserType:
            def __init__(self) -> None:
                self.launch = launch

        class _FakePlaywright:
            chromium = _FakeBrowserType()

        class _FakeAPW:
            async def start(self) -> object:
                return _FakePlaywright()

        with patch.dict("os.environ", {"MCP_FETCH_AUTO_INSTALL_PLAYWRIGHT": "0"}), \
                patch("mcp_fetch.crawler.async_playwright", new=lambda: _FakeAPW()), \
                patch.object(crawler, "_install_browser", new=AsyncMock()) as install_mock:
            with self.assertRaises(Exception) as ctx:
                await crawler._get_browser(None)
            self.assertIn("Executable doesn't exist", str(ctx.exception))
            self.assertEqual(launch.await_count, 1)
            install_mock.assert_not_awaited()

    async def test_install_attempt_resets_on_failure(self) -> None:
        crawler = PlaywrightCrawler(
            default_user_agent="test-ua",
            proxy_pool=ProxyPool([]),
            rate_limiter=HostRateLimiter(),
        )

        class _Proc:
            returncode = 1

            async def communicate(self) -> tuple[bytes, bytes]:
                return b"stdout", b"stderr"

            def kill(self) -> None:
                return None

        with patch("mcp_fetch.crawler.asyncio.create_subprocess_exec", new=AsyncMock(return_value=_Proc())):
            with self.assertRaises(RuntimeError):
                await crawler._install_browser("chromium")
            self.assertNotIn("chromium", crawler._install_attempted)
