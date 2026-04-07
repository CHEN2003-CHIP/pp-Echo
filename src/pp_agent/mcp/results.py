from __future__ import annotations

import json
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


MCPResultKind = Literal["mcp_tool", "mcp_resource", "mcp_prompt"]


class MCPResult(BaseModel):
    """Unified MCP execution/read result model."""
    # Note: content is optional because some MCP interactions may only return structured payloads without a main text content.
    server_name: str
    kind: MCPResultKind
    name_or_uri: str
    content: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    is_error: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("payload", "metadata")
    @classmethod
    def _validate_jsonable(cls, value: dict[str, Any]) -> dict[str, Any]:
        json.dumps(value)
        return value
