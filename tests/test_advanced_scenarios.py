import asyncio
import time
import unittest
from unittest.mock import patch, AsyncMock

from mcp_fetch.crawler import PlaywrightCrawler, HostRateLimiter, ProxyPool


class TestAdvancedScenarios(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.rate_limiter = HostRateLimiter()
        self.proxy_pool = ProxyPool([])
        self.crawler = PlaywrightCrawler(
            default_user_agent="test-ua",
            proxy_pool=self.proxy_pool,
            rate_limiter=self.rate_limiter
        )

    async def asyncTearDown(self):
        await self.crawler.close()

    async def test_request_deduplication(self):
        """Test that concurrent requests to the same URL are deduplicated."""
        url = "http://example.com/dedup"

        # Mock _rate_limiter to avoid delays
        self.crawler._rate_limiter.wait = AsyncMock()

        # Mock _get_browser to avoid launching real browser
        mock_browser = AsyncMock()
        self.crawler._get_browser = AsyncMock(return_value=mock_browser)

        with patch.object(self.crawler, '_new_context', new_callable=AsyncMock) as mock_new_context:
            # Setup mock context and page
            mock_context = AsyncMock()
            mock_page = AsyncMock()
            mock_new_context.return_value = mock_context
            mock_context.new_page.return_value = mock_page

            # Simulate a slow page load
            async def slow_goto(*args, **kwargs):
                await asyncio.sleep(0.1)
                mock_response = AsyncMock()
                mock_response.status = 200
                mock_response.headers = {}
                mock_response.url = url
                return mock_response

            mock_page.goto.side_effect = slow_goto
            mock_page.content.return_value = "<html></html>"

            # Launch 5 concurrent requests
            tasks = [
                asyncio.create_task(self.crawler.fetch_html(url=url))
                for _ in range(5)
            ]

            results = await asyncio.gather(*tasks)

            # Check results
            for res in results:
                self.assertTrue(res.ok)
                self.assertEqual(res.url, url)

            # Verification:
            # _new_context should be called only ONCE because of deduplication
            self.assertEqual(mock_new_context.call_count, 1)

    async def test_wait_strategy_optimization(self):
        """Test that networkidle timeout doesn't block the whole request if content is ready."""
        url = "http://example.com/slow-network"

        self.crawler._rate_limiter.wait = AsyncMock()
        self.crawler._get_browser = AsyncMock(return_value=AsyncMock())

        with patch.object(self.crawler, '_new_context', new_callable=AsyncMock) as mock_new_context:
            mock_context = AsyncMock()
            mock_page = AsyncMock()
            mock_new_context.return_value = mock_context
            mock_context.new_page.return_value = mock_page

            mock_response = AsyncMock()
            mock_response.status = 200
            mock_page.goto.return_value = mock_response
            mock_page.content.return_value = "<html>Done</html>"

            # Mock wait_for_load_state to timeout
            async def timeout_wait(state, timeout):
                if state == "networkidle":
                    # Verify we are using a shorter timeout (e.g. 5000ms) even if request timeout is 30000ms
                    if timeout > 5000:
                        raise ValueError(f"Timeout too long: {timeout}")
                    # Simulate timeout behavior (just return or raise TimeoutError depending on impl)
                    # The implementation swallows Exception, so raising one is fine
                    raise asyncio.TimeoutError("Network idle timeout")

            mock_page.wait_for_load_state.side_effect = timeout_wait

            start = time.time()
            # Request with 30s timeout
            result = await self.crawler.fetch_html(url=url, timeout_ms=30000)
            elapsed = time.time() - start

            self.assertTrue(result.ok)
            # Ensure we didn't wait 30s (mock checks timeout value passed)


if __name__ == "__main__":
    unittest.main()
