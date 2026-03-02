import logging
import unittest

from mcp_fetch.server import _fetch_page_impl as fetch_page, shutdown

# Configure logging to see info
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("playwright").setLevel(logging.INFO)


class TestZhihuReal(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Ensure clean state
        await shutdown()

    async def asyncTearDown(self):
        # Ensure we clean up resources
        await shutdown()

    async def test_fetch_zhihu_article(self):
        url = "https://zhuanlan.zhihu.com/p/674072446"
        print(f"\nFetching {url} ...")

        # Call fetch_page directly
        # We increase chunk_bytes to ensure we get most content in one go for simple verification
        result = await fetch_page(
            url=url,
            to_markdown=True,
            timeout_ms=60000,  # Give it more time, but rely on internal logic to not wait too long
            chunk_bytes=1024 * 1024  # 1MB, should cover the whole article
        )

        if not result.get("ok"):
            print(f"Fetch failed: {result.get('error')}")

        self.assertTrue(result.get("ok"), f"Fetch failed: {result.get('error')}")
        self.assertTrue(result.get("to_markdown"))

        content = (result.get("chunk") or {}).get("content", "")
        print(f"\n--- Result Preview (First 500 chars) ---\n")
        print(content[:500])
        print(f"\n--- End Preview ---\n")

        print(f"Total length: {len(content)} bytes")
        print(f"Status: {result.get('status')}")
        print(f"Elapsed: {result.get('elapsed_ms')} ms")

        # Verify some expected content if possible (optional, as content changes)
        # But we expect at least some non-empty string
        self.assertGreater(len(content), 0)

    async def asyncTearDown(self):
        # Ensure we clean up resources
        await shutdown()


if __name__ == "__main__":
    unittest.main()
