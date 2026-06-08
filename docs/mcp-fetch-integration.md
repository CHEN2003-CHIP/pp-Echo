# fetch-mcp 社区 MCP 集成说明

pp-Echo 已验证可以接入社区 MCP server [`zcaceres/fetch-mcp`](https://github.com/zcaceres/fetch-mcp)。该 server 提供 `fetch_html`、`fetch_markdown`、`fetch_txt`、`fetch_json`、`fetch_readable`、`fetch_youtube_transcript` 等网页获取工具。

## 为什么需要这项验证

pp-Echo 的 MCP runtime 原本支持：

- legacy line-delimited compat MCP
- 标准 HTTP JSON-RPC MCP
- 标准 stdio MCP，使用 `Content-Length` framing

实际接入 `fetch-mcp` 时暴露了两个常见兼容性问题：

- 一些 JavaScript MCP server 使用 stdio newline-delimited JSON，而不是 `Content-Length` framing。
- 一些社区 MCP server 只提供 tools，对 `resources/list` 和 `prompts/list` 返回 `Method not found`。

因此 runtime 已调整为：

- stdio 优先尝试 line-delimited JSON，再回退到 framed stdio。
- 对 `resources/list` 和 `prompts/list` 的 `-32601 Method not found` 做容忍处理，将其视为空能力集合。

## 本地验证配置

示例配置如下：

```json
{
  "servers": [
    {
      "name": "fetch",
      "description": "Community MCP server for fetching web pages.",
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

安装命令：

```powershell
npm install mcp-fetch-server --prefix .mcp-tools\fetch-mcp
```

## 已验证行为

已验证通过：

- `python -m pp_agent.cli.main capabilities list --include-mcp`
- `python -m pp_agent.cli.main capabilities show mcp_tool fetch.fetch_markdown --include-mcp`
- `fetch.fetch_markdown` 访问 `http://example.com`
- `fetch.fetch_json` 访问 `https://httpbin.org/json`

曾经失败的目标：

- `https://www.example.com` 返回 `fetch failed`

该失败来自目标抓取本身，不是 MCP discovery 或 tool execution 失败。
