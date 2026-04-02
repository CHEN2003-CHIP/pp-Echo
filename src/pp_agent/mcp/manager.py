from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pp_agent.mcp.config import MCPServerConfig, load_mcp_server_configs
from pp_agent.mcp.descriptors import MCPPromptDescriptor, MCPResourceDescriptor, MCPToolDescriptor
from pp_agent.mcp.discovery import discover_mcp_prompts, discover_mcp_resources, discover_mcp_tools
from pp_agent.mcp.results import MCPResult
from pp_agent.mcp.session import MCPSession, MCPSessionManager, TimeFn, TransportFactory


class MCPManager:
    """Facade for MCP config loading, lazy sessions, discovery, and execution."""

    def __init__(
        self,
        servers: list[MCPServerConfig],
        *,
        transport_factory: TransportFactory | None = None,
        time_fn: TimeFn | None = None,
    ) -> None:
        self._servers = {server.name: server for server in servers}
        self._session_manager = MCPSessionManager(transport_factory=transport_factory, time_fn=time_fn)

    @classmethod
    def from_workspace(
        cls,
        workspace: Path,
        *,
        transport_factory: TransportFactory | None = None,
        time_fn: TimeFn | None = None,
    ) -> "MCPManager":
        project_dir = workspace.resolve() / ".pp-agent"
        return cls(load_mcp_server_configs(project_dir), transport_factory=transport_factory, time_fn=time_fn)

    def list_mcp_tools(self, server_name: str) -> list[MCPToolDescriptor]:
        server, session = self._server_session(server_name)
        return discover_mcp_tools(server, session)

    def list_mcp_resources(self, server_name: str) -> list[MCPResourceDescriptor]:
        server, session = self._server_session(server_name)
        return discover_mcp_resources(server, session)

    def list_mcp_prompts(self, server_name: str) -> list[MCPPromptDescriptor]:
        server, session = self._server_session(server_name)
        return discover_mcp_prompts(server, session)

    def call_mcp_tool(self, server_name: str, name: str, args: dict[str, Any]) -> MCPResult:
        _server, session = self._server_session(server_name)
        payload = session.client.call_tool(name, args)
        session.touch(session.last_used_at if False else session.last_used_at)
        return MCPResult(
            server_name=server_name,
            kind="mcp_tool",
            name_or_uri=name,
            content=payload.get("content"),
            payload=payload.get("payload", {}),
            is_error=bool(payload.get("is_error", False)),
            metadata={"source_server": server_name},
        )

    def read_mcp_resource(self, server_name: str, uri: str) -> MCPResult:
        _server, session = self._server_session(server_name)
        payload = session.client.read_resource(uri)
        session.touch(session.last_used_at if False else session.last_used_at)
        return MCPResult(
            server_name=server_name,
            kind="mcp_resource",
            name_or_uri=uri,
            content=payload.get("content"),
            payload=payload.get("payload", {}),
            is_error=bool(payload.get("is_error", False)),
            metadata={"source_server": server_name},
        )

    def get_mcp_prompt(self, server_name: str, name: str, args: Optional[dict[str, Any]] = None) -> MCPResult:
        _server, session = self._server_session(server_name)
        payload = session.client.get_prompt(name, args or {})
        session.touch(session.last_used_at if False else session.last_used_at)
        return MCPResult(
            server_name=server_name,
            kind="mcp_prompt",
            name_or_uri=name,
            content=payload.get("content"),
            payload=payload.get("payload", {}),
            is_error=bool(payload.get("is_error", False)),
            metadata={"source_server": server_name},
        )

    def close_idle_sessions(self) -> list[str]:
        return self._session_manager.close_idle_sessions()

    def active_session_names(self) -> list[str]:
        return self._session_manager.active_session_names()

    def server_names(self) -> list[str]:
        return list(self._servers)

    def _server_session(self, server_name: str) -> tuple[MCPServerConfig, MCPSession]:
        server = self._servers[server_name]
        session = self._session_manager.get_or_create(server)
        return server, session
