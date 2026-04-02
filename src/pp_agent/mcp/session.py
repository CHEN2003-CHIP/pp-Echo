from __future__ import annotations

import json
import os
import subprocess
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


class _StdioJsonMCPClient:
    def __init__(self, config: MCPServerConfig) -> None:
        if not config.command:
            raise ValueError(f"MCP stdio server {config.name!r} requires a command")
        env = os.environ.copy()
        env.update(config.env)
        self._process = subprocess.Popen(
            [config.command, *config.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=config.cwd or None,
            env=env,
            bufsize=1,
        )
        self._request_id = 0

    def initialize(self) -> None:
        self._request("initialize", {})

    def list_tools(self) -> list[dict[str, Any]]:
        payload = self._request("list_tools", {})
        return list(payload.get("tools", []))

    def list_resources(self) -> list[dict[str, Any]]:
        payload = self._request("list_resources", {})
        return list(payload.get("resources", []))

    def list_prompts(self) -> list[dict[str, Any]]:
        payload = self._request("list_prompts", {})
        return list(payload.get("prompts", []))

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._request("call_tool", {"name": name, "arguments": arguments})

    def read_resource(self, uri: str) -> dict[str, Any]:
        return self._request("read_resource", {"uri": uri})

    def get_prompt(self, name: str, arguments: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._request("get_prompt", {"name": name, "arguments": arguments or {}})

    def close(self) -> None:
        try:
            self._request("close", {})
        except Exception:
            pass
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError("MCP stdio pipes are unavailable")
        self._request_id += 1
        payload = {"id": self._request_id, "method": method, "params": params}
        self._process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._process.stdin.flush()
        line = self._process.stdout.readline()
        if not line:
            stderr = ""
            if self._process.stderr is not None:
                try:
                    stderr = self._process.stderr.read().strip()
                except Exception:
                    stderr = ""
            raise RuntimeError(f"MCP server exited before replying to {method!r}. {stderr}".strip())
        response = json.loads(line)
        if "error" in response:
            raise RuntimeError(str(response["error"]))
        result = response.get("result", {})
        if not isinstance(result, dict):
            raise RuntimeError(f"MCP response for {method!r} must be an object")
        return result


def _default_transport_factory(config: MCPServerConfig) -> MCPClientProtocol:
    if config.transport == "stdio":
        return _StdioJsonMCPClient(config)
    raise NotImplementedError(f"Unsupported MCP transport {config.transport!r} for server {config.name!r}.")


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
        self._transport_factory = transport_factory or _default_transport_factory
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

    def close_all_sessions(self) -> list[str]:
        closed: list[str] = []
        for name, session in list(self._sessions.items()):
            session.client.close()
            del self._sessions[name]
            closed.append(name)
        return closed

    def active_session_names(self) -> list[str]:
        return list(self._sessions)
