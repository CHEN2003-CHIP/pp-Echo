from __future__ import annotations

import json
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CapabilityKind = Literal[
    "builtin_tool",
    "mcp_tool",
    "mcp_resource",
    "mcp_prompt",
    "skill",
    "subagent",
    "connector",
    "runtime_adapter",
    "extension",
]
CapabilitySourceKind = Literal["builtin", "mcp", "skill_package", "subagent", "connector", "runtime", "extension", "unknown"]
CapabilityRiskLevel = Literal["safe", "read", "write", "network", "shell", "destructive"]
CapabilityStatus = Literal["discovered", "enabled", "disabled", "error", "deprecated", "loaded"]
CapabilityCostHint = Literal["low", "medium", "high", "unknown"]
CapabilityLatencyHint = Literal["fast", "normal", "slow", "unknown"]
CapabilityDiscoverability = Literal["listed", "hidden", "internal", "disabled"]

_SENSITIVE_METADATA_KEYS = {"api_key", "secret", "token", "password"}


class CapabilityDescriptor(BaseModel):
    """
    Runtime-safe v2 descriptor for any externally exposed capability.

    CapabilityDescriptor is intentionally execution-neutral: it describes what
    a capability is for catalog, policy, router, UI, and trace consumers while
    the owning runtime component still performs execution.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = ""
    kind: CapabilityKind
    name: str
    display_name: Optional[str] = None
    description: str
    source: str
    source_kind: CapabilitySourceKind = "unknown"
    input_schema: Optional[dict[str, Any]] = None
    output_schema: Optional[dict[str, Any]] = None
    risk_level: CapabilityRiskLevel = "safe"
    permissions_required: list[str] = Field(default_factory=list)
    effects: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    version: Optional[str] = None
    status: CapabilityStatus = "discovered"
    cost_hint: CapabilityCostHint = "unknown"
    latency_hint: CapabilityLatencyHint = "unknown"
    discoverability: CapabilityDiscoverability = "listed"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _ensure_metadata_is_serializable(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            json.dumps(value)
        except TypeError as exc:
            raise TypeError("Capability metadata must be JSON-serializable.") from exc
        _reject_sensitive_metadata(value)
        return value

    @model_validator(mode="after")
    def _fill_v2_defaults(self) -> "CapabilityDescriptor":
        """Populate stable v2 defaults for callers that omit derived fields."""
        if not self.id:
            self.id = self.name
        if self.display_name is None:
            self.display_name = self.name
        if self.source_kind == "unknown":
            self.source_kind = _source_kind_for(self.kind, self.source)
        if not self.permissions_required:
            self.permissions_required = _permissions_for_risk(self.risk_level)
        if not self.tags:
            self.tags = [self.kind]
        return self


def _reject_sensitive_metadata(value: Any, *, path: str = "metadata") -> None:
    """Reject metadata keys that could leak credentials into catalog or trace output."""
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(secret_key in lowered for secret_key in _SENSITIVE_METADATA_KEYS):
                raise ValueError(f"Capability metadata cannot contain sensitive key: {path}.{key}")
            _reject_sensitive_metadata(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_sensitive_metadata(item, path=f"{path}[{index}]")


def _source_kind_for(kind: str, source: str) -> CapabilitySourceKind:
    if kind == "builtin_tool" or source.startswith("builtin:"):
        return "builtin"
    if kind.startswith("mcp_") or "mcp_adapter" in source:
        return "mcp"
    if kind == "skill":
        return "skill_package"
    if kind == "subagent":
        return "subagent"
    if kind == "connector":
        return "connector"
    if kind == "runtime_adapter":
        return "runtime"
    if kind == "extension":
        return "extension"
    return "unknown"


def _permissions_for_risk(risk_level: str) -> list[str]:
    if risk_level == "safe":
        return []
    if risk_level == "read":
        return ["read"]
    if risk_level == "write":
        return ["write"]
    if risk_level == "network":
        return ["network"]
    if risk_level == "shell":
        return ["shell"]
    if risk_level == "destructive":
        return ["destructive"]
    return []
