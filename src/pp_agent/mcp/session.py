from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

from pp_agent.mcp.config import MCPServerConfig


class MCPClientProtocol(Protocol):
    def initialize(self) -> None:
        ...

    def list_tools(self) -> list[dict[str, Any]]:
        ...

    def list_resources(self) -> list[dict[str, Any]]:
        ...

    def list_prompts(self) -> list[dict[str, Any]]:
        ...

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        ...

    def read_resource(self, uri: str) -> dict[str, Any]:
        ...

    def get_prompt(self, name: str, arguments: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        ...

    def close(self) -> None:
        ...


TransportFactory = Callable[[MCPServerConfig], MCPClientProtocol]
TimeFn = Callable[[], float]


def _unsupported_transport_factory(config: MCPServerConfig) -> MCPClientProtocol:
    raise NotImplementedError(f"No MCP transport factory configured for server {config.name!r}.")


@dataclass
class MCPSession:
    server: MCPServerConfig
    client: MCPClientProtocol
    last_used_at: float
    discovery_cache: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def touch(self, now: float) -> None:
        self.last_used_at = now

    def list_tools(self) -> list[dict[str, Any]]:
        return self._cached_list("tools", self.client.list_tools)

    def list_resources(self) -> list[dict[str, Any]]:
        return self._cached_list("resources", self.client.list_resources)

    def list_prompts(self) -> list[dict[str, Any]]:
        return self._cached_list("prompts", self.client.list_prompts)

    def _cached_list(self, cache_key: str, loader: Callable[[], list[dict[str, Any]]]) -> list[dict[str, Any]]:
        if cache_key not in self.discovery_cache:
            self.discovery_cache[cache_key] = loader()
        return [dict(item) for item in self.discovery_cache[cache_key]]


class MCPSessionManager:
    """Lazily creates and reuses MCP sessions per server."""

    def __init__(self, transport_factory: TransportFactory | None = None, time_fn: TimeFn | None = None) -> None:
        self._transport_factory = transport_factory or _unsupported_transport_factory
        self._time_fn = time_fn or time.time
        self._sessions: dict[str, MCPSession] = {}

    def get_or_create(self, server: MCPServerConfig) -> MCPSession:
        session = self._sessions.get(server.name)
        if session is not None:
            session.touch(self._time_fn())
            return session

        client = self._transport_factory(server)
        client.initialize()
        session = MCPSession(server=server, client=client, last_used_at=self._time_fn())
        self._sessions[server.name] = session
        return session

    def close_idle_sessions(self) -> list[str]:
        now = self._time_fn()
        closed: list[str] = []
        for name, session in list(self._sessions.items()):
            idle_seconds = now - session.last_used_at
            if idle_seconds < session.server.idle_timeout_seconds:
                continue
            session.client.close()
            del self._sessions[name]
            closed.append(name)
        return closed

    def active_session_names(self) -> list[str]:
        return list(self._sessions)
