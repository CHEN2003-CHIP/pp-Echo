from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, model_validator


_SUPPORTED_RISK_OVERRIDES = {
    "requests_network",
    "touches_external",
    "destructive_hint",
    "protected_path_hint",
    "touches_workspace",
}


class ToolMetadata(BaseModel):
    name: str
    category: str
    requires_confirmation: bool = False
    permission_domain: str = "read"
    sensitive: bool = False
    model_callable: bool = True
    tool_family: Optional[str] = None
    risk_overrides: dict[str, bool] = Field(default_factory=dict)
    exact_effect_mode: str = "auto"
    non_side_effectful: bool = False
    known_safe_inspect: bool = False
    requests_network_hint: bool = False
    touches_external_hint: bool = False

    @model_validator(mode="after")
    def _validate_dynamic_declarations(self) -> "ToolMetadata":
        if self.exact_effect_mode not in {"none", "auto", "required"}:
            raise ValueError("exact_effect_mode must be one of: none, auto, required")
        if self.known_safe_inspect and not self.non_side_effectful:
            raise ValueError("known_safe_inspect requires non_side_effectful=True")
        if self.known_safe_inspect and self.requests_network_hint:
            raise ValueError("known_safe_inspect cannot be combined with requests_network_hint=True")
        if self.known_safe_inspect and self.touches_external_hint:
            raise ValueError("known_safe_inspect cannot be combined with touches_external_hint=True")
        unsupported = sorted(key for key in self.risk_overrides if key not in _SUPPORTED_RISK_OVERRIDES)
        if unsupported:
            allowed = ", ".join(sorted(_SUPPORTED_RISK_OVERRIDES))
            raise ValueError(f"risk_overrides['{unsupported[0]}'] is not supported. Allowed keys: {allowed}")
        false_overrides = sorted(key for key, value in self.risk_overrides.items() if value is not True)
        if false_overrides:
            raise ValueError(f"risk_overrides['{false_overrides[0]}'] only accepts True")
        return self

    @property
    def supports_exact_effect_staging(self) -> bool:
        return self.exact_effect_mode in {"auto", "required"}

    @property
    def has_explicit_dynamic_declarations(self) -> bool:
        return self.exact_effect_mode == "required" or any(
            (
                self.non_side_effectful,
                self.known_safe_inspect,
                self.requests_network_hint,
                self.touches_external_hint,
            )
        )

    @property
    def declaration_strength(self) -> str:
        if self.has_explicit_dynamic_declarations:
            return "declared"
        return "weak"
