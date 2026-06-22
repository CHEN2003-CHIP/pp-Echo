from __future__ import annotations

from typing import Any

from pp_agent.capabilities.policy import CapabilityRouteContext
from pp_agent.capabilities.router import CapabilitySelection


def build_capability_selected_event_payload(
    selection: CapabilitySelection,
    context: CapabilityRouteContext,
    *,
    max_capabilities: int,
) -> dict[str, Any]:
    """Build a trace-safe payload for capability selection lifecycle events."""
    return {
        "type": "capability_selected",
        "selected": [
            {"id": item.id, "kind": item.kind, "risk_level": item.risk_level}
            for item in selection.selected
        ],
        "blocked": [
            {"id": item.capability_id, "reason": item.reason, "policy": item.policy}
            for item in selection.blocked
        ],
        "policy_context": {
            "bot_id": context.bot_id,
            "connector_id": context.connector_id,
            "trust_level": context.trust_level,
            "workspace_id": context.workspace_id,
            "session_id": context.session_id,
            "max_capabilities": max_capabilities,
        },
    }
