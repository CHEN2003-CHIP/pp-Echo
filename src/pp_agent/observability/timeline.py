from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pp_agent.coding.enforcement import ScopeEnforcementResult, scope_enforcement_to_details
from pp_agent.coding.impact import ChangeImpact, change_impact_to_dict
from pp_agent.coding.planner import TaskPlan, task_plan_to_dict
from pp_agent.coding.repository import RepositoryAnalysis
from pp_agent.coding.scope import TaskScope, task_scope_to_dict
from pp_agent.coding.testing import ValidationPlan, validation_plan_to_dict
from pp_agent.context.project import ProjectContext, ProjectManifest

TIMELINE_EVENT_TYPES = {
    "project_context",
    "repository_analysis",
    "change_impact",
    "task_scope",
    "validation_plan",
    "scope_enforcement",
    "manifest_loaded",
    "plan",
    "task_scope",
    "tool_call",
    "tool_policy_decision",
    "shell_command",
    "file_read",
    "file_edit",
    "file_create",
    "file_delete",
    "test_run",
    "approval_required",
    "patch_candidate",
    "patch_apply",
    "rollback",
    "summary",
    "error",
}

TIMELINE_STATUSES = {
    "queued",
    "running",
    "succeeded",
    "failed",
    "skipped",
    "waiting_approval",
    "cancelled",
}


@dataclass
class AgentStep:
    """A normalized runtime step that preserves the factual unit of work."""

    id: str
    run_id: str | None
    parent_id: str | None
    type: str
    status: str
    title: str
    summary: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    duration_ms: int | None = None
    details: dict[str, Any] = field(default_factory=dict)
    artifact_ids: list[str] = field(default_factory=list)


@dataclass
class FileOperation:
    """A single workspace file operation derived from structured changes."""

    path: str
    operation: str
    status: str
    lines_added: int | None = None
    lines_deleted: int | None = None
    summary: str | None = None


@dataclass
class DiffLine:
    """A single diff line used inside a diff hunk."""

    type: str
    text: str


@dataclass
class DiffHunk:
    """A compact diff hunk suitable for frontend rendering."""

    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: list[DiffLine] = field(default_factory=list)


@dataclass
class DiffArtifact:
    """A file-scoped diff artifact derived from structured workspace changes."""

    id: str
    run_id: str | None
    file_path: str
    old_digest: str | None = None
    new_digest: str | None = None
    hunks: list[DiffHunk] = field(default_factory=list)
    binary: bool = False
    truncated: bool = False


@dataclass
class ApprovalCard:
    """A pending approval summary for the frontend approval rail."""

    token: str
    action_type: str
    tool_name: str | None
    title: str
    risk_level: str | None = None
    summary: str | None = None
    changed_files: list[str] = field(default_factory=list)
    command: str | None = None
    diff_artifact_ids: list[str] = field(default_factory=list)
    created_at: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class TestRunResult:
    """A normalized test execution outcome."""

    __test__ = False

    command: str
    exit_code: int | None
    duration_ms: int | None = None
    passed: int | None = None
    failed: int | None = None
    skipped: int | None = None
    output_excerpt: str | None = None


@dataclass
class RunSummary:
    """A run-level summary block for completed agent work."""

    task: str | None
    status: str
    files_changed: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    tests: list[TestRunResult] = field(default_factory=list)
    approvals: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


@dataclass
class AssistantMessageBlock:
    """A model-authored explanation block that can appear in the timeline."""

    id: str
    run_id: str | None
    content: str
    type: str = "assistant_message"
    created_at: str | None = None
    related_step_ids: list[str] = field(default_factory=list)


@dataclass
class AgentActionGroup:
    """A runtime-derived action cluster that groups factual tool activity."""

    id: str
    run_id: str | None
    message_id: str | None
    title: str
    status: str
    command_count: int = 0
    file_read_count: int = 0
    file_edit_count: int = 0
    file_create_count: int = 0
    file_delete_count: int = 0
    approval_count: int = 0
    test_count: int = 0
    error_count: int = 0
    tool_call_ids: list[str] = field(default_factory=list)
    step_ids: list[str] = field(default_factory=list)
    started_at: str | None = None
    ended_at: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class TimelineBlock:
    """A frontend timeline unit that can represent text, facts, approvals, or results."""

    id: str
    run_id: str | None
    type: str
    status: str
    title: str | None = None
    content: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    children: list[dict[str, Any]] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)


def to_jsonable(obj: Any) -> Any:
    """Convert timeline dataclasses and helper objects into JSON-safe values."""

    if is_dataclass(obj):
        return {key: to_jsonable(value) for key, value in asdict(obj).items()}
    if hasattr(obj, "model_dump"):
        return to_jsonable(obj.model_dump(mode="json"))
    if isinstance(obj, dict):
        return {str(key): to_jsonable(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [to_jsonable(value) for value in obj]
    if isinstance(obj, tuple):
        return [to_jsonable(value) for value in obj]
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def timeline_to_jsonable(obj: Any) -> Any:
    """Convert timeline dataclasses into JSON-safe data structures."""

    return to_jsonable(obj)


def from_runtime_event(event: Any) -> AgentStep:
    """Turn a runtime event into a traceable timeline step."""

    payload = _as_mapping(event)
    event_type = str(payload.get("type") or payload.get("event_type") or "error")
    details = _as_mapping(payload.get("details"))
    status = _status_from_event(event_type, payload, details)
    title = _title_from_event(event_type, payload, details)
    summary = _string_or_none(
        details.get("summary")
        or payload.get("message")
        or details.get("message")
        or details.get("reason")
        or payload.get("delta")
    )
    artifact_ids = _list_of_strings(details.get("artifact_ids") or details.get("diff_artifact_ids"))
    if not artifact_ids:
        artifact_ids = _list_of_strings(details.get("changed_files"))
    return AgentStep(
        id=_string_or_default(payload.get("event_id") or payload.get("id") or ""),
        run_id=_string_or_none(payload.get("run_id")),
        parent_id=_string_or_none(payload.get("parent_activity_id") or details.get("parent_id")),
        type=event_type,
        status=status,
        title=title,
        summary=summary,
        started_at=_timestamp_string(payload.get("started_at") or details.get("started_at")),
        ended_at=_timestamp_string(payload.get("ended_at") or details.get("ended_at")),
        duration_ms=_int_or_none(payload.get("duration_ms") or details.get("duration_ms")),
        details=to_jsonable(details),
        artifact_ids=artifact_ids,
    )


def file_operations_from_structured_changes(structured_changes: Any) -> list[FileOperation]:
    """Convert structured change payloads into file operations."""

    operations: list[FileOperation] = []
    for change in _normalize_structured_changes(structured_changes):
        operation = _operation_from_change(change)
        operations.append(
            FileOperation(
                path=str(change.get("path") or ""),
                operation=operation,
                status=str(change.get("status") or ("deleted" if operation == "deleted" else "modified")),
                lines_added=_int_or_none(change.get("lines_added")),
                lines_deleted=_int_or_none(change.get("lines_deleted")),
                summary=_string_or_none(change.get("summary") or change.get("content_text")),
            )
        )
    return operations


def diff_artifacts_from_structured_changes(structured_changes: Any) -> list[DiffArtifact]:
    """Convert structured changes into frontend diff artifacts."""

    artifacts: list[DiffArtifact] = []
    for index, change in enumerate(_normalize_structured_changes(structured_changes), start=1):
        path = str(change.get("path") or f"unknown-{index}")
        content_text = change.get("content_text")
        artifact_id = str(change.get("artifact_id") or change.get("id") or f"diff-{index}")
        lines = _diff_lines_from_change(change, content_text)
        hunk = DiffHunk(
            old_start=1,
            old_lines=0 if change.get("change_type") in {"create", "created", "added"} else len(lines),
            new_start=1,
            new_lines=len(lines),
            lines=lines,
        )
        artifacts.append(
            DiffArtifact(
                id=artifact_id,
                run_id=_string_or_none(change.get("run_id")),
                file_path=path,
                old_digest=_string_or_none(change.get("old_digest")),
                new_digest=_string_or_none(change.get("new_digest")),
                hunks=[hunk],
                binary=bool(change.get("binary")),
                truncated=bool(change.get("truncated")),
            )
        )
    return artifacts


def approval_card_from_pending_action(pending_payload: Any) -> ApprovalCard:
    """Convert a pending action payload into an approval card."""

    payload = _as_mapping(pending_payload)
    details = _as_mapping(payload.get("details"))
    effect = _as_mapping(payload.get("effect"))
    action_type = str(payload.get("action_type") or effect.get("tool_name") or "pending_action")
    tool_name = _string_or_none(payload.get("tool_name") or effect.get("tool_name") or details.get("tool_name"))
    changed_files = _list_of_strings(details.get("changed_files") or payload.get("changed_files"))
    if not changed_files:
        changed_files = _list_of_strings(details.get("files"))
    diff_artifact_ids = _list_of_strings(details.get("diff_artifact_ids") or details.get("artifact_ids"))
    command = _string_or_none(payload.get("command") or details.get("command") or effect.get("command"))
    risk_level = _string_or_none(details.get("risk_level") or effect.get("risk_level") or payload.get("risk_level"))
    summary = _string_or_none(details.get("summary") or effect.get("summary") or payload.get("summary"))
    if not summary and action_type == "run_shell":
        summary = "Run shell command"
    if not summary and action_type == "apply_patch_candidate":
        summary = "Apply staged patch"
    created_at = _timestamp_string(payload.get("created_at") or details.get("created_at"))
    title = _approval_title(action_type, tool_name, summary)
    return ApprovalCard(
        token=str(payload.get("token") or ""),
        action_type=action_type,
        tool_name=tool_name,
        title=title,
        risk_level=risk_level,
        summary=summary,
        changed_files=changed_files,
        command=command,
        diff_artifact_ids=diff_artifact_ids,
        created_at=created_at,
        details=to_jsonable(details),
    )


def _approval_title(action_type: str, tool_name: str | None, summary: str | None) -> str:
    """Build a compact approval title for the pending action rail."""

    if summary:
        return summary
    action_label = action_type.replace("_", " ").strip().title() or "Pending action"
    if tool_name:
        return f"{action_label}: {tool_name}"
    return action_label


def run_summary_from_items(
    *,
    task: str | None,
    status: str,
    files_changed: Any = None,
    commands_run: Any = None,
    tests: Any = None,
    approvals: Any = None,
    risks: Any = None,
    next_steps: Any = None,
) -> RunSummary:
    """Build a run summary from JSON-friendly item collections."""

    return RunSummary(
        task=task,
        status=status,
        files_changed=_list_of_strings(files_changed),
        commands_run=_list_of_strings(commands_run),
        tests=[item if isinstance(item, TestRunResult) else TestRunResult(**_as_mapping(item)) for item in (tests or [])],
        approvals=_list_of_strings(approvals),
        risks=_list_of_strings(risks),
        next_steps=_list_of_strings(next_steps),
    )


def assistant_message_to_block(
    *,
    id: str,
    run_id: str | None,
    content: str,
    created_at: str | None = None,
    related_step_ids: list[str] | None = None,
) -> AssistantMessageBlock:
    """Build an assistant message block for the conversational timeline."""

    return AssistantMessageBlock(
        id=id,
        run_id=run_id,
        content=content,
        created_at=created_at,
        related_step_ids=_list_of_strings(related_step_ids),
    )


def agent_steps_to_action_group(
    agent_steps: Any,
    *,
    id: str,
    run_id: str | None,
    message_id: str | None = None,
) -> AgentActionGroup:
    """Aggregate runtime steps into a fact-based action group."""

    steps = [from_runtime_event(step) if not isinstance(step, AgentStep) else step for step in (agent_steps or [])]
    command_count = 0
    file_read_count = 0
    file_edit_count = 0
    file_create_count = 0
    file_delete_count = 0
    approval_count = 0
    test_count = 0
    error_count = 0
    tool_call_ids: list[str] = []
    step_ids: list[str] = []
    started_at = None
    ended_at = None
    for step in steps:
        step_ids.append(step.id)
        details = step.details if isinstance(step.details, dict) else {}
        tool_name = str(details.get("tool_name") or details.get("name") or "").strip()
        event_type = step.type
        if event_type == "shell_command" or tool_name == "run_shell":
            command_count += 1
            tool_call_ids.extend(_list_of_strings(details.get("tool_call_id") or step.id))
        if event_type == "file_read" or tool_name == "read_file":
            file_read_count += 1
        if event_type == "file_edit" or _change_type_in_details(details, {"modified", "edited"}):
            file_edit_count += 1
        if event_type == "file_create" or _change_type_in_details(details, {"created", "added"}):
            file_create_count += 1
        if event_type == "file_delete" or _change_type_in_details(details, {"deleted", "removed"}):
            file_delete_count += 1
        if event_type == "approval_required" or step.status == "waiting_approval" or bool(details.get("approval_token")):
            approval_count += 1
        if event_type == "test_run":
            test_count += 1
        if step.status == "failed" or event_type == "error":
            error_count += 1
        if started_at is None and step.started_at is not None:
            started_at = step.started_at
        if step.ended_at is not None:
            ended_at = step.ended_at
    status = "failed" if error_count else "waiting_approval" if approval_count and not (command_count or file_read_count or file_edit_count or file_create_count or file_delete_count or test_count) else "running" if any([command_count, file_read_count, file_edit_count, file_create_count, file_delete_count, test_count]) else "succeeded"
    title = _action_group_title(
        status=status,
        command_count=command_count,
        file_read_count=file_read_count,
        file_edit_count=file_edit_count,
        file_create_count=file_create_count,
        file_delete_count=file_delete_count,
        approval_count=approval_count,
        test_count=test_count,
        error_count=error_count,
    )
    details = {
        "step_count": len(steps),
        "step_types": sorted({step.type for step in steps}),
    }
    return AgentActionGroup(
        id=id,
        run_id=run_id,
        message_id=message_id,
        title=title,
        status=status,
        command_count=command_count,
        file_read_count=file_read_count,
        file_edit_count=file_edit_count,
        file_create_count=file_create_count,
        file_delete_count=file_delete_count,
        approval_count=approval_count,
        test_count=test_count,
        error_count=error_count,
        tool_call_ids=sorted({tool_call_id for tool_call_id in tool_call_ids if tool_call_id}),
        step_ids=step_ids,
        started_at=started_at,
        ended_at=ended_at,
        details=details,
    )


def action_group_to_block(action_group: AgentActionGroup) -> TimelineBlock:
    """Wrap an action group as a frontend timeline block."""

    return TimelineBlock(
        id=action_group.id,
        run_id=action_group.run_id,
        type="action_group",
        status=action_group.status,
        title=action_group.title,
        details=to_jsonable(action_group),
        artifact_ids=list(action_group.tool_call_ids),
    )


def approval_card_to_block(card: ApprovalCard) -> TimelineBlock:
    """Wrap an approval card as a frontend timeline block."""

    return TimelineBlock(
        id=card.token,
        run_id=None,
        type="approval_card",
        status="waiting_approval",
        title=card.title,
        content=card.summary,
        details=to_jsonable(card),
        artifact_ids=list(card.diff_artifact_ids),
    )


def test_result_to_block(test_result: TestRunResult, *, id: str, run_id: str | None = None) -> TimelineBlock:
    """Wrap a test result as a timeline block."""

    status = "failed" if test_result.exit_code not in (None, 0) or (test_result.failed or 0) > 0 else "succeeded"
    content = test_result.output_excerpt or test_result.command
    return TimelineBlock(
        id=id,
        run_id=run_id,
        type="test_result",
        status=status,
        title="Test result",
        content=content,
        details=to_jsonable(test_result),
    )


test_result_to_block.__test__ = False


def run_summary_to_block(summary: RunSummary, *, id: str, run_id: str | None = None) -> TimelineBlock:
    """Wrap a run summary as the final timeline block."""

    return TimelineBlock(
        id=id,
        run_id=run_id,
        type="summary",
        status=summary.status,
        title=summary.task or "Run summary",
        content="; ".join(summary.next_steps) or None,
        details=to_jsonable(summary),
        artifact_ids=list(summary.files_changed),
    )


def project_context_to_timeline_step(context: ProjectContext, *, id: str = "project-context") -> AgentStep:
    """Convert project bootstrap context into a visible timeline step."""

    return AgentStep(
        id=id,
        run_id=None,
        parent_id=None,
        type="project_context",
        status="succeeded",
        title="Project context",
        summary=context.summary_text,
        details=to_jsonable(_project_context_details(context)),
        artifact_ids=list(context.manifest_files),
    )


def project_context_to_block(context: ProjectContext, *, id: str = "project-context") -> TimelineBlock:
    """Convert project bootstrap context into a renderable timeline block."""

    return TimelineBlock(
        id=id,
        run_id=None,
        type="project_context",
        status="succeeded",
        title="Project context",
        content=context.summary_text,
        details=to_jsonable(_project_context_details(context)),
        children=[],
        artifact_ids=list(context.manifest_files),
    )


def repository_analysis_to_timeline_step(analysis: RepositoryAnalysis, *, id: str = "repository-analysis") -> AgentStep:
    """Convert repository analysis into a visible timeline step."""

    return AgentStep(
        id=id,
        run_id=None,
        parent_id=None,
        type="repository_analysis",
        status="succeeded",
        title="Repository analysis",
        summary=analysis.summary_text,
        details=to_jsonable(_repository_analysis_details(analysis)),
        artifact_ids=_repository_analysis_artifact_ids(analysis),
    )


def repository_analysis_to_block(analysis: RepositoryAnalysis, *, id: str = "repository-analysis") -> TimelineBlock:
    """Convert repository analysis into a renderable timeline block."""

    return TimelineBlock(
        id=id,
        run_id=None,
        type="repository_analysis",
        status="succeeded",
        title="Repository analysis",
        content=analysis.summary_text,
        details=to_jsonable(_repository_analysis_details(analysis)),
        children=[],
        artifact_ids=_repository_analysis_artifact_ids(analysis),
    )


def task_plan_to_timeline_step(plan: TaskPlan, *, id: str = "task-plan") -> AgentStep:
    """Convert a rule-based TaskPlan into a Web/TUI-visible planning timeline step."""

    return AgentStep(
        id=id,
        run_id=None,
        parent_id=None,
        type="plan",
        status="succeeded",
        title="Generated task plan",
        summary=plan.summary_text,
        details=to_jsonable(task_plan_to_dict(plan)),
        artifact_ids=list(plan.files_to_inspect),
    )


def task_plan_to_block(plan: TaskPlan, *, id: str = "task-plan") -> TimelineBlock:
    """Convert a rule-based TaskPlan into a renderable Web/TUI timeline block."""

    return TimelineBlock(
        id=id,
        run_id=None,
        type="plan",
        status="succeeded",
        title="Generated task plan",
        content=plan.summary_text,
        details=to_jsonable(task_plan_to_dict(plan)),
        children=[],
        artifact_ids=list(plan.files_to_inspect),
    )


def task_scope_to_timeline_step(scope: TaskScope, *, id: str = "task-scope") -> AgentStep:
    """Convert TaskScope into a Web/TUI-visible timeline step without enforcing tools."""

    return AgentStep(
        id=id,
        run_id=None,
        parent_id=None,
        type="task_scope",
        status="succeeded",
        title="Generated task scope",
        summary=scope.summary_text,
        details=to_jsonable(task_scope_to_dict(scope)),
        artifact_ids=list(scope.allowed_paths),
    )


def task_scope_to_block(scope: TaskScope, *, id: str = "task-scope") -> TimelineBlock:
    """Convert TaskScope into a renderable Web/TUI timeline block for task boundaries."""

    return TimelineBlock(
        id=id,
        run_id=None,
        type="task_scope",
        status="succeeded",
        title="Generated task scope",
        content=scope.summary_text,
        details=to_jsonable(task_scope_to_dict(scope)),
        children=[],
        artifact_ids=list(scope.allowed_paths),
    )


def change_impact_to_timeline_step(impact: ChangeImpact, *, id: str = "change-impact") -> AgentStep:
    """Convert ChangeImpact into a Web/TUI-visible timeline step without enforcing validation."""

    return AgentStep(
        id=id,
        run_id=None,
        parent_id=None,
        type="change_impact",
        status="succeeded",
        title="Analyzed change impact",
        summary=impact.summary_text,
        details=to_jsonable(change_impact_to_dict(impact)),
        artifact_ids=list(impact.changed_paths),
    )


def change_impact_to_block(impact: ChangeImpact, *, id: str = "change-impact") -> TimelineBlock:
    """Convert ChangeImpact into a renderable Web/TUI timeline block."""

    return TimelineBlock(
        id=id,
        run_id=None,
        type="change_impact",
        status="succeeded",
        title="Analyzed change impact",
        content=impact.summary_text,
        details=to_jsonable(change_impact_to_dict(impact)),
        children=[],
        artifact_ids=list(impact.changed_paths),
    )


def validation_plan_to_timeline_step(plan: ValidationPlan, *, id: str = "validation-plan") -> AgentStep:
    """Convert ValidationPlan into a Web/TUI-visible timeline step without running commands."""

    return AgentStep(
        id=id,
        run_id=None,
        parent_id=None,
        type="validation_plan",
        status="succeeded",
        title="Generated validation plan",
        summary=plan.summary_text,
        details=to_jsonable(validation_plan_to_dict(plan)),
        artifact_ids=[command.command for command in plan.commands],
    )


def validation_plan_to_block(plan: ValidationPlan, *, id: str = "validation-plan") -> TimelineBlock:
    """Convert ValidationPlan into a renderable Web/TUI timeline block."""

    return TimelineBlock(
        id=id,
        run_id=None,
        type="validation_plan",
        status="succeeded",
        title="Generated validation plan",
        content=plan.summary_text,
        details=to_jsonable(validation_plan_to_dict(plan)),
        children=[],
        artifact_ids=[command.command for command in plan.commands],
    )


def scope_enforcement_to_timeline_step(result: ScopeEnforcementResult, *, id: str = "scope-enforcement") -> AgentStep:
    """Convert task-level scope enforcement into a Web/TUI step without replacing sandbox or approval."""

    return AgentStep(
        id=id,
        run_id=None,
        parent_id=None,
        type="scope_enforcement",
        status=_scope_enforcement_status(result),
        title=_scope_enforcement_title(result),
        summary=result.summary_text,
        details=to_jsonable(scope_enforcement_to_details(result)),
        artifact_ids=list(result.checked_paths),
    )


def scope_enforcement_to_block(result: ScopeEnforcementResult, *, id: str = "scope-enforcement") -> TimelineBlock:
    """Convert task-level scope enforcement into a renderable block for approvals and Web/TUI."""

    return TimelineBlock(
        id=id,
        run_id=None,
        type="scope_enforcement",
        status=_scope_enforcement_status(result),
        title=_scope_enforcement_title(result),
        content=result.summary_text,
        details=to_jsonable(scope_enforcement_to_details(result)),
        children=[],
        artifact_ids=list(result.checked_paths),
    )


def manifest_to_timeline_step(manifest: ProjectManifest, *, id: str | None = None, run_id: str | None = None) -> AgentStep:
    """Convert a manifest preview into a visible timeline step."""

    manifest_name = Path(manifest.path).name
    return AgentStep(
        id=id or f"manifest:{manifest_name}",
        run_id=run_id,
        parent_id=None,
        type="manifest_loaded",
        status="succeeded",
        title=f"Manifest loaded: {manifest_name}",
        summary=manifest.content_excerpt,
        details=to_jsonable(asdict(manifest)),
        artifact_ids=[manifest.path],
    )


def manifest_to_block(manifest: ProjectManifest, *, id: str | None = None, run_id: str | None = None) -> TimelineBlock:
    """Convert a loaded manifest into a renderable timeline block."""

    manifest_name = Path(manifest.path).name
    return TimelineBlock(
        id=id or f"manifest:{manifest_name}",
        run_id=run_id,
        type="manifest_loaded",
        status="succeeded",
        title=f"Manifest loaded: {manifest_name}",
        content=manifest.content_excerpt,
        details=to_jsonable(asdict(manifest)),
        children=[],
        artifact_ids=[manifest.path],
    )


def _status_from_event(event_type: str, payload: dict[str, Any], details: dict[str, Any]) -> str:
    raw_status = str(payload.get("status") or details.get("status") or "").strip().lower()
    if raw_status in TIMELINE_STATUSES:
        return raw_status
    if payload.get("is_error") or event_type == "error":
        return "failed"
    if event_type in {"approval_required", "tool_policy_decision"}:
        decision = str(details.get("decision") or details.get("action") or payload.get("status") or "").strip().lower()
        if decision in {"deny", "denied", "reject", "rejected", "blocked"}:
            return "waiting_approval"
        if decision in {"ask", "pending", "review", "approve"}:
            return "waiting_approval"
    if event_type in {"file_delete", "rollback"}:
        return "running"
    if event_type == "summary":
        return "succeeded"
    return "succeeded"


def _title_from_event(event_type: str, payload: dict[str, Any], details: dict[str, Any]) -> str:
    if event_type == "tool_call":
        tool_name = _string_or_none(payload.get("tool_name") or details.get("tool_name"))
        return f"Tool call: {tool_name}" if tool_name else "Tool call"
    if event_type == "tool_policy_decision":
        tool_name = _string_or_none(payload.get("tool_name") or details.get("tool_name"))
        decision = _string_or_none(details.get("decision") or details.get("action"))
        bits = ["Policy decision"]
        if tool_name:
            bits.append(tool_name)
        if decision:
            bits.append(decision)
        return " ".join(bits)
    if event_type == "shell_command":
        return "Shell command"
    if event_type.startswith("file_"):
        path = _string_or_none(details.get("path") or payload.get("path"))
        return f"{event_type.replace('_', ' ').title()}: {path}" if path else event_type.replace("_", " ").title()
    if event_type == "approval_required":
        return "Approval required"
    if event_type == "patch_candidate":
        return "Patch candidate"
    if event_type == "patch_apply":
        return "Patch applied"
    if event_type == "summary":
        return "Run summary"
    if event_type == "error":
        return "Error"
    return event_type.replace("_", " ").strip().title()


def _scope_enforcement_status(result: ScopeEnforcementResult) -> str:
    if result.allowed is None:
        return "skipped"
    return "succeeded" if result.allowed else "failed"


def _scope_enforcement_title(result: ScopeEnforcementResult) -> str:
    if result.allowed is True:
        return "Checked task scope"
    if result.allowed is False:
        return "Task scope check failed"
    return "Task scope check not applied"


def _action_group_title(
    *,
    status: str,
    command_count: int,
    file_read_count: int,
    file_edit_count: int,
    file_create_count: int,
    file_delete_count: int,
    approval_count: int,
    test_count: int,
    error_count: int,
) -> str:
    if error_count > 0:
        return "Operation failed"
    if status == "waiting_approval" or approval_count > 0:
        return "Waiting for approval"
    if command_count > 0 and not any([file_read_count, file_edit_count, file_create_count, file_delete_count, test_count]):
        return f"Ran {command_count} command{'s' if command_count != 1 else ''}"
    if file_edit_count > 0:
        return f"{'Editing' if status == 'running' else 'Edited'} {file_edit_count} file{'s' if file_edit_count != 1 else ''}"
    if file_create_count > 0:
        return f"Created {file_create_count} file{'s' if file_create_count != 1 else ''}"
    if file_delete_count > 0:
        return f"Deleted {file_delete_count} file{'s' if file_delete_count != 1 else ''}"
    if test_count > 0:
        return f"Ran {test_count} test{'s' if test_count != 1 else ''}"
    if file_read_count > 0:
        return f"Read {file_read_count} file{'s' if file_read_count != 1 else ''}"
    return "Operation complete"


def _diff_lines_from_change(change: dict[str, Any], content_text: Any) -> list[DiffLine]:
    text = _string_or_none(content_text)
    if text is None:
        return []
    lines = text.splitlines()
    change_type = str(change.get("change_type") or change.get("operation") or "modified").lower()
    if change_type in {"delete", "deleted", "removed"}:
        return [DiffLine(type="removed", text=line) for line in lines]
    return [DiffLine(type="added", text=line) for line in lines]


def _operation_from_change(change: dict[str, Any]) -> str:
    raw = str(change.get("operation") or change.get("change_type") or "modified").lower()
    if raw in {"create", "created", "added", "new"}:
        return "created"
    if raw in {"delete", "deleted", "removed"}:
        return "deleted"
    if raw in {"rename", "renamed"}:
        return "renamed"
    if raw in {"read"}:
        return "read"
    return "modified"


def _change_type_in_details(details: dict[str, Any], candidates: set[str]) -> bool:
    raw = str(details.get("change_type") or details.get("operation") or details.get("status") or "").lower()
    return raw in candidates


def _normalize_structured_changes(structured_changes: Any) -> list[dict[str, Any]]:
    if structured_changes is None:
        return []
    if isinstance(structured_changes, dict):
        items = structured_changes.get("changes") or structured_changes.get("items") or []
    else:
        items = structured_changes
    normalized: list[dict[str, Any]] = []
    for item in items or []:
        if is_dataclass(item):
            normalized.append(asdict(item))
        elif hasattr(item, "to_dict"):
            normalized.append(dict(item.to_dict()))
        elif isinstance(item, dict):
            normalized.append(dict(item))
    return normalized


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if is_dataclass(value):
        return dict(asdict(value))
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    if isinstance(value, dict):
        return value
    return dict(getattr(value, "__dict__", {}) or {})


def _list_of_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)] if str(value).strip() else []


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_or_default(value: Any) -> str:
    return str(value or "")


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _timestamp_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value)).isoformat()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:  # noqa: BLE001
            return str(value)
    return str(value)


def _project_context_details(context: ProjectContext) -> dict[str, Any]:
    return {
        "workspace_path": context.workspace_path,
        "workspace_name": context.workspace_name,
        "detected_languages": list(context.detected_languages),
        "detected_frameworks": list(context.detected_frameworks),
        "important_paths": list(context.important_paths),
        "likely_test_commands": list(context.likely_test_commands),
        "manifest_files": list(context.manifest_files),
        "warnings": list(context.warnings),
    }


def _repository_analysis_details(analysis: RepositoryAnalysis) -> dict[str, Any]:
    return {
        "workspace_path": analysis.workspace_path,
        "workspace_name": analysis.workspace_name,
        "project_type": analysis.project_type,
        "languages": list(analysis.languages),
        "frameworks": list(analysis.frameworks),
        "source_roots": list(analysis.source_roots),
        "test_roots": list(analysis.test_roots),
        "doc_roots": list(analysis.doc_roots),
        "frontend_roots": list(analysis.frontend_roots),
        "backend_roots": list(analysis.backend_roots),
        "config_files": list(analysis.config_files),
        "ci_files": list(analysis.ci_files),
        "entry_points": list(analysis.entry_points),
        "module_map": {key: list(value) for key, value in analysis.module_map.items()},
        "likely_test_commands": list(analysis.likely_test_commands),
        "warnings": list(analysis.warnings),
    }


def _repository_analysis_artifact_ids(analysis: RepositoryAnalysis) -> list[str]:
    return _unique_strings([*analysis.entry_points, *analysis.config_files, *analysis.ci_files])


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique
