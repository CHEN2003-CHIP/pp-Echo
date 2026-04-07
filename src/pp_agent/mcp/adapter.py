from __future__ import annotations

from typing import Any

from pp_agent.mcp.manager import MCPManager
from pp_agent.mcp.results import MCPResult


class MCPToolAdapter:
    """Wrap an MCP tool as an explicit executable object without using ToolRegistry."""

    def __init__(self, manager: MCPManager, server_name: str, tool_name: str) -> None:
        self.manager = manager
        self.server_name = server_name
        self.tool_name = tool_name

    def execute(self, arguments: dict[str, Any]) -> MCPResult:
        """Execute the MCP tool with the given arguments and return the result."""
        return self.manager.call_mcp_tool(self.server_name, self.tool_name, arguments)
