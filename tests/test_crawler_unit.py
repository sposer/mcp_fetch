import unittest
from unittest.mock import patch

from mcp_fetch.crawler import HostRateLimiter, ProxyPool


class TestProxyPool(unittest.IsolatedAsyncioTestCase):
    async def test_proxy_pool_round_robin(self) -> None:
        pool = ProxyPool(["http://a:1", "http://b:2"])
        self.assertEqual(await pool.next(), "http://a:1")
        self.assertEqual(await pool.next(), "http://b:2")
        self.assertEqual(await pool.next(), "http://a:1")


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
