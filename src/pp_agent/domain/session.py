from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


TurnPhase = Literal["idle", "planning", "awaiting_approval", "executing", "draining_queue"]


class CompactionState(BaseModel):
    """State of message compaction for a conversation."""
    summary: str = ""
    summarized_message_count: int = 0


class QueuedMessage(BaseModel):
    """A message that is queued for delivery to the assistant, along with its delivery method and metadata."""
    id: str
    delivery: Literal["steering", "follow_up"] = "follow_up"
    text: str
    created_at: float


class PlanStep(BaseModel):
    """A step in a plan, representing a task or action to be taken by the assistant."""
    title: str
    tool_name: Optional[str] = None
    tool_args: dict[str, Any] = Field(default_factory=dict)
    status: Literal["pending", "awaiting_approval", "in_progress", "completed", "failed"] = "pending"


class RuntimeStatusSnapshot(BaseModel):
    """A snapshot of the runtime status of the assistant."""
    turn_id: int = 0
    phase: TurnPhase = "idle"
    queue_count: int = 0
    pending_plan: bool = False
    pending_tool_count: int = 0
    reason: str = ""
    planner_active: bool = False
    queue_action: Optional[str] = None
    queue_delivery: Optional[str] = None
