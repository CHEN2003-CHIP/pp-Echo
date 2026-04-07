from __future__ import annotations

from pp_agent.mcp.config import MCPServerConfig
from pp_agent.mcp.descriptors import MCPPromptDescriptor, MCPResourceDescriptor, MCPToolDescriptor
from pp_agent.mcp.session import MCPSession


def discover_mcp_tools(server: MCPServerConfig, session: MCPSession) -> list[MCPToolDescriptor]:
    """Discovers available MCP tools from a session and returns a list of descriptors."""
    descriptors: list[MCPToolDescriptor] = []
    for item in session.list_tools():
        is_destructive = bool(item.get("is_destructive", False))
        descriptors.append(
            MCPToolDescriptor(
                server_name=server.name,
                name=item["name"],
                description=item.get("description", ""),
                is_remote=server.is_remote,
                requires_auth=server.requires_auth,
                is_destructive=is_destructive,
                approval_mode=item.get("approval_mode", server.approval_mode),
                risk_level="high" if server.is_remote and is_destructive else "medium" if is_destructive else "low",
                input_schema=item.get("input_schema", {}),
                metadata={"title": item.get("title", item["name"])},
            )
        )
    return descriptors


def discover_mcp_resources(server: MCPServerConfig, session: MCPSession) -> list[MCPResourceDescriptor]:
    descriptors: list[MCPResourceDescriptor] = []
    for item in session.list_resources():
        descriptors.append(
            MCPResourceDescriptor(
                server_name=server.name,
                uri=item["uri"],
                name=item.get("name", item["uri"]),
                description=item.get("description", ""),
                mime_type=item.get("mime_type"),
                is_remote=server.is_remote,
                requires_auth=server.requires_auth,
                is_destructive=False,
                approval_mode=item.get("approval_mode", server.approval_mode),
                risk_level="low",
                metadata={"title": item.get("title", item.get("name", item["uri"]))},
            )
        )
    return descriptors


def discover_mcp_prompts(server: MCPServerConfig, session: MCPSession) -> list[MCPPromptDescriptor]:
    descriptors: list[MCPPromptDescriptor] = []
    for item in session.list_prompts():
        descriptors.append(
            MCPPromptDescriptor(
                server_name=server.name,
                name=item["name"],
                description=item.get("description", ""),
                is_remote=server.is_remote,
                requires_auth=server.requires_auth,
                is_destructive=False,
                approval_mode=item.get("approval_mode", server.approval_mode),
                risk_level="low",
                arguments_schema=item.get("arguments_schema", {}),
                metadata={"title": item.get("title", item["name"])},
            )
        )
    return descriptors
