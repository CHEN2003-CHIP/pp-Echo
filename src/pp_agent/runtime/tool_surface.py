from __future__ import annotations

from typing import Any


def active_tool_surface(agent: Any) -> dict[str, Any]:
    registry = getattr(agent, "tool_registry", None)
    if registry is None:
        return {"config_version": getattr(agent, "config_version", None), "tools": []}
    metadata = registry.metadata()
    tools = []
    for name, item in sorted(metadata.items()):
        spec = registry.get_spec(name)
        tools.append(
            {
                "name": name,
                "category": item.category,
                "tool_family": item.tool_family,
                "permission_domain": item.permission_domain,
                "requires_confirmation": spec.requires_confirmation,
                "model_callable": spec.model_callable,
                "sensitive": spec.sensitive,
                "description": spec.description,
            }
        )
    return {
        "config_version": getattr(agent, "config_version", None),
        "config_hash": getattr(getattr(agent, "config_snapshot", None), "config_hash", None),
        "tool_count": len(tools),
        "tools": tools,
    }
