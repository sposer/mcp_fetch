import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional
from unittest.mock import patch

import httpx

from mcp_fetch.cache import CacheConfig, TransferCache, encode_chunk_for_json


class _FakeResponse:
	def __init__(
		self,
		*,
		status_code: int = 200,
		url: str = "https://example.com/",
		headers: Optional[Dict[str, str]] = None,
		chunks: Optional[list[bytes]] = None,
	) -> None:
		self.status_code = status_code
		self.url = httpx.URL(url)
		self.headers = headers or {"content-type": "text/plain; charset=utf-8"}
		self._chunks = chunks or []

	async def aiter_bytes(self) -> AsyncIterator[bytes]:
		for c in self._chunks:
			await asyncio.sleep(0)
			yield c


class _FakeStream:
	def __init__(self, response: _FakeResponse) -> None:
		self._response = response

	async def __aenter__(self) -> _FakeResponse:
		return self._response

	async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
		return None


class _FakeAsyncClient:
	def __init__(self, response: _FakeResponse, *, raise_on_stream: Optional[BaseException] = None) -> None:
		self._response = response
		self._raise_on_stream = raise_on_stream

	async def __aenter__(self) -> "_FakeAsyncClient":
		return self

	async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
		return None

	def stream(self, *args: Any, **kwargs: Any) -> _FakeStream:
		if self._raise_on_stream is not None:
			raise self._raise_on_stream
		return _FakeStream(self._response)


class TestCacheUnit(unittest.IsolatedAsyncioTestCase):
	async def test_download_writes_and_reads(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			config = CacheConfig(cache_dir=Path(td), max_single_transfer_bytes=1024)
			cache = TransferCache(config)

			response = _FakeResponse(chunks=[b"hello", b" ", b"world"])
			fake_client_factory = lambda *args, **kwargs: _FakeAsyncClient(response)

			with patch("mcp_fetch.cache.httpx.AsyncClient", new=fake_client_factory):
				transfer = await cache.start_request(
					method="GET",
					url="https://example.com/",
					headers={},
					content=None,
					timeout_seconds=1,
					follow_redirects=False,
				)
				await transfer._task

			self.assertTrue(transfer.done)
			self.assertIsNone(transfer.error)
			self.assertEqual(transfer.status, 200)
			self.assertEqual(transfer.available_bytes, len(b"hello world"))

			data, next_offset, done = await transfer.read_chunk(offset=0, size=5, wait_timeout_seconds=1)
			self.assertEqual(data, b"hello")
			self.assertEqual(next_offset, 5)
			self.assertFalse(done)

			data, next_offset, done = await transfer.read_chunk(offset=next_offset, size=1024, wait_timeout_seconds=1)
			self.assertEqual(data, b" world")
			self.assertEqual(next_offset, len(b"hello world"))
			self.assertTrue(done)

	async def test_download_truncates(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			config = CacheConfig(cache_dir=Path(td), max_single_transfer_bytes=3)
			cache = TransferCache(config)

			response = _FakeResponse(chunks=[b"abcd"])
			fake_client_factory = lambda *args, **kwargs: _FakeAsyncClient(response)

			with patch("mcp_fetch.cache.httpx.AsyncClient", new=fake_client_factory):
				transfer = await cache.start_request(
					method="GET",
					url="https://example.com/",
					headers={},
					content=None,
					timeout_seconds=1,
					follow_redirects=False,
				)
				await transfer._task

			self.assertTrue(transfer.done)
			self.assertTrue(transfer.truncated)
			self.assertEqual(transfer.available_bytes, 3)
			self.assertEqual(transfer.file_path.stat().st_size, 3)

	async def test_download_records_error(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			config = CacheConfig(cache_dir=Path(td), max_single_transfer_bytes=1024)
			cache = TransferCache(config)

			response = _FakeResponse(chunks=[b"never"])
			fake_client_factory = lambda *args, **kwargs: _FakeAsyncClient(response, raise_on_stream=RuntimeError("boom"))

			with patch("mcp_fetch.cache.httpx.AsyncClient", new=fake_client_factory):
				transfer = await cache.start_request(
					method="GET",
					url="https://example.com/",
					headers={},
					content=None,
					timeout_seconds=1,
					follow_redirects=False,
				)
				await transfer._task

			self.assertTrue(transfer.done)
			self.assertIsNotNone(transfer.error)
			self.assertEqual(transfer.error.get("type"), "RuntimeError")

	def test_encode_chunk_for_json_text_like(self) -> None:
		out = encode_chunk_for_json(b'{"a":1}', "application/json; charset=utf-8")
		self.assertEqual(out["chunk_text"], '{"a":1}')
		self.assertTrue(out["chunk_base64"])


class TestCacheIntegration(unittest.IsolatedAsyncioTestCase):
	async def test_github_smoke(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			config = CacheConfig(cache_dir=Path(td), max_single_transfer_bytes=64 * 1024, wait_chunk_timeout_seconds=5)
			cache = TransferCache(config)

			try:
				transfer = await cache.start_request(
					method="GET",
					url="https://github.com/",
					headers={"user-agent": "mcp-fetch-tests"},
					content=None,
					timeout_seconds=10,
					follow_redirects=True,
				)
				await transfer._task
			except Exception as e:
				self.skipTest(str(e))

			if transfer.error is not None:
				self.skipTest(f"{transfer.error.get('type')}: {transfer.error.get('message')}")

			self.assertIn(transfer.status, (200, 301, 302))
			self.assertGreater(transfer.available_bytes, 0)
