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
    """
    ToolMetadata 用来描述“工具在系统层面的属性”，不是给模型看的工具参数说明。
    
    它主要服务于：
    1. 工具分类：标记工具属于 file、shell、repo、mcp、memory、subagent 等类别。
    2. 模型可见性：通过 model_callable 控制该工具是否暴露给 LLM 调用。
    3. 权限控制：记录 permission_domain，配合 ToolPolicyEvaluator 判断 read/write/bash/dynamic 等权限。
    4. 风险判断：标记工具是否 sensitive、是否需要确认、是否可能访问网络或外部系统。
    5. 能力过滤：配合 capability profile 控制子 Agent 或受限 Runtime 能使用哪些工具。
    6. 前端展示：为 capabilities、runtime report、工具面板提供工具来源、类别、风险等信息。
    7. 动态工具支持：MCP、extension、browser、memory 等动态注册工具会通过 metadata 告诉系统它们的来源和副作用特征。
    
    简单说：
    ToolSpec 是“给模型看的工具说明”；
    ToolMetadata 是“给 Runtime / Policy / UI / Capability 系统看的工具元信息”。
    """
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
