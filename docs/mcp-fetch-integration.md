# Community MCP integration: fetch-mcp

This repo has been validated against the free community MCP server [`zcaceres/fetch-mcp`](https://github.com/zcaceres/fetch-mcp), which exposes webpage fetching tools such as `fetch_html`, `fetch_markdown`, `fetch_txt`, `fetch_json`, `fetch_readable`, and `fetch_youtube_transcript`.

## Why this matters

The MCP runtime in `pp-Echo` originally handled:
- legacy line-delimited compat MCP
- standard HTTP JSON-RPC MCP
- standard stdio MCP with `Content-Length` framing

During real integration testing, `fetch-mcp` exposed two mainstream compatibility gaps:
- many JavaScript MCP servers built on the MCP SDK use newline-delimited JSON over stdio instead of `Content-Length` framing
- many community MCP servers are tool-only and return `Method not found` for `resources/list` and `prompts/list`

The runtime has now been updated to:
- try standard stdio line-delimited JSON first, then fall back to framed stdio
- tolerate `-32601 Method not found` for `resources/list` and `prompts/list` by treating them as empty capability sets

## Local install used for verification

The verified local setup in this workspace uses a repo-local install:

```json
{
  "servers": [
    {
      "name": "fetch",
      "description": "Community standard MCP server for fetching web pages as HTML, text, markdown, JSON, and readable article content.",
      "protocol": "standard",
      "command": "node",
      "args": [
        ".mcp-tools/fetch-mcp/node_modules/mcp-fetch-server/dist/index.js"
      ],
      "env": {
        "DEFAULT_LIMIT": "12000"
      },
      "timeout_seconds": 60,
      "idle_timeout_seconds": 300
    }
  ]
}
```

The package was installed with:

```powershell
npm install mcp-fetch-server --prefix .mcp-tools\fetch-mcp
```

## Verified behavior

The following were verified successfully in this repo:
- `python -m pp_agent.cli.main capabilities list --include-mcp`
- `python -m pp_agent.cli.main capabilities show mcp_tool fetch.fetch_markdown --include-mcp`
- `fetch.fetch_markdown` against `http://example.com`
- `fetch.fetch_json` against `https://httpbin.org/json`

One target failed during live testing:
- `https://www.example.com` returned `fetch failed`

That failure came from the target fetch attempt, not from MCP discovery or tool execution. The MCP integration itself was working at that point.
