from __future__ import annotations

import time
import os
import sys
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode, urlparse, urlunparse

from fastmcp import FastMCP

from .cache import CacheConfig, TransferCache, encode_chunk_for_json


def _only_http_https(url: str) -> None:
	parsed = urlparse(url)
	if parsed.scheme not in ("http", "https"):
		raise ValueError("Only http/https URLs are supported")
	if not parsed.netloc:
		raise ValueError("URL missing host")


def _merge_query(url: str, query: Optional[Dict[str, Any]]) -> str:
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


def _parse_body(
	*,
	json_body: Any,
	form: Optional[Dict[str, Any]],
	text: Optional[str],
	bytes_base64: Optional[str],
	content_type: Optional[str],
) -> Tuple[Optional[bytes], Dict[str, str]]:
	headers: Dict[str, str] = {}
	content: Optional[bytes] = None

	if json_body is not None:
		import json as _json

		content = _json.dumps(json_body, ensure_ascii=False).encode("utf-8")
		headers["content-type"] = "application/json; charset=utf-8"
	elif form is not None:
		if not isinstance(form, dict):
			raise ValueError("`form` must be an object")
		content = urlencode({k: str(v) for k, v in form.items()}).encode("utf-8")
		headers["content-type"] = "application/x-www-form-urlencoded; charset=utf-8"
	elif text is not None:
		if not isinstance(text, str):
			raise ValueError("`text` must be a string")
		content = text.encode("utf-8")
		headers["content-type"] = str(content_type or "text/plain; charset=utf-8")
	elif bytes_base64 is not None:
		import base64

		if not isinstance(bytes_base64, str):
			raise ValueError("`bytes_base64` must be a string")
		try:
			content = base64.b64decode(bytes_base64, validate=True)
		except Exception:
			raise ValueError("Invalid base64 for `bytes_base64`")
		if content_type:
			headers["content-type"] = str(content_type)

	return content, headers


_config = CacheConfig()
_cache = TransferCache(_config)

mcp = FastMCP("mcp-fetch")


@mcp.tool
async def http_request(
	method: str = "GET",
	url: Optional[str] = None,
	headers: Optional[Dict[str, str]] = None,
	query: Optional[Dict[str, Any]] = None,
	json: Any = None,
	form: Optional[Dict[str, Any]] = None,
	text: Optional[str] = None,
	bytes_base64: Optional[str] = None,
	content_type: Optional[str] = None,
	timeout_ms: float = 30000,
	follow_redirects: bool = False,
	chunk_bytes: int = 262144,
	transfer_id: Optional[str] = None,
	offset: int = 0,
) -> Dict[str, Any]:
	"""Perform an HTTP request and return the response in chunks using a transfer_id cursor."""

	chunk_bytes = int(chunk_bytes or 262144)
	if chunk_bytes <= 0:
		chunk_bytes = 1

	if transfer_id:
		transfer = await _cache.get(transfer_id)
		if transfer is None:
			return {"ok": False, "error": {"type": "not_found", "message": "Unknown transfer_id"}}

		data, next_offset, done = await transfer.read_chunk(
			offset=int(offset or 0), size=chunk_bytes, wait_timeout_seconds=_config.wait_chunk_timeout_seconds
		)
		payload: Dict[str, Any] = {
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
		}
		payload.update(encode_chunk_for_json(data, transfer.content_type))
		return payload

	if not url:
		raise ValueError("`url` is required")

	url = _merge_query(url, query)
	_only_http_https(url)
	method = str(method or "GET").upper()

	headers_obj = headers or {}
	if not isinstance(headers_obj, dict):
		raise ValueError("`headers` must be an object")
	request_headers = {str(k): str(v) for k, v in headers_obj.items() if v is not None}

	content, inferred_headers = _parse_body(
		json_body=json,
		form=form,
		text=text,
		bytes_base64=bytes_base64,
		content_type=content_type,
	)
	for k, v in inferred_headers.items():
		request_headers.setdefault(k, v)

	if timeout_ms <= 0:
		timeout_ms = 30000
	timeout_seconds = float(timeout_ms) / 1000.0

	start_time = time.time()
	transfer = await _cache.start_request(
		method=method,
		url=url,
		headers=request_headers,
		content=content,
		timeout_seconds=timeout_seconds,
		follow_redirects=bool(follow_redirects),
	)
	data, next_offset, done = await transfer.read_chunk(
		offset=0, size=chunk_bytes, wait_timeout_seconds=_config.wait_chunk_timeout_seconds
	)
	elapsed_ms = int((time.time() - start_time) * 1000)

	# If the request failed before producing any bytes, surface it as a tool error so MCP sets `isError=true`.
	if transfer.error is not None and not data:
		raise RuntimeError(f"{transfer.error.get('type')}: {transfer.error.get('message')}")

	payload = {
		"ok": transfer.error is None,
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
		"error": transfer.error,
	}
	payload.update(encode_chunk_for_json(data, transfer.content_type))
	return payload


def main() -> None:
	import argparse

	parser = argparse.ArgumentParser(add_help=True)
	parser.add_argument("--transport", choices=["stdio", "http"], default=None)
	parser.add_argument("--port", type=int, default=int(os.environ.get("MCP_FETCH_PORT", "8000")))
	parsed, _unknown = parser.parse_known_args()

	transport = parsed.transport or os.environ.get("MCP_FETCH_TRANSPORT")
	if not transport:
		transport = "http" if sys.stdin.isatty() else "stdio"

	if transport == "http":
		mcp.run(transport="http", port=int(parsed.port))
		return

	try:
		mcp.run()
	except BaseException as e:
		# When started without an MCP host, stdin may close immediately; FastMCP/anyio can surface this as CancelledError.
		if type(e).__name__ == "CancelledError":
			return
		raise
