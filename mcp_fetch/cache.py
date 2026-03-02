from __future__ import annotations

import asyncio
import base64
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from .base.env import env_int, env_path


@dataclass
class CacheConfig:
    cache_dir: Path = field(default_factory=lambda: env_path("MCP_FETCH_CACHE_DIR", "./.fetch/cache"))
    ttl_seconds: int = field(default_factory=lambda: env_int("MCP_FETCH_TTL_SECONDS", 1800))
    max_cache_bytes_total: int = field(
        default_factory=lambda: env_int("MCP_FETCH_MAX_CACHE_BYTES_TOTAL", 512 * 1024 * 1024))
    max_single_transfer_bytes: int = field(
        default_factory=lambda: env_int("MCP_FETCH_MAX_SINGLE_TRANSFER_BYTES", 200 * 1024 * 1024))
    wait_chunk_timeout_seconds: int = field(
        default_factory=lambda: env_int("MCP_FETCH_WAIT_CHUNK_TIMEOUT_SECONDS", 30))


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

    def touch(self) -> None:
        self.last_access = time.time()

    async def read_chunk(self, offset: int, size: int, *, wait_timeout_seconds: int) -> tuple[bytes, int, bool]:
        if offset < 0:
            offset = 0
        if size <= 0:
            size = 1
        _ = wait_timeout_seconds
        if offset >= self.available_bytes:
            return b"", offset, True

        read_len = min(size, self.available_bytes - offset)
        with self.file_path.open("rb") as f:
            f.seek(offset)
            data = f.read(read_len)

        next_offset = offset + len(data)
        return data, next_offset, next_offset >= self.available_bytes


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
        try:
            t.file_path.unlink(missing_ok=True)
        except Exception:
            pass

    async def create_transfer(
            self,
            *,
            final_url: str,
            status: int,
            headers: Dict[str, str],
            content_type: Optional[str],
            content: bytes,
            error: Optional[Dict[str, Any]] = None,
    ) -> Transfer:
        content_bytes = content or b""
        total_bytes = len(content_bytes)
        truncated = False
        limit = int(self._config.max_single_transfer_bytes)
        if limit > 0 and total_bytes > limit:
            content_bytes = content_bytes[:limit]
            truncated = True

        async with self._lock:
            self._evict_if_needed_locked()
            transfer_id = uuid.uuid4().hex
            file_path = self._config.cache_dir / f"{transfer_id}.bin"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with file_path.open("wb") as f:
                f.write(content_bytes)
                f.flush()

            transfer = Transfer(
                transfer_id=transfer_id,
                file_path=file_path,
                created_at=time.time(),
                last_access=time.time(),
                status=int(status or 0),
                headers={str(k): str(v) for k, v in (headers or {}).items()},
                final_url=str(final_url),
                content_type=str(content_type) if content_type else None,
                total_bytes=total_bytes,
                truncated=bool(truncated),
                error=error,
                available_bytes=len(content_bytes),
                done=True,
            )
            self._transfers[transfer_id] = transfer
            self._evict_if_needed_locked()
            return transfer

    async def get(self, transfer_id: str) -> Transfer | None:
        async with self._lock:
            t = self._transfers.get(transfer_id)
            if t is None:
                return None
            t.touch()
            self._evict_if_needed_locked()
            return t


def encode_chunk_for_json(data: bytes, content_type: Optional[str]) -> Dict[str, Any]:
    text_like = False
    if content_type:
        ct = content_type.lower()
        if ct.startswith("text/") or "json" in ct or "xml" in ct or "javascript" in ct:
            text_like = True
    if not data:
        if text_like:
            return {"chunk": {"type": "text", "content": ""}}
        return {"chunk": {"type": "base64", "content": ""}}
    if text_like:
        try:
            return {"chunk": {"type": "text", "content": data.decode("utf-8")}}
        except UnicodeDecodeError:
            return {"chunk": {"type": "text", "content": data.decode("utf-8", errors="replace")}}
        except Exception:
            return {"chunk": {"type": "text", "content": data.decode("utf-8", errors="replace")}}
    return {"chunk": {"type": "base64", "content": base64.b64encode(data).decode("ascii")}}
