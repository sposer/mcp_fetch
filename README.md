# mcp-fetch

A minimal MCP (Model Context Protocol) server that exposes a single tool: `fetch_page`.

It supports:
- Browser automation via Playwright (dynamic content, scrolling, waiting for selectors)
- Basic anti-bot shaping (User-Agent, mouse movement, randomized request delays, proxy rotation)
- Large responses via chunking with a `transfer_id` cursor
- On-disk chunk cache so agents can request more chunks later

## Run (uvx)

From this directory:

```bash
uvx --no-cache --refresh --from . mcp-fetch
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

## Tool: `fetch_page`

Typical flow:
1) Call with `url` (gets chunk 0 and `transfer_id`)
2) If you need more, call again with `transfer_id` and `offset=next_offset`

Notes:
- This server **allows private/internal network access by default** (your requested behavior).
- Only `http://` and `https://` URLs are allowed.
- Use `headers` for request headers.
- Set `to_markdown=false` to return raw HTML instead of Markdown.

## Tests

Run unit tests:

```bash
python -m unittest discover -s tests -v
```

There is a Playwright integration test (dynamic DOM). It is disabled by default:
- Run with: `MCP_FETCH_RUN_PLAYWRIGHT_TESTS=1 python -m unittest discover -s tests -v`

## Configuration (env)

- `MCP_FETCH_CACHE_DIR` (default: `./.mcp-fetch-cache`)
- `MCP_FETCH_TTL_SECONDS` (default: `1800`)
- `MCP_FETCH_MAX_CACHE_BYTES_TOTAL` (default: `536870912`) (512 MiB)
- `MCP_FETCH_MAX_SINGLE_TRANSFER_BYTES` (default: `209715200`) (200 MiB)
- `MCP_FETCH_WAIT_CHUNK_TIMEOUT_SECONDS` (default: `30`)
- `MCP_FETCH_EXPOSE_SHUTDOWN` (default: unset) Set to `1` to expose the `shutdown` tool.
