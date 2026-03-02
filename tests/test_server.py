import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock

from mcp_fetch.cache import CacheConfig, TransferCache
from mcp_fetch.crawler import CrawlResult
from mcp_fetch.server import _fetch_page_impl, _merge_query, _only_http_https, main


class TestServerHelpers(unittest.TestCase):
    def test_only_http_https_rejects_non_http(self) -> None:
        with self.assertRaises(ValueError):
            _only_http_https("file:///etc/passwd")

    def test_only_http_https_requires_host(self) -> None:
        with self.assertRaises(ValueError):
            _only_http_https("https:///path-only")

    def test_merge_query_appends(self) -> None:
        url = _merge_query("https://example.com/path?a=1", {"b": 2, "c": None})
        self.assertEqual(url, "https://example.com/path?a=1&b=2")


class TestFetchPageChunking(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_page_returns_transfer_and_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config = CacheConfig(cache_dir=Path(td), max_single_transfer_bytes=1024)
            cache = TransferCache(config)

            class _FakeCrawler:
                async def fetch_html(self, **kwargs: object) -> CrawlResult:
                    return CrawlResult(
                        ok=True,
                        url=str(kwargs.get("url")),
                        final_url=str(kwargs.get("url")),
                        status=200,
                        headers={"content-type": "text/html; charset=utf-8"},
                        html="<html>hello world</html>",
                        elapsed_ms=1,
                    )

            async def _fake_get_default_crawler() -> _FakeCrawler:
                return _FakeCrawler()

            with patch("mcp_fetch.server._cache", new=cache), patch("mcp_fetch.server._config", new=config), patch(
                    "mcp_fetch.server.get_default_crawler", new=_fake_get_default_crawler
            ):
                out = await _fetch_page_impl(url="http://example.com/", to_markdown=False, chunk_bytes=5)
                self.assertTrue(out["ok"])
                self.assertIsNotNone(out.get("transfer_id"))
                self.assertEqual(out["chunk"]["type"], "text")
                self.assertEqual(out["chunk"]["content"], "<html")
                self.assertFalse(out["done"])

                out2 = await _fetch_page_impl(transfer_id=out["transfer_id"], offset=out["next_offset"],
                                              chunk_bytes=1024)
                self.assertTrue(out2["ok"])
                self.assertTrue(out2["done"])
                self.assertEqual(out2["chunk"]["type"], "text")
                self.assertIn("hello world", out2["chunk"]["content"])


class TestAutoShutdown(unittest.TestCase):
    def test_main_calls_resource_close(self) -> None:
        with patch("mcp_fetch.server.mcp.run", new=lambda **kwargs: None), patch(
                "mcp_fetch.server._close_resources_sync"
        ) as closer:
            main()
            self.assertTrue(closer.called)


class TestShutdownTool(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_tool_closes_crawler(self) -> None:
        with patch("mcp_fetch.server.close_default_crawler", new_callable=AsyncMock) as mock_close_crawler, \
                patch("mcp_fetch.server._close_http_client", new_callable=AsyncMock) as mock_close_http:
            from mcp_fetch.server import shutdown
            res = await shutdown()
            self.assertTrue(res["ok"])
            mock_close_crawler.assert_awaited_once()
            mock_close_http.assert_awaited_once()


class TestHttpRequest(unittest.IsolatedAsyncioTestCase):
    async def test_http_request_basic(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config = CacheConfig(cache_dir=Path(td))
            cache = TransferCache(config)

            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "application/json"}
            mock_response.read.return_value = b'{"a": 1}'
            mock_response.url = "http://api.example.com/"

            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response

            with patch("mcp_fetch.server._cache", new=cache), \
                    patch("mcp_fetch.server._get_http_client", new=AsyncMock(return_value=mock_client)):
                from mcp_fetch.server import _http_request_impl

                # Test basic JSON
                res = await _http_request_impl(url="http://api.example.com/", to_markdown=False)
                self.assertTrue(res["ok"])
                self.assertEqual(res["chunk"]["type"], "text")
                self.assertEqual(res["chunk"]["content"], '{"a": 1}')
                self.assertEqual(res["content_type"], "application/json")

                # Test markdown conversion (should NOT happen for JSON)
                res = await _http_request_impl(url="http://api.example.com/", to_markdown=True)
                self.assertTrue(res["ok"])
                self.assertEqual(res["chunk"]["type"], "text")
                self.assertEqual(res["chunk"]["content"], '{"a": 1}')
                self.assertEqual(res["content_type"], "application/json")

    async def test_http_request_markdown_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config = CacheConfig(cache_dir=Path(td))
            cache = TransferCache(config)

            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "text/html"}
            mock_response.read.return_value = b'<h1>Hello</h1>'
            mock_response.text = '<h1>Hello</h1>'
            mock_response.url = "http://example.com/"

            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response

            with patch("mcp_fetch.server._cache", new=cache), \
                    patch("mcp_fetch.server._get_http_client", new=AsyncMock(return_value=mock_client)):
                from mcp_fetch.server import _http_request_impl

                # Test markdown conversion
                res = await _http_request_impl(url="http://example.com/", to_markdown=True)
                self.assertTrue(res["ok"])
                self.assertEqual(res["chunk"]["type"], "text")
                self.assertIn("# Hello", res["chunk"]["content"])
                self.assertIn("text/markdown", res["content_type"])


if __name__ == "__main__":
    unittest.main()
