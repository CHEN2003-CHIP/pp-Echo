from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from pp_agent.capabilities.binding import CapabilityBinding
from pp_agent.capabilities.catalog import CapabilityCatalog
from pp_agent.capabilities.descriptor import CapabilityDescriptor
from pp_agent.capabilities.policy import CapabilityPolicy, CapabilityRouteContext


class BlockedCapability(BaseModel):
    """Trace-safe summary for a capability filtered out by policy."""

    capability_id: str
    reason: str
    policy: Optional[str] = None


class CapabilitySelection(BaseModel):
    """Router output split into selected descriptors and blocked summaries."""

    selected: list[CapabilityDescriptor] = Field(default_factory=list)
    blocked: list[BlockedCapability] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CapabilityRouter:
    """
    Deterministic keyword router for the governance layer.

    The router ranks descriptors for observability and future allowlisting; it
    does not replace execution-time tool filtering owned by AgentRuntime.
    """

    def __init__(self, policy: Optional[CapabilityPolicy] = None) -> None:
        """Create a router with the provided policy engine or the default policy."""
        self.policy = policy or CapabilityPolicy()

    def select(
        self,
        task_text: str,
        catalog: CapabilityCatalog,
        bindings: list[CapabilityBinding],
        context: CapabilityRouteContext,
        max_capabilities: int = 16,
    ) -> CapabilitySelection:
        """Select the highest-scoring unblocked capabilities for a task preview."""
        selected: list[CapabilityDescriptor] = []
        blocked: list[BlockedCapability] = []
        candidates: list[tuple[int, int, CapabilityDescriptor]] = []
        keywords = _keywords(task_text)

        for descriptor in catalog.list():
            reason = self.policy.block_reason(descriptor, bindings, context)
            if reason is not None:
                blocked.append(
                    BlockedCapability(
                        capability_id=descriptor.id,
                        reason=reason,
                        policy=self.policy.approval_policy_for(descriptor, bindings, context),
                    )
                )
                continue
            candidates.append((_match_score(descriptor, keywords), _risk_rank(descriptor.risk_level), descriptor))

        for _score, _risk, descriptor in sorted(candidates, key=lambda item: (-item[0], item[1], item[2].name)):
            if len(selected) >= max_capabilities:
                break
            selected.append(descriptor)

        return CapabilitySelection(selected=selected, blocked=blocked)


def _keywords(task_text: str) -> set[str]:
    return {part.lower() for part in task_text.replace("_", " ").replace(".", " ").split() if part.strip()}


def _match_score(descriptor: CapabilityDescriptor, keywords: set[str]) -> int:
    haystack = " ".join([descriptor.name, descriptor.description, " ".join(descriptor.tags)]).lower()
    return sum(1 for keyword in keywords if keyword in haystack)


def _risk_rank(risk_level: str) -> int:
    order = {"safe": 0, "read": 1, "write": 2, "network": 3, "shell": 4, "destructive": 5}
    return order.get(risk_level, 6)
