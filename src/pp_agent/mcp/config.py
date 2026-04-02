from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class MCPServerConfig(BaseModel):
    """Minimal static MCP server configuration."""

    name: str
    transport: str = "stdio"
    command: Optional[str] = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: Optional[str] = None
    is_remote: bool = False
    requires_auth: bool = False
    approval_mode: str = "default"
    idle_timeout_seconds: int = 300


def load_mcp_server_configs(project_dir: Path) -> list[MCPServerConfig]:
    """Load static MCP server configs from `.pp-agent/mcp.json` when present."""

    config_path = project_dir / "mcp.json"
    if not config_path.exists():
        return []

    data: Any = json.loads(config_path.read_text(encoding="utf-8"))
    raw_servers = data["servers"] if isinstance(data, dict) else data
    return [MCPServerConfig(**item) for item in raw_servers]
