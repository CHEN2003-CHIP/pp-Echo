"""
这个例子讲什么：
    MCP mock：外部服务先暴露工具清单，Agent 再按名称调用工具。

对应完整工程：
    src/pp_agent/mcp/*
    example-mcp.jsonc

运行命令：
    python mini-pp-echo/07_mcp_mock.py
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class McpTool:
    name: str
    description: str
    input_schema: dict[str, str]


@dataclass
class McpResult:
    content: str


ToolHandler = Callable[[dict[str, Any]], McpResult]


class FakeMcpServer:
    """模拟一个 MCP server：能列工具，也能执行工具。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self._tools: dict[str, tuple[McpTool, ToolHandler]] = {}

    def register(self, tool: McpTool, handler: ToolHandler) -> None:
        self._tools[tool.name] = (tool, handler)

    def list_tools(self) -> list[McpTool]:
        return [pair[0] for pair in self._tools.values()]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> McpResult:
        if name not in self._tools:
            raise ValueError(f"未知 MCP 工具：{name}")
        return self._tools[name][1](arguments)


class McpAdapter:
    """把 MCP server 的工具转成 Agent 内部可见的 qualified name。"""

    def __init__(self, server: FakeMcpServer) -> None:
        self.server = server

    def discover(self) -> list[McpTool]:
        tools: list[McpTool] = []
        for tool in self.server.list_tools():
            tools.append(
                McpTool(
                    name=f"{self.server.name}.{tool.name}",
                    description=tool.description,
                    input_schema=tool.input_schema,
                )
            )
        return tools

    def call(self, qualified_name: str, arguments: dict[str, Any]) -> McpResult:
        server_name, tool_name = qualified_name.split(".", 1)
        if server_name != self.server.name:
            raise ValueError(f"工具不属于当前 server：{qualified_name}")
        return self.server.call_tool(tool_name, arguments)


class FakeLLM:
    def choose_tool(self, tools: list[McpTool], user_input: str) -> tuple[str, dict[str, Any]]:
        for tool in tools:
            if "天气" in user_input and tool.name.endswith("weather"):
                return tool.name, {"city": "Shanghai"}
            if "仓库" in user_input and tool.name.endswith("repo_summary"):
                return tool.name, {"path": "."}
        return tools[0].name, {}


def create_server() -> FakeMcpServer:
    server = FakeMcpServer("demo")

    server.register(
        McpTool("weather", "查询城市天气 mock", {"city": "string"}),
        lambda args: McpResult(f"{args['city']} 今天适合读 Agent 源码。"),
    )
    server.register(
        McpTool("repo_summary", "总结仓库 mock", {"path": "string"}),
        lambda args: McpResult(f"{args['path']} 看起来像一个本地 Agent 工程。"),
    )
    return server


def main() -> None:
    adapter = McpAdapter(create_server())
    llm = FakeLLM()

    tools = adapter.discover()
    print("--- discovered mcp tools ---")
    for tool in tools:
        print(f"{tool.name}: {tool.description} schema={tool.input_schema}")

    user_input = "请查一下天气，然后提醒我继续读源码"
    tool_name, args = llm.choose_tool(tools, user_input)
    print("\n--- tool call ---")
    print(tool_name, args)

    result = adapter.call(tool_name, args)
    print("\n--- result ---")
    print(result.content)

    print("\n重点：真实工程还会处理 server 生命周期、权限、超时和结果转换。")


if __name__ == "__main__":
    main()
