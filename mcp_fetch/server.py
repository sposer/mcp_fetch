from __future__ import annotations

import asyncio
import atexit
import logging
import sys
import time
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

import httpx
from fastmcp import FastMCP

from .base.env import env_bool, env_int, env_str
from .base.logging import configure_logging
from .cache import CacheConfig, TransferCache, encode_chunk_for_json
from .cleaner import clean_html
from .converter import html_to_markdown
from .crawler import close_default_crawler, get_default_crawler


def _only_http_https(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http/https URLs are supported")
    if not parsed.netloc:
        raise ValueError("URL missing host")


def _merge_query(url: str, query: dict[str, Any] | None) -> str:
    if not query:
        return url
    parsed = urlparse(url)
    existing = parsed.query
    added = urlencode({k: str(v) for k, v in query.items() if v is not None}, doseq=True)
    combined = existing
    if combined and added:
        combined = combined + "&" + added
    elif added:
        combined = added
    return urlunparse(parsed._replace(query=combined))


_config = CacheConfig()
_cache = TransferCache(_config)

configure_logging()
_log = logging.getLogger("mcp_fetch.server")

mcp = FastMCP("mcp-fetch")

_http_client: httpx.AsyncClient | None = None


async def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
            verify=False,
            trust_env=True,
        )
    return _http_client


async def _close_http_client() -> None:
    global _http_client
    if _http_client:
        await _http_client.aclose()
        _http_client = None


async def _read_chunk_impl(
        transfer_id: str, offset: int, chunk_bytes: int, to_markdown: bool = False
) -> dict[str, Any]:
    transfer = await _cache.get(transfer_id)
    if transfer is None:
        return {"ok": False, "error": {"type": "not_found", "message": "Unknown transfer_id"}}

    data, next_offset, done = await transfer.read_chunk(
        offset=int(offset or 0), size=chunk_bytes, wait_timeout_seconds=_config.wait_chunk_timeout_seconds
    )
    payload: dict[str, Any] = {
        "ok": transfer.error is None,
        "transfer_id": transfer.transfer_id,
        "offset": int(offset or 0),
        "next_offset": next_offset if data else None,
        "done": bool(done and next_offset >= transfer.available_bytes),
        "available_bytes": transfer.available_bytes,
        "total_bytes": transfer.total_bytes,
        "status": transfer.status,
        "headers": transfer.headers,
        "final_url": transfer.final_url,
        "content_type": transfer.content_type,
        "truncated": transfer.truncated,
        "error": transfer.error,
        "to_markdown": bool(to_markdown),
    }
    payload.update(encode_chunk_for_json(data, transfer.content_type))
    return payload


async def _fetch_page_impl(
        url: str | None = None,
        headers: dict[str, str] | None = None,
        query: dict[str, Any] | None = None,
        timeout_ms: float = 30000,
        to_markdown: bool = True,
        wait_selector: str | None = None,
        max_scrolls: int = 8,
        min_delay_ms: int = 150,
        max_delay_ms: int = 450,
        proxy: str | None = None,
        proxy_pool: list[str] | None = None,
        user_agent: str | None = None,
        chunk_bytes: int = 262144,
        transfer_id: str | None = None,
        offset: int = 0,
) -> dict[str, Any]:
    chunk_bytes = int(chunk_bytes or 262144)
    if chunk_bytes <= 0:
        chunk_bytes = 1

    if transfer_id:
        return await _read_chunk_impl(transfer_id, offset, chunk_bytes, to_markdown)

    if not url:
        raise ValueError("`url` is required")

    url = _merge_query(url, query)
    _only_http_https(url)

    headers_obj = headers or {}
    if not isinstance(headers_obj, dict):
        raise ValueError("`headers` must be an object")
    request_headers = {str(k): str(v) for k, v in headers_obj.items() if v is not None}

    if timeout_ms <= 0:
        timeout_ms = 30000

    start_time = time.time()
    crawler = await get_default_crawler()
    result = await crawler.fetch_html(
        url=url,
        headers=request_headers,
        timeout_ms=timeout_ms,
        wait_selector=wait_selector,
        max_scrolls=max_scrolls,
        min_delay_ms=min_delay_ms,
        max_delay_ms=max_delay_ms,
        proxy=proxy,
        proxy_pool=proxy_pool,
        user_agent=user_agent,
    )
    elapsed_ms = int((time.time() - start_time) * 1000)

    if not result.ok:
        raise RuntimeError(
            f"{result.error.get('type') if result.error else 'Error'}: {result.error.get('message') if result.error else 'unknown'}"
        )

    html = result.html
    content: str
    content_type: str
    if bool(to_markdown):
        cleaned_html = clean_html(html)
        content = html_to_markdown(cleaned_html)
        content_type = "text/markdown; charset=utf-8"
    else:
        content = html
        content_type = "text/html; charset=utf-8"

    transfer = await _cache.create_transfer(
        final_url=result.final_url,
        status=result.status,
        headers=result.headers,
        content_type=content_type,
        content=content.encode("utf-8"),
    )
    data, next_offset, done = await transfer.read_chunk(offset=0, size=chunk_bytes, wait_timeout_seconds=0)

    payload = {
        "ok": True,
        "transfer_id": transfer.transfer_id,
        "offset": 0,
        "next_offset": next_offset if data else None,
        "done": bool(done and next_offset >= transfer.available_bytes),
        "available_bytes": transfer.available_bytes,
        "total_bytes": transfer.total_bytes,
        "status": transfer.status,
        "headers": transfer.headers,
        "final_url": transfer.final_url,
        "content_type": transfer.content_type,
        "truncated": transfer.truncated,
        "elapsed_ms": elapsed_ms,
        "error": None,
        "to_markdown": bool(to_markdown),
    }
    payload.update(encode_chunk_for_json(data, transfer.content_type))
    _log.info("fetch_page ok", extra={"url": url, "elapsed_ms": elapsed_ms, "status": transfer.status})
    return payload


@mcp.tool
async def fetch_page(
        url: str | None = None,
        headers: dict[str, str] | None = None,
        query: dict[str, Any] | None = None,
        timeout_ms: float = 30000,
        to_markdown: bool = True,
        wait_selector: str | None = None,
        max_scrolls: int = 8,
        min_delay_ms: int = 150,
        max_delay_ms: int = 450,
        proxy: str | None = None,
        proxy_pool: list[str] | None = None,
        user_agent: str | None = None,
        chunk_bytes: int = 48000,
        transfer_id: str | None = None,
        offset: int = 0,
) -> dict[str, Any]:
    """Fetch/Crawl a dynamic web page and convert to Markdown (supports JavaScript).

    Use this tool to:
    1. Crawl/Scrape content from modern web pages (React, Vue, etc.)
    2. Get full page content after JavaScript rendering
    3. Download large page content via chunked streaming
    
    Protocol:
    1. Start: Provide url (required) → returns transfer_id + first chunk
    2. Continue: Provide transfer_id + offset → returns next chunk

    Args:
      - url: Target http(s) URL (required for phase 1)
      - to_markdown: Convert HTML to Markdown (default: True)
      - wait_selector: CSS selector to wait for before capturing content
      - Optional: headers, query, timeout_ms, max_scrolls,
                  min/max_delay_ms, proxy/pool, user_agent, chunk_bytes
      - Cursor: transfer_id, offset (for phase 2)

    Returns:
      - Chunk: chunk{type, content}, next_offset, done, truncated
      - Meta: transfer_id, status, headers, final_url, content_type, elapsed_ms
      - Size: available_bytes, total_bytes
    """
    return await _fetch_page_impl(
        url=url,
        headers=headers,
        query=query,
        timeout_ms=timeout_ms,
        to_markdown=to_markdown,
        wait_selector=wait_selector,
        max_scrolls=max_scrolls,
        min_delay_ms=min_delay_ms,
        max_delay_ms=max_delay_ms,
        proxy=proxy,
        proxy_pool=proxy_pool,
        user_agent=user_agent,
        chunk_bytes=chunk_bytes,
        transfer_id=transfer_id,
        offset=offset,
    )


async def _http_request_impl(
        url: str | None = None,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        query: dict[str, Any] | None = None,
        body: str | None = None,
        json_body: dict[str, Any] | None = None,
        timeout_ms: float = 30000,
        to_markdown: bool = True,
        chunk_bytes: int = 262144,
        transfer_id: str | None = None,
        offset: int = 0,
) -> dict[str, Any]:
    chunk_bytes = int(chunk_bytes or 262144)
    if chunk_bytes <= 0:
        chunk_bytes = 1

    if transfer_id:
        return await _read_chunk_impl(transfer_id, offset, chunk_bytes, to_markdown=to_markdown)

    if not url:
        raise ValueError("`url` is required")

    url = _merge_query(url, query)
    _only_http_https(url)

    if timeout_ms <= 0:
        timeout_ms = 30000

    client = await _get_http_client()
    request_headers = {str(k): str(v) for k, v in (headers or {}).items() if v is not None}

    max_retries = 3
    last_error = None
    start_time = time.time()

    for attempt in range(max_retries):
        try:
            response = await client.request(
                method=method,
                url=url,
                headers=request_headers,
                content=body,
                json=json_body,
                timeout=timeout_ms / 1000.0,
            )
            # Read full content for caching
            content = response.read()
            elapsed_ms = int((time.time() - start_time) * 1000)

            content_type = response.headers.get("content-type", "application/octet-stream")
            if to_markdown and "text/html" in content_type.lower():
                try:
                    # httpx response.text automatically handles encoding detection
                    cleaned_html = clean_html(response.text)
                    content = html_to_markdown(cleaned_html).encode("utf-8")
                    content_type = "text/markdown; charset=utf-8"
                except Exception:
                    # Fallback to original content if conversion fails
                    pass

            transfer = await _cache.create_transfer(
                final_url=str(response.url),
                status=response.status_code,
                headers=dict(response.headers),
                content_type=content_type,
                content=content,
            )

            data, next_offset, done = await transfer.read_chunk(offset=0, size=chunk_bytes, wait_timeout_seconds=0)

            payload = {
                "ok": True,
                "transfer_id": transfer.transfer_id,
                "offset": 0,
                "next_offset": next_offset if data else None,
                "done": bool(done and next_offset >= transfer.available_bytes),
                "available_bytes": transfer.available_bytes,
                "total_bytes": transfer.total_bytes,
                "status": transfer.status,
                "headers": transfer.headers,
                "final_url": transfer.final_url,
                "content_type": transfer.content_type,
                "truncated": transfer.truncated,
                "elapsed_ms": elapsed_ms,
                "error": None,
                "to_markdown": bool(to_markdown),
            }
            payload.update(encode_chunk_for_json(data, transfer.content_type))
            _log.info("http_request ok", extra={"url": url, "elapsed_ms": elapsed_ms, "status": transfer.status})
            return payload

        except (httpx.TransportError, httpx.TimeoutException) as e:
            last_error = e
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5 * (attempt + 1))
            continue
        except Exception as e:
            raise RuntimeError(f"HTTP request failed: {str(e)}")

    raise RuntimeError(f"HTTP request failed after {max_retries} retries: {str(last_error)}")


@mcp.tool
async def http_request(
        url: str | None = None,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        query: dict[str, Any] | None = None,
        body: str | None = None,
        json_body: dict[str, Any] | None = None,
        timeout_ms: float = 30000,
        to_markdown: bool = True,
        chunk_bytes: int = 262144,
        transfer_id: str | None = None,
        offset: int = 0,
) -> dict[str, Any]:
    """Perform a generic HTTP request (GET, POST, PUT, DELETE, etc) for APIs or raw data.

    Use this tool when:
    1. You need to call a REST API (JSON/XML)
    2. You need to use HTTP methods other than GET (POST, PUT, DELETE)
    3. You want to download a raw file without rendering (PDF, Image, etc)

    Note: For GET requests to renderable web pages, prefer `fetch_page` which handles dynamic content and JavaScript.

    Protocol:
    1. Start: Provide url (required) → returns transfer_id + first chunk
    2. Continue: Provide transfer_id + offset → returns next chunk
    """
    return await _http_request_impl(
        url=url,
        method=method,
        headers=headers,
        query=query,
        body=body,
        json_body=json_body,
        timeout_ms=timeout_ms,
        to_markdown=to_markdown,
        chunk_bytes=chunk_bytes,
        transfer_id=transfer_id,
        offset=offset,
    )


async def shutdown() -> dict[str, Any]:
    """Release browser resources early when embedding this server in a long-lived process."""
    await close_default_crawler()
    await _close_http_client()
    return {"ok": True}


if env_bool("MCP_FETCH_EXPOSE_SHUTDOWN", False):
    shutdown = mcp.tool(shutdown)


async def _cleanup_all() -> None:
    await close_default_crawler()
    await _close_http_client()


def _close_resources_sync() -> None:
    try:
        asyncio.run(_cleanup_all())
    except RuntimeError:
        try:
            loop = asyncio.get_running_loop()
        except Exception:
            return
        try:
            loop.create_task(_cleanup_all())
        except Exception:
            return


def main() -> None:
    logging.getLogger("fastmcp").setLevel(logging.WARNING)
    logging.getLogger("fastmcp").propagate = False

    atexit.register(_close_resources_sync)

    try:
        # Always run in stdio mode
        mcp.run()
    except BaseException as e:
        # When started without an MCP host, stdin may close immediately; FastMCP/anyio can surface this as CancelledError.
        if type(e).__name__ == "CancelledError":
            return
        raise
    finally:
        _close_resources_sync()
