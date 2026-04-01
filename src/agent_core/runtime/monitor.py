from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from agent_core.runtime.types import AgentEvent, AgentState


class RuntimeStatusSnapshot(BaseModel):
    turn_id: int = 0
    phase: str = "idle"
    queue_count: int = 0
    pending_plan: bool = False
    pending_tool_count: int = 0
    reason: str = ""
    planner_active: bool = False
    queue_action: Optional[str] = None
    queue_delivery: Optional[str] = None


class RuntimeMonitor:
    def snapshot_from_state(self, state: AgentState, **overrides: Any) -> RuntimeStatusSnapshot:
        payload = {
            "turn_id": state.turn.turn_id,
            "phase": state.turn.phase,
            "queue_count": len(state.queued_messages),
            "pending_plan": bool(state.pending_plan_token),
            "pending_tool_count": len(state.pending_tool_calls),
            "reason": state.turn.reason,
            "planner_active": state.turn.phase in {"planning", "awaiting_approval", "executing"},
        }
        payload.update(overrides)
        return RuntimeStatusSnapshot(**payload)

    def attach(self, details: dict[str, Any], state: AgentState, **overrides: Any) -> dict[str, Any]:
        enriched = dict(details)
        enriched["runtime"] = self.snapshot_from_state(state, **overrides).model_dump(mode="json")
        return enriched

    def snapshot_from_event(self, event: AgentEvent) -> Optional[RuntimeStatusSnapshot]:
        runtime = event.details.get("runtime")
        if not runtime:
            return None
        return RuntimeStatusSnapshot.model_validate(runtime)

    @staticmethod
    def format(snapshot: RuntimeStatusSnapshot) -> str:
        pending_plan = "yes" if snapshot.pending_plan else "no"
        suffix = f" reason={snapshot.reason}" if snapshot.reason else ""
        return (
            f"[State] turn={snapshot.turn_id} phase={snapshot.phase} queue={snapshot.queue_count} "
            f"pending_plan={pending_plan} pending_tools={snapshot.pending_tool_count}{suffix}"
        )
