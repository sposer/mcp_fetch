import asyncio
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from mcp_fetch.crawler import get_default_crawler


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        body = """
		<!doctype html>
		<html>
		<head><meta charset="utf-8"></head>
		<body>
			<div id="content">loading</div>
			<script>
				setTimeout(() => {
					const d = document.createElement("div");
					d.id = "late";
					d.textContent = "done";
					document.body.appendChild(d);
				}, 300);
			</script>
		</body>
		</html>
		""".encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class TestCrawlerIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_dynamic_content_wait_selector(self) -> None:
        if os.environ.get("MCP_FETCH_RUN_PLAYWRIGHT_TESTS") != "1":
            self.skipTest("Set MCP_FETCH_RUN_PLAYWRIGHT_TESTS=1 to run Playwright integration tests")

        server = HTTPServer(("127.0.0.1", 0), _Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            crawler = await get_default_crawler()
            result = await asyncio.wait_for(
                crawler.fetch_html(
                    url=f"http://127.0.0.1:{port}/",
                    timeout_ms=10_000,
                    wait_selector="#late",
                    max_scrolls=0,
                    min_delay_ms=0,
                    max_delay_ms=0,
                ),
                timeout=15.0,
            )
            if not result.ok:
                self.skipTest(result.error.get("message") if result.error else "crawl failed")
            self.assertIn('id="late"', result.html)
            self.assertIn("done", result.html)
        finally:
            server.shutdown()
            server.server_close()
            for _ in range(50):
                if not thread.is_alive():
                    break
                time.sleep(0.01)
