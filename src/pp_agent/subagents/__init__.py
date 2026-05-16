from __future__ import annotations

from typing import Any


_EXPORTS = {
    "SubAgentCatalog": ("pp_agent.subagents.catalog", "SubAgentCatalog"),
    "SubAgentManager": ("pp_agent.subagents.manager", "SubAgentManager"),
    "SubAgentOrchestrationResult": ("pp_agent.subagents.orchestrator", "SubAgentOrchestrationResult"),
    "SubAgentOrchestrator": ("pp_agent.subagents.orchestrator", "SubAgentOrchestrator"),
    "SubAgentRunResult": ("pp_agent.subagents.specs", "SubAgentRunResult"),
    "SubAgentSpec": ("pp_agent.subagents.specs", "SubAgentSpec"),
    "SubAgentRuntimeAdapter": ("pp_agent.subagents.runtime_adapter", "SubAgentRuntimeAdapter"),
    "SubAgentTurnLimitReached": ("pp_agent.subagents.runtime_adapter", "SubAgentTurnLimitReached"),
    "build_subagent_tool_registry": ("pp_agent.subagents.manager", "build_subagent_tool_registry"),
    "default_subagent_specs": ("pp_agent.subagents.specs", "default_subagent_specs"),
    "parse_subagent_output": ("pp_agent.subagents.specs", "parse_subagent_output"),
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attr_name = _EXPORTS[name]
    from importlib import import_module

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS)
