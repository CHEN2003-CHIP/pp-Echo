from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from pp_agent.capabilities.descriptor import _reject_sensitive_metadata


CapabilityScopeType = Literal["global", "workspace", "bot", "connector", "session"]
CapabilityApprovalPolicy = Literal["never", "on_risk", "always", "deny"]


class CapabilityBinding(BaseModel):
    """
    Scope-specific governance rule for one capability.

    Descriptor answers what a capability is; binding answers whether a
    workspace, bot, connector, or session may use it.
    """

    id: str
    capability_id: str
    scope_type: CapabilityScopeType = "global"
    scope_id: Optional[str] = None
    enabled: bool = True
    approval_policy: CapabilityApprovalPolicy = "on_risk"
    max_calls_per_run: Optional[int] = None
    timeout_seconds: Optional[int] = None
    allowed_trust_levels: list[str] = Field(default_factory=list)
    denied_trust_levels: list[str] = Field(default_factory=list)
    allowed_contexts: list[str] = Field(default_factory=list)
    denied_contexts: list[str] = Field(default_factory=list)
    reason: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Keep binding metadata safe for catalog APIs and trace payloads."""
        _reject_sensitive_metadata(value)
        return value
