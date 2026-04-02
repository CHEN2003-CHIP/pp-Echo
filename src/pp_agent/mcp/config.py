from __future__ import annotations

import json
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
    transport: str = "stdio"
    command: Optional[str] = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: Optional[str] = None
    is_remote: bool = False
    requires_auth: bool = False
    approval_mode: str = "default"
    idle_timeout_seconds: int = 300


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
    return server
