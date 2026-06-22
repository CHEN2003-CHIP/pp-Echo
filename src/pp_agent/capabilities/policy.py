from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

from pp_agent.capabilities.binding import CapabilityApprovalPolicy, CapabilityBinding
from pp_agent.capabilities.descriptor import CapabilityDescriptor


class CapabilityRouteContext(BaseModel):
    """
    Policy context used while selecting or exposing capabilities.

    The fields intentionally mirror runtime scopes instead of UI state, so the
    same policy decision can be reused by TraceInspect, Bot Center, CLI, and the
    AgentRuntime selection event.
    """

    bot_id: Optional[str] = None
    workspace_id: Optional[str] = None
    connector_id: Optional[str] = None
    session_id: Optional[str] = None
    trust_level: str = "default"


class CapabilityPolicy:
    """
    Small deterministic policy engine for descriptor plus binding checks.

    CapabilityPolicy centralizes risk and binding decisions for v0.2.1 so old
    scattered risk checks can be retired in the v0.3.0 cleanup.
    """

    def is_enabled(
        self,
        descriptor: CapabilityDescriptor,
        bindings: list[CapabilityBinding],
        context: CapabilityRouteContext,
    ) -> bool:
        """Return whether a descriptor is selectable in the supplied scope."""
        return self.block_reason(descriptor, bindings, context) is None

    def approval_policy_for(
        self,
        descriptor: CapabilityDescriptor,
        bindings: list[CapabilityBinding],
        context: CapabilityRouteContext,
    ) -> CapabilityApprovalPolicy:
        """Resolve the effective approval policy from binding first, then descriptor risk."""
        binding = self._most_specific_binding(descriptor.id, bindings, context)
        if binding is not None:
            return binding.approval_policy
        return "never" if descriptor.risk_level in {"safe", "read"} else "on_risk"

    def is_allowed_for_trust_level(
        self,
        descriptor: CapabilityDescriptor,
        bindings: list[CapabilityBinding],
        trust_level: str,
    ) -> bool:
        """Check trust-level allow/deny lists without requiring a full route context."""
        context = CapabilityRouteContext(trust_level=trust_level)
        binding = self._most_specific_binding(descriptor.id, bindings, context)
        if binding is None:
            return True
        return self._trust_allowed(binding, trust_level)

    def block_reason(
        self,
        descriptor: CapabilityDescriptor,
        bindings: list[CapabilityBinding],
        context: CapabilityRouteContext,
    ) -> Optional[str]:
        """Return the first deterministic reason a descriptor cannot be selected."""
        if descriptor.status not in {"discovered", "enabled", "loaded"}:
            return "status_not_enabled"
        if descriptor.discoverability == "disabled":
            return "discoverability_disabled"
        binding = self._most_specific_binding(descriptor.id, bindings, context)
        if binding is None:
            return None
        if not binding.enabled:
            return binding.reason or "disabled_by_binding"
        if binding.approval_policy == "deny":
            return binding.reason or "denied_by_binding"
        if not self._trust_allowed(binding, context.trust_level):
            return binding.reason or "denied_by_trust_level"
        return None

    def _most_specific_binding(
        self,
        capability_id: str,
        bindings: list[CapabilityBinding],
        context: CapabilityRouteContext,
    ) -> Optional[CapabilityBinding]:
        """Select the nearest binding in session, bot, connector, workspace, global order."""
        matches = [binding for binding in bindings if binding.capability_id == capability_id]
        if not matches:
            return None
        scope_ids = {
            "session": context.session_id,
            "bot": context.bot_id,
            "connector": context.connector_id,
            "workspace": context.workspace_id,
            "global": None,
        }
        for scope_type in ("session", "bot", "connector", "workspace", "global"):
            expected_id = scope_ids[scope_type]
            for binding in matches:
                if binding.scope_type != scope_type:
                    continue
                if scope_type == "global" or binding.scope_id == expected_id:
                    return binding
        return None

    @staticmethod
    def _trust_allowed(binding: CapabilityBinding, trust_level: str) -> bool:
        """Apply denied trust levels before allowed trust-level narrowing."""
        if trust_level in binding.denied_trust_levels:
            return False
        if binding.allowed_trust_levels and trust_level not in binding.allowed_trust_levels:
            return False
        return True
