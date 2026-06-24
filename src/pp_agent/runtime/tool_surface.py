from __future__ import annotations

import importlib
from typing import Any


def active_tool_surface(agent: Any) -> dict[str, Any]:
    """
    Return the session tool listing from CapabilityCatalog descriptors.

    This keeps the Web/API tool surface on the governance model while
    ToolRegistry remains the execution source of truth.
    """
    registry = getattr(agent, "tool_registry", None)
    if registry is None:
        return {"config_version": getattr(agent, "config_version", None), "tools": []}
    capability_catalog = importlib.import_module("pp_agent.capabilities.catalog")
    capability_discovery = importlib.import_module("pp_agent.capabilities.discovery")
    catalog = capability_catalog.CapabilityCatalog([capability_discovery.BuiltinToolCapabilityDiscoveryProvider(registry)])
    tools = []
    for descriptor in sorted(catalog.list(kind="builtin_tool"), key=lambda item: item.name):
        metadata = descriptor.metadata
        tools.append(
            {
                "id": descriptor.id,
                "name": descriptor.name,
                "kind": descriptor.kind,
                "category": metadata.get("category"),
                "tool_family": metadata.get("tool_family"),
                "permission_domain": (descriptor.permissions_required or [None])[0],
                "requires_confirmation": metadata.get("requires_confirmation"),
                "model_callable": metadata.get("model_callable"),
                "risk_level": descriptor.risk_level,
                "effects": list(descriptor.effects),
                "description": descriptor.description,
            }
        )
    return {
        "config_version": getattr(agent, "config_version", None),
        "config_hash": getattr(getattr(agent, "config_snapshot", None), "config_hash", None),
        "tool_count": len(tools),
        "tools": tools,
    }
