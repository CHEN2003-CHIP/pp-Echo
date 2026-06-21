from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

CostLevel = Literal["unknown", "low", "medium", "high"]

_SECRET_KEY_PARTS = ("api_key", "apikey", "secret", "token", "password")


class ModelCapabilities(BaseModel):
    tool_calling: bool = False
    json_mode: bool = False
    streaming: bool = False
    vision: bool = False
    long_context: bool = False
    reasoning_mode: bool = False
    structured_output: bool = False


class ModelLimits(BaseModel):
    context_window: Optional[int] = None
    max_output_tokens: Optional[int] = None


class ModelQualityHints(BaseModel):
    good_for: list[str] = Field(default_factory=list)
    avoid_for: list[str] = Field(default_factory=list)


class ModelRuntimeHints(BaseModel):
    preferred_runtime: Optional[str] = None
    compatible_runtimes: list[str] = Field(default_factory=lambda: ["pp_echo_native"])


class ModelCostHints(BaseModel):
    input_cost_per_million: Optional[float] = None
    output_cost_per_million: Optional[float] = None
    cost_level: CostLevel = "unknown"


class ModelCapabilityProfile(BaseModel):
    """
    ModelCapabilityProfile is the single internal shape for model capability checks.

    Provider configuration still owns authentication and endpoint details; this profile
    only describes the selected model's behavioral surface, limits, rough quality hints,
    runtime compatibility, and non-secret metadata.
    """

    provider_id: str = "unknown"
    model_id: str = "unknown"
    display_name: Optional[str] = None
    family: Optional[str] = None
    capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)
    limits: ModelLimits = Field(default_factory=ModelLimits)
    quality_hints: ModelQualityHints = Field(default_factory=ModelQualityHints)
    runtime_hints: ModelRuntimeHints = Field(default_factory=ModelRuntimeHints)
    cost_hints: ModelCostHints = Field(default_factory=ModelCostHints)
    metadata: dict[str, Any] = Field(default_factory=lambda: {"source": "inferred"})

    @model_validator(mode="after")
    def _reject_secret_metadata(self) -> "ModelCapabilityProfile":
        """
        Profiles are safe to write into traces and docs, so metadata must never carry
        credential-like fields. ProviderConfig remains the only place that names secret
        environment variables.
        """
        secret_path = _first_secret_path(self.metadata)
        if secret_path is not None:
            raise ValueError(f"ModelCapabilityProfile metadata cannot contain secret-like key: {secret_path}")
        return self

    def capability_summary(self) -> dict[str, bool]:
        """Return the compact capability subset used by run metadata and trace events."""
        return {
            "tool_calling": self.capabilities.tool_calling,
            "json_mode": self.capabilities.json_mode,
            "streaming": self.capabilities.streaming,
            "vision": self.capabilities.vision,
            "long_context": self.capabilities.long_context,
            "reasoning_mode": self.capabilities.reasoning_mode,
            "structured_output": self.capabilities.structured_output,
        }


def _first_secret_path(value: Any, prefix: str = "metadata") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            path = f"{prefix}.{key}"
            if any(part in key_text for part in _SECRET_KEY_PARTS):
                return path
            nested = _first_secret_path(child, path)
            if nested is not None:
                return nested
    if isinstance(value, list):
        for index, child in enumerate(value):
            nested = _first_secret_path(child, f"{prefix}[{index}]")
            if nested is not None:
                return nested
    return None
