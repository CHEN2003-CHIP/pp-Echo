from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class _MCPDescriptorBase(BaseModel):
    """Base class for MCP descriptors with common fields and validation."""
    server_name: str
    description: str = ""
    is_remote: bool = False
    requires_auth: bool = False
    is_destructive: bool = False
    approval_mode: str = "default"
    risk_level: str = "low"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        json.dumps(value)
        return value


class MCPToolDescriptor(_MCPDescriptorBase):
    """Descriptor for an MCP tool, which can be called with arguments."""
    name: str
    input_schema: dict[str, Any] = Field(default_factory=dict)


class MCPResourceDescriptor(_MCPDescriptorBase):
    """Descriptor for an MCP resource, which can be accessed via a URI."""
    uri: str
    name: str = ""
    mime_type: Optional[str] = None


class MCPPromptDescriptor(_MCPDescriptorBase):
    """Descriptor for an MCP prompt, which can be used to generate text."""
    name: str
    arguments_schema: dict[str, Any] = Field(default_factory=dict)
