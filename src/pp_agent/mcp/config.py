from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class MCPTransportSettings(BaseModel):
    tool_prefix: str = "mcp"
    idle_timeout: int = 300
    lifecycle: str = "lazy"
    direct_tools: bool = False


class MCPServerConfig(BaseModel):
    """Minimal static MCP server configuration."""

    name: str
    description: str = ""
    intent_tags: list[str] = Field(default_factory=list)
    auto_match_examples: list[str] = Field(default_factory=list)
    transport: Optional[str] = None
    protocol: str = "auto"
    command: Optional[str] = None
    args: list[str] = Field(default_factory=list)
    url: Optional[str] = None
    headers: dict[str, str] = Field(default_factory=dict)
    bearer_token: Optional[str] = None
    bearer_token_env: Optional[str] = None
    env: dict[str, str] = Field(default_factory=dict)
    cwd: Optional[str] = None
    is_remote: bool = False
    requires_auth: bool = False
    approval_mode: str = "default"
    idle_timeout_seconds: int = 300
    timeout_seconds: int = 30

    def resolved_transport(self) -> str:
        value = (self.transport or "").strip().lower()
        if value and value != "auto":
            return value
        if self.url:
            return "http"
        return "stdio"

    def resolved_protocol(self) -> str:
        value = (self.protocol or "auto").strip().lower()
        if value not in {"auto", "compat", "standard"}:
            raise ValueError(f"Unsupported MCP protocol {self.protocol!r} for server {self.name!r}.")
        return value

    def resolved_headers(self) -> dict[str, str]:
        headers = dict(self.headers)
        token = self.bearer_token
        if token is None and self.bearer_token_env:
            token = os.getenv(self.bearer_token_env)
        if token:
            headers.setdefault("Authorization", f"Bearer {token}")
        return headers


class MCPConfigDocument(BaseModel):
    settings: MCPTransportSettings = Field(default_factory=MCPTransportSettings)
    servers: list[MCPServerConfig] = Field(default_factory=list)


def load_mcp_config(project_dir: Path, config_paths: Optional[list[Path]] = None) -> MCPConfigDocument:
    """Load MCP adapter settings and server configs from one or more config files."""

    document = MCPConfigDocument()
    paths = config_paths or [project_dir / "mcp.json"]
    for path in paths:
        if not path.exists():
            continue
        loaded = _parse_mcp_document(path)
        if loaded.settings != MCPTransportSettings():
            document.settings = loaded.settings
        document.servers.extend(loaded.servers)
    return document


def load_mcp_server_configs(project_dir: Path, config_paths: Optional[list[Path]] = None) -> list[MCPServerConfig]:
    return load_mcp_config(project_dir, config_paths=config_paths).servers


def _parse_mcp_document(path: Path) -> MCPConfigDocument:
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return MCPConfigDocument(servers=[MCPServerConfig(**item) for item in data])

    if not isinstance(data, dict):
        raise ValueError(f"MCP config must be a list or object: {path}")

    settings = MCPTransportSettings(**data.get("settings", {}))
    if "mcpServers" in data and isinstance(data["mcpServers"], dict):
        raw_servers = []
        for name, value in data["mcpServers"].items():
            item = dict(value)
            item.setdefault("name", name)
            raw_servers.append(item)
    else:
        raw_servers = data.get("servers", [])
    servers = [_apply_mcp_defaults(MCPServerConfig(**item), settings) for item in raw_servers]
    return MCPConfigDocument(settings=settings, servers=servers)


def _apply_mcp_defaults(server: MCPServerConfig, settings: MCPTransportSettings) -> MCPServerConfig:
    if "idle_timeout_seconds" not in server.model_fields_set:
        server.idle_timeout_seconds = settings.idle_timeout
    if "is_remote" not in server.model_fields_set and server.url:
        server.is_remote = True
    if server.url and not server.description:
        server.description = f"Remote MCP server at {server.url}"
    return server
