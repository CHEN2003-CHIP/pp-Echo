from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field


class UserAgendaStep(BaseModel):
    kind: Literal["message", "approve_pending", "reject_pending"]
    text: str = ""
    tool: str = ""

    model_config = {"extra": "forbid"}


class SuccessCriteria(BaseModel):
    verification_commands: list[str] = Field(default_factory=list)
    expected_files_changed: list[str] = Field(default_factory=list)
    forbidden_files_changed: list[str] = Field(default_factory=list)
    final_files_contains: dict[str, list[str]] = Field(default_factory=dict)
    final_files_not_contains: dict[str, list[str]] = Field(default_factory=dict)
    required_communication: list[str] = Field(default_factory=list)
    protected_path_block_required: bool = False
    memory_recall_required: bool = False
    checkpoint_rewind_restored: bool = False
    rewind_files: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class ActionConstraints(BaseModel):
    required_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    required_approvals: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class EvalTask(BaseModel):
    id: str
    name: str
    category: str
    workspace_fixture: str
    max_turns: int = 4
    user_agenda: list[UserAgendaStep]
    success_criteria: SuccessCriteria = Field(default_factory=SuccessCriteria)
    action_constraints: ActionConstraints = Field(default_factory=ActionConstraints)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class CommandResult(BaseModel):
    command: str
    returncode: int
    stdout: str = ""
    stderr: str = ""


class AgentTrace(BaseModel):
    task_id: str
    mode: str
    turns: int = 0
    session_id: str = ""
    assistant_messages: list[str] = Field(default_factory=list)
    tool_calls: list[str] = Field(default_factory=list)
    approvals: list[str] = Field(default_factory=list)
    rejected_approvals: list[str] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[bool] = Field(default_factory=list)
    pending_actions: list[str] = Field(default_factory=list)
    checkpoint_rewind_restored: bool = False
    infra_failed: bool = False
    failure_kind: str = ""
    duration_seconds: float = 0.0


class CaseScore(BaseModel):
    task_id: str
    category: str
    passed: bool
    pending: bool = False
    infra_failed: bool = False
    failure_reasons: list[str] = Field(default_factory=list)
    safety_violations: list[str] = Field(default_factory=list)
    state_reward: float = 0.0
    communication_reward: float = 0.0
    action_reward: float = 0.0
    approval_recall: float = 1.0
    tool_call_count: int = 0
    tool_success_rate: float = 1.0
    turn_count: int = 0
    duration_seconds: float = 0.0
    verification_results: list[CommandResult] = Field(default_factory=list)
    trace_events: list[dict[str, Any]] = Field(default_factory=list)


class EvalReport(BaseModel):
    commit_hash: str
    date: str
    provider: str
    model: str
    mode: str
    suite: str
    total_cases: int
    passed: int
    failed: int
    pending: int
    infra_failed: int
    task_success_rate: float
    state_reward: float
    communication_reward: float
    action_reward: float
    safety_violations: int
    safety_rate: float
    approval_recall: float
    tool_success_rate: float
    average_tool_calls: float
    average_turns: float
    average_duration: float
    category_summary: dict[str, dict[str, Union[float, int]]]
    chart_path: str = ""
    cases: list[dict[str, Any]]


class RunConfig(BaseModel):
    suite: str = "pp_echo_core"
    mode: Literal["deterministic", "live"] = "deterministic"
    model: Optional[str] = None
    case_count: Optional[int] = None
    seed: int = 0
    timeout_seconds: int = 120
    output_dir: Optional[str] = None
    save_history: bool = False
