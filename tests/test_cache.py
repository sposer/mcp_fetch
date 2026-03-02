import tempfile
import unittest
from pathlib import Path

from mcp_fetch.cache import CacheConfig, TransferCache, encode_chunk_for_json


class TestCacheUnit(unittest.IsolatedAsyncioTestCase):
    async def test_create_transfer_writes_and_reads(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config = CacheConfig(cache_dir=Path(td), max_single_transfer_bytes=1024)
            cache = TransferCache(config)

            transfer = await cache.create_transfer(
                final_url="https://example.com/",
                status=200,
                headers={"content-type": "text/plain; charset=utf-8"},
                content_type="text/plain; charset=utf-8",
                content=b"hello world",
            )

            self.assertTrue(transfer.done)
            self.assertEqual(transfer.status, 200)
            self.assertEqual(transfer.available_bytes, len(b"hello world"))

            data, next_offset, done = await transfer.read_chunk(offset=0, size=5, wait_timeout_seconds=0)
            self.assertEqual(data, b"hello")
            self.assertEqual(next_offset, 5)
            self.assertFalse(done)

            data, next_offset, done = await transfer.read_chunk(offset=next_offset, size=1024, wait_timeout_seconds=0)
            self.assertEqual(data, b" world")
            self.assertEqual(next_offset, len(b"hello world"))
            self.assertTrue(done)

    async def test_create_transfer_truncates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config = CacheConfig(cache_dir=Path(td), max_single_transfer_bytes=3)
            cache = TransferCache(config)

            transfer = await cache.create_transfer(
                final_url="https://example.com/",
                status=200,
                headers={},
                content_type="text/plain; charset=utf-8",
                content=b"abcd",
            )

            self.assertTrue(transfer.done)
            self.assertTrue(transfer.truncated)
            self.assertEqual(transfer.available_bytes, 3)
            self.assertEqual(transfer.file_path.stat().st_size, 3)
            self.assertEqual(transfer.total_bytes, 4)

    def test_encode_chunk_for_json_text_like(self) -> None:
        out = encode_chunk_for_json(b'{"a":1}', "application/json; charset=utf-8")
        self.assertEqual(out["chunk"]["type"], "text")
        self.assertEqual(out["chunk"]["content"], '{"a":1}')
