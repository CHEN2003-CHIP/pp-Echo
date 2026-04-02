from __future__ import annotations

import json
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


CapabilityKind = Literal["skill", "builtin_tool", "extension", "mcp_tool", "mcp_resource", "mcp_prompt"]


class CapabilityDescriptor(BaseModel):
    """Serializable metadata describing a discoverable capability."""

    kind: CapabilityKind
    name: str
    description: str
    source: str
    path: Optional[str] = None
    status: str = "discovered"
    origin_type: str = "unknown"
    risk_level: str = "low"
    cost_hint: str = "low"
    discoverability: str = "listed"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _ensure_metadata_is_serializable(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            json.dumps(value)
        except TypeError as exc:
            raise TypeError("Capability metadata must be JSON-serializable.") from exc
        return value
