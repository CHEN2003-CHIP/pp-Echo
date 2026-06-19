from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from pp_agent.domain import ChatMessage, ToolCall
from pp_agent.tools.base import ToolExecutionResult

SESSION_START = "session_start"
SESSION_RESTORE = "session_restore"
SESSION_BEFORE_SWITCH = "session_before_switch"
SESSION_SWITCHED = "session_switched"
SESSION_BEFORE_FORK = "session_before_fork"
SESSION_FORKED = "session_forked"
SESSION_BEFORE_TREE = "session_before_tree"
SESSION_TREE_VIEWED = "session_tree_viewed"
SESSION_TREE_NAVIGATED = "session_tree_navigated"
SESSION_BEFORE_COMPACT = "session_before_compact"
SESSION_COMPACTED = "session_compacted"
SESSION_REWOUND = "session_rewound"
SESSION_SHUTDOWN = "session_shutdown"
CHECKPOINT_BEFORE_CREATE = "checkpoint_before_create"
CHECKPOINT_CREATED = "checkpoint_created"
CHECKPOINT_RESTORE_PREVIEW = "checkpoint_restore_preview"
CHECKPOINT_BEFORE_RESTORE = "checkpoint_before_restore"
CHECKPOINT_RESTORED = "checkpoint_restored"
CHECKPOINT_RESTORE_FAILED = "checkpoint_restore_failed"
SESSION_SAFE_REWIND_STARTED = "session_safe_rewind_started"
SESSION_SAFE_REWIND_COMPLETED = "session_safe_rewind_completed"

AGENT_START = "agent_start"
TURN_START = "turn_start"
TURN_PHASE_CHANGED = "turn_phase_changed"
TURN_END = "turn_end"
AGENT_END = "agent_end"

CONTEXT_BUILT = "context_built"
BEFORE_PROVIDER_REQUEST = "before_provider_request"
PROVIDER_RESPONSE = "provider_response"
PROVIDER_ERROR = "provider_error"
REASONING_START = "reasoning_start"
REASONING_DELTA = "reasoning_delta"
REASONING_SUMMARY = "reasoning_summary"
REASONING_END = "reasoning_end"

PLANNER_START = "planner_start"
PLANNER_STEP = "planner_step"
PLANNER_GATE_PENDING = "planner_gate_pending"
PLANNER_GATE_APPROVED = "planner_gate_approved"
PLANNER_GATE_REJECTED = "planner_gate_rejected"
PLANNER_END = "planner_end"

TOOL_CALL = "tool_call"
TOOL_START = "tool_start"
TOOL_RESULT = "tool_result"
TOOL_ERROR = "tool_error"
TOOL_END = "tool_end"
SUBAGENT_START = "subagent_start"
SUBAGENT_PROGRESS = "subagent_progress"
SUBAGENT_END = "subagent_end"
SUBAGENT_FAIL = "subagent_fail"
LEARNING_CANDIDATES_CREATED = "learning_candidates_created"
LEARNING_EXTRACTION_FAILED = "learning_extraction_failed"
LEARNING_ITEM_APPLIED = "learning_item_applied"

QUEUE_ENQUEUED = "queue_enqueued"
QUEUE_DEQUEUED = "queue_dequeued"
QUEUE_CLEARED = "queue_cleared"
QUEUE_UPDATE = "queue_update"

MESSAGE_DELTA = "message_delta"
ERROR = "error"
COMPACTION = "compaction"
TURN_STATE = "turn_state"


class LifecycleDecision(BaseModel):
    details: dict[str, object] = Field(default_factory=dict)


class ContextBuildDecision(LifecycleDecision):
    messages: Optional[list[ChatMessage]] = None


class ProviderRequestDecision(LifecycleDecision):
    messages: Optional[list[ChatMessage]] = None
    tools: Optional[list[dict[str, Any]]] = None


class ProviderResponseDecision(LifecycleDecision):
    assistant_text: Optional[str] = None
    tool_calls: Optional[list[ToolCall]] = None


class ToolCallDecision(LifecycleDecision):
    action: str = "allow"
    message: Optional[str] = None


class ToolResultDecision(LifecycleDecision):
    continue_loop: bool = True
    result: Optional[ToolExecutionResult] = None


class ToolErrorDecision(LifecycleDecision):
    continue_loop: bool = False


class SessionCompactDecision(LifecycleDecision):
    allow: bool = True
