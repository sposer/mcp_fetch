from __future__ import annotations

import asyncio
import base64
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx


def _env_int(name: str, default: int) -> int:
	try:
		return int(os.environ.get(name, str(default)))
	except Exception:
		return default


def _env_path(name: str, default: str) -> Path:
	return Path(os.environ.get(name, default)).resolve()


@dataclass
class CacheConfig:
	cache_dir: Path = field(default_factory=lambda: _env_path("MCP_FETCH_CACHE_DIR", "./.mcp-fetch-cache"))
	ttl_seconds: int = field(default_factory=lambda: _env_int("MCP_FETCH_TTL_SECONDS", 1800))
	max_cache_bytes_total: int = field(default_factory=lambda: _env_int("MCP_FETCH_MAX_CACHE_BYTES_TOTAL", 512 * 1024 * 1024))
	max_single_transfer_bytes: int = field(default_factory=lambda: _env_int("MCP_FETCH_MAX_SINGLE_TRANSFER_BYTES", 200 * 1024 * 1024))
	wait_chunk_timeout_seconds: int = field(default_factory=lambda: _env_int("MCP_FETCH_WAIT_CHUNK_TIMEOUT_SECONDS", 30))


@dataclass
class Transfer:
	transfer_id: str
	file_path: Path
	created_at: float
	last_access: float
	status: int
	headers: Dict[str, str]
	final_url: str
	content_type: Optional[str]
	total_bytes: Optional[int]
	truncated: bool = False
	error: Optional[Dict[str, Any]] = None
	available_bytes: int = 0
	done: bool = False
	_condition: asyncio.Condition = field(default_factory=asyncio.Condition, repr=False)
	_task: Optional[asyncio.Task[None]] = field(default=None, repr=False)

	def touch(self) -> None:
		self.last_access = time.time()

	async def wait_for_bytes(self, min_bytes: int, timeout_seconds: int) -> None:
		deadline = time.time() + timeout_seconds
		async with self._condition:
			while self.available_bytes < min_bytes and not self.done and self.error is None:
				remaining = deadline - time.time()
				if remaining <= 0:
					return
				try:
					await asyncio.wait_for(self._condition.wait(), timeout=remaining)
				except asyncio.TimeoutError:
					return

	async def read_chunk(self, offset: int, size: int, *, wait_timeout_seconds: int) -> Tuple[bytes, int, bool]:
		if offset < 0:
			offset = 0
		if size <= 0:
			size = 1

		target = offset + size
		await self.wait_for_bytes(target, wait_timeout_seconds)

		max_readable = self.available_bytes
		if self.done or self.error is not None:
			max_readable = max(self.available_bytes, max_readable)

		if offset >= max_readable:
			return b"", offset, bool(self.done or self.error is not None)

		read_len = min(size, max_readable - offset)
		with self.file_path.open("rb") as f:
			f.seek(offset)
			data = f.read(read_len)

		next_offset = offset + len(data)
		return data, next_offset, bool(self.done or self.error is not None) and next_offset >= self.available_bytes


class TransferCache:
	def __init__(self, config: CacheConfig) -> None:
		self._config = config
		self._config.cache_dir.mkdir(parents=True, exist_ok=True)
		self._transfers: Dict[str, Transfer] = {}
		self._lock = asyncio.Lock()

	def _cache_size_bytes(self) -> int:
		total = 0
		for t in self._transfers.values():
			try:
				total += t.file_path.stat().st_size
			except FileNotFoundError:
				continue
		return total

	def _evict_if_needed_locked(self) -> None:
		now = time.time()
		# TTL eviction
		expired = [k for k, t in self._transfers.items() if (now - t.last_access) > self._config.ttl_seconds]
		for k in expired:
			self._drop_locked(k)

		# Size-based eviction (LRU)
		while self._cache_size_bytes() > self._config.max_cache_bytes_total and self._transfers:
			oldest_key = min(self._transfers.items(), key=lambda kv: kv[1].last_access)[0]
			self._drop_locked(oldest_key)

	def _drop_locked(self, transfer_id: str) -> None:
		t = self._transfers.pop(transfer_id, None)
		if t is None:
			return
		if t._task is not None and not t._task.done():
			t._task.cancel()
		try:
			t.file_path.unlink(missing_ok=True)
		except Exception:
			pass

	async def start_request(
		self,
		*,
		method: str,
		url: str,
		headers: Dict[str, str],
		content: Optional[bytes],
		timeout_seconds: float,
		follow_redirects: bool,
	) -> Transfer:
		async with self._lock:
			self._evict_if_needed_locked()
			transfer_id = uuid.uuid4().hex
			file_path = self._config.cache_dir / f"{transfer_id}.bin"
			transfer = Transfer(
				transfer_id=transfer_id,
				file_path=file_path,
				created_at=time.time(),
				last_access=time.time(),
				status=0,
				headers={},
				final_url=url,
				content_type=None,
				total_bytes=None,
			)
			self._transfers[transfer_id] = transfer

		transfer._task = asyncio.create_task(
			self._download_to_file(
				transfer=transfer,
				method=method,
				url=url,
				headers=headers,
				content=content,
				timeout_seconds=timeout_seconds,
				follow_redirects=follow_redirects,
			)
		)
		return transfer

	async def get(self, transfer_id: str) -> Optional[Transfer]:
		async with self._lock:
			t = self._transfers.get(transfer_id)
			if t is None:
				return None
			t.touch()
			self._evict_if_needed_locked()
			return t

	async def _download_to_file(
		self,
		*,
		transfer: Transfer,
		method: str,
		url: str,
		headers: Dict[str, str],
		content: Optional[bytes],
		timeout_seconds: float,
		follow_redirects: bool,
	) -> None:
		try:
			timeout = httpx.Timeout(float(timeout_seconds)) if timeout_seconds and timeout_seconds > 0 else None
			async with httpx.AsyncClient(timeout=timeout, follow_redirects=follow_redirects) as client:
				async with client.stream(method=method, url=url, headers=headers, content=content) as response:
					transfer.status = response.status_code
					transfer.final_url = str(response.url)
					transfer.headers = {k: v for k, v in response.headers.items()}
					transfer.content_type = response.headers.get("content-type")
					transfer.total_bytes = int(response.headers["content-length"]) if "content-length" in response.headers else None

					written = 0
					transfer.file_path.parent.mkdir(parents=True, exist_ok=True)
					with transfer.file_path.open("wb") as f:
						async for chunk in response.aiter_bytes():
							if not chunk:
								continue
							if written >= self._config.max_single_transfer_bytes:
								transfer.truncated = True
								break
							remaining = self._config.max_single_transfer_bytes - written
							if len(chunk) > remaining:
								f.write(chunk[:remaining])
								written += remaining
								transfer.truncated = True
								break
							f.write(chunk)
							f.flush()
							written += len(chunk)
							transfer.available_bytes = written
							async with transfer._condition:
								transfer._condition.notify_all()

				transfer.available_bytes = written
				transfer.done = True
				async with transfer._condition:
					transfer._condition.notify_all()
		except asyncio.CancelledError:
			raise
		except Exception as e:
			transfer.error = {"type": type(e).__name__, "message": str(e)}
			transfer.done = True
			async with transfer._condition:
				transfer._condition.notify_all()


def encode_chunk_for_json(data: bytes, content_type: Optional[str]) -> Dict[str, Any]:
	if not data:
		return {"chunk_base64": "", "chunk_text": None}
	text_like = False
	if content_type:
		ct = content_type.lower()
		if ct.startswith("text/") or "json" in ct or "xml" in ct or "javascript" in ct:
			text_like = True
	if text_like:
		try:
			return {"chunk_base64": base64.b64encode(data).decode("ascii"), "chunk_text": data.decode("utf-8")}
		except Exception:
			pass
	return {"chunk_base64": base64.b64encode(data).decode("ascii"), "chunk_text": None}
