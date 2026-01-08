# mcp-fetch

A minimal MCP (Model Context Protocol) stdio server that exposes a single tool: `http_request`.

It supports:
- Any HTTP method (GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS/...)
- Headers, query params, and multiple body types (json/form/text/base64 bytes)
- Large responses via chunking with a `transfer_id` cursor
- In-process caching backed by on-disk files so agents can request more chunks later

## Run (uvx)

From this directory:

```bash
uvx --refresh --from . mcp-fetch
```

This is an MCP stdio server: it typically does not print anything until an MCP client connects and sends requests.
If you run it directly in a terminal, it should stay running and wait for stdin from an MCP host.

For interactive/manual testing, it will auto-run an HTTP server when stdin is a TTY:
- Open: `http://127.0.0.1:8000/mcp`
- Override: `MCP_FETCH_TRANSPORT=stdio|http`, `MCP_FETCH_PORT=8000`
- Or flags: `mcp-fetch --transport http --port 8000`

## Client config note

If you use `uvx`, you must include the provided command name at the end. This works:

```text
cmd: uvx.exe
args: ["--from", "E:\\Private\\Mcp\\fetch", "mcp-fetch", "--transport", "stdio"]
```

## Tool: `http_request`

Typical flow:
1) Call with `url` (gets chunk 0 and `transfer_id`)
2) If you need more, call again with `transfer_id` and `offset=next_offset`

Notes:
- This server **allows private/internal network access by default** (your requested behavior).
- Only `http://` and `https://` URLs are allowed.
- Use `headers` for request headers.

## Tests

Run unit tests:

```bash
python -m unittest discover -s tests -v
```

There is an integration-style test that attempts a real request to `https://github.com/`. If outbound network access is unavailable, it will be skipped.

## Configuration (env)

- `MCP_FETCH_CACHE_DIR` (default: `./.mcp-fetch-cache`)
- `MCP_FETCH_TTL_SECONDS` (default: `1800`)
- `MCP_FETCH_MAX_CACHE_BYTES_TOTAL` (default: `536870912`) (512 MiB)
- `MCP_FETCH_MAX_SINGLE_TRANSFER_BYTES` (default: `209715200`) (200 MiB)
- `MCP_FETCH_WAIT_CHUNK_TIMEOUT_SECONDS` (default: `30`)
