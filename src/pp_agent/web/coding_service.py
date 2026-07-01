from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import uuid4

from pp_agent.coding import (
    ControlledLoopOptions,
    ControlledToolLoopResult,
    CodingExecutionSession,
    CodingWorkflow,
    prepare_coding_workflow,
    run_controlled_coding_loop,
    start_coding_execution_session,
)
from pp_agent.observability.timeline import to_jsonable
from pp_agent.runtime.execution_context import runtime_counters_to_dict


RuntimeFactory = Callable[[Path], Any]
ApprovalHandler = Callable[[Path, str], dict[str, Any]]
RejectHandler = Callable[[Path, str, Optional[str]], dict[str, Any]]


class CodingTaskNotFound(ValueError):
    """Raised when a Web/API coding task id is not present in the service store."""


class CodingApprovalNotFound(ValueError):
    """Raised when a pending approval token is not present on a stored coding task."""


class CodingApprovalNotSupported(RuntimeError):
    """Raised when the service cannot safely reach the existing approval backend."""


@dataclass
class CodingTaskState:
    """Web/API task state for controlled coding workflows.

    This state is a frontend-facing summary, not a tool runtime object. It is JSON-friendly,
    filters pending payloads and file contents, and never implies that approvals were granted or
    patches were applied. Future Web and TUI surfaces can reuse this shape.
    """

    task_id: str
    task: str
    status: str
    stop_reason: str | None = None
    workflow_summary: str | None = None
    timeline_blocks: list[dict[str, Any]] = field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = field(default_factory=list)
    validation_commands: list[dict[str, Any]] = field(default_factory=list)
    runtime_counters: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class InMemoryCodingTaskStore:
    """In-memory store for Web/API coding task states.

    The store is an MVP service backing store, not a runtime, approval store, or database. It keeps
    sanitized `CodingTaskState` objects for Web/TUI reuse and does not approve, apply, or execute
    pending actions.
    """

    def __init__(self) -> None:
        self._states: dict[str, CodingTaskState] = {}
        self._order: list[str] = []

    def create(self, state: CodingTaskState) -> CodingTaskState:
        """Store a new sanitized task state without executing or approving anything."""

        self._states[state.task_id] = state
        self._order = [item for item in self._order if item != state.task_id]
        self._order.append(state.task_id)
        return state

    def get(self, task_id: str) -> CodingTaskState | None:
        """Return a stored Web/API task state by id, or None when it is unknown."""

        return self._states.get(str(task_id))

    def update(self, state: CodingTaskState) -> CodingTaskState:
        """Replace a stored sanitized task state without mutating approval or patch state."""

        self._states[state.task_id] = state
        self._order = [item for item in self._order if item != state.task_id]
        self._order.append(state.task_id)
        return state

    def list_recent(self, limit: int = 20) -> list[CodingTaskState]:
        """List recent sanitized task states for Web/API consumers."""

        bounded = max(0, int(limit))
        ids = list(reversed(self._order))[:bounded]
        return [self._states[item] for item in ids if item in self._states]


class CodingWorkflowService:
    """Web/API service wrapper around the controlled coding workflow.

    The service is an API contract layer, not a tool runtime and not a Web UI. It can prepare or run
    a bounded controlled loop, stores sanitized `CodingTaskState` summaries, never auto-approves or
    auto-applies pending actions, and filters payloads/file contents for future Web/TUI reuse.
    """

    def __init__(
        self,
        workspace: Path | None = None,
        *,
        store: InMemoryCodingTaskStore | None = None,
        runtime_factory: RuntimeFactory | None = None,
        approval_handler: ApprovalHandler | None = None,
        reject_handler: RejectHandler | None = None,
    ) -> None:
        self.workspace = Path(workspace) if workspace is not None else None
        self.store = store or InMemoryCodingTaskStore()
        self._runtime_factory = runtime_factory or _default_runtime_factory
        self._approval_handler = approval_handler or _default_approval_handler
        self._reject_handler = reject_handler or _default_reject_handler

    def start_task(
        self,
        task: str,
        workspace: Path | None = None,
        max_turns: int = 3,
        prepare_only: bool = False,
    ) -> CodingTaskState:
        """Start a Web/API coding task and store its sanitized state.

        `prepare_only=True` prepares workflow/session contracts and does not call the controlled
        loop. Otherwise the service runs `run_controlled_coding_loop` with stop-on-approval,
        stop-on-guardrail, and stop-on-scope options. Neither path auto-approves or applies patches.
        """

        resolved_workspace = self._workspace(workspace)
        normalized_task = task.strip() or "Unspecified task"
        task_id = f"coding-task-{uuid4().hex[:12]}"
        if prepare_only:
            workflow = prepare_coding_workflow(normalized_task, workspace=resolved_workspace)
            session = start_coding_execution_session(workflow)
            return self.store.create(_state_from_prepare(task_id, workflow, session))

        runtime = self._runtime_factory(resolved_workspace)
        options = ControlledLoopOptions(
            max_model_turns=max(0, int(max_turns)),
            stop_on_approval=True,
            stop_on_guardrail_block=True,
            stop_on_scope_block=True,
            dry_run=False,
        )
        result = run_controlled_coding_loop(normalized_task, runtime, workspace=resolved_workspace, options=options)
        return self.store.create(_state_from_controlled_result(task_id, result))

    def get_task(self, task_id: str) -> CodingTaskState | None:
        """Return a sanitized Web/API task state without exposing raw runtime payloads."""

        return self.store.get(task_id)

    def get_timeline(self, task_id: str) -> list[dict[str, Any]]:
        """Return compact timeline summaries for a stored task state."""

        state = self.get_task(task_id)
        return list(state.timeline_blocks) if state is not None else []

    def get_pending_approvals(self, task_id: str) -> list[dict[str, Any]]:
        """Return sanitized pending approvals for a stored task state."""

        state = self.get_task(task_id)
        return list(state.pending_approvals) if state is not None else []

    def get_validation_plan(self, task_id: str) -> list[dict[str, Any]]:
        """Return Web/API validation command summaries for a stored task state."""

        state = self.get_task(task_id)
        return list(state.validation_commands) if state is not None else []

    def approve_action(self, task_id: str, token: str) -> CodingTaskState:
        """Approve a pending action through the existing approval backend.

        The service verifies that the task and token are known, delegates to the injected or
        default approval handler, and stores a sanitized state update. It does not apply patches,
        run shell commands, bypass payload digest checks, or grant approval directly.
        """

        state = self._require_task(task_id)
        approval = self._require_approval(state, token)
        try:
            result = self._approval_handler(self._workspace(None), token)
        except CodingApprovalNotSupported:
            raise
        except Exception as exc:  # noqa: BLE001
            updated = _state_with_approval_result(
                state,
                token,
                approval,
                action="approve",
                result={"success": False, "error": str(exc)},
                remove=False,
            )
            self.store.update(updated)
            raise CodingApprovalNotSupported(str(exc)) from exc
        updated = _state_with_approval_result(
            state,
            token,
            approval,
            action="approve",
            result=result,
            remove=_approval_result_success(result),
        )
        return self.store.update(updated)

    def reject_action(self, task_id: str, token: str, reason: str | None = None) -> CodingTaskState:
        """Reject a pending action without executing the staged action.

        Rejection delegates to the existing reject backend when available. If that path is not
        available, the service records a service-level rejection in the sanitized task state and
        removes the approval from the Web/API summary without touching files, shell, patches,
        sandbox, payload digest, or write-scope enforcement.
        """

        state = self._require_task(task_id)
        approval = self._require_approval(state, token)
        try:
            result = self._reject_handler(self._workspace(None), token, reason)
        except Exception as exc:  # noqa: BLE001
            result = {
                "success": True,
                "result": "service_level_rejected",
                "reason": reason,
                "warning": f"Pending approval was rejected at the service layer: {exc}",
            }
        updated = _state_with_approval_result(
            state,
            token,
            approval,
            action="reject",
            result=result,
            remove=_approval_result_success(result),
        )
        return self.store.update(updated)

    def _workspace(self, workspace: Path | None) -> Path:
        resolved = workspace or self.workspace or Path.cwd()
        return Path(resolved)

    def _require_task(self, task_id: str) -> CodingTaskState:
        state = self.get_task(task_id)
        if state is None:
            raise CodingTaskNotFound("coding task not found")
        return state

    def _require_approval(self, state: CodingTaskState, token: str) -> dict[str, Any]:
        normalized = str(token or "").strip()
        for approval in state.pending_approvals:
            if str(approval.get("token") or "") == normalized:
                return approval
        raise CodingApprovalNotFound("pending approval not found")


def coding_task_state_to_dict(state: CodingTaskState) -> dict[str, Any]:
    """Serialize `CodingTaskState` for Web/API responses.

    The result is JSON-friendly and contains only sanitized summaries: no full pending payloads,
    file contents, secrets, raw diffs, or approval/apply internals.
    """

    return to_jsonable(
        {
            "task_id": state.task_id,
            "task": state.task,
            "status": state.status,
            "stop_reason": state.stop_reason,
            "workflow_summary": state.workflow_summary,
            "timeline_blocks": list(state.timeline_blocks),
            "pending_approvals": [sanitize_pending_approval(item) for item in state.pending_approvals],
            "validation_commands": list(state.validation_commands),
            "runtime_counters": dict(state.runtime_counters),
            "warnings": list(state.warnings),
        }
    )


def sanitize_pending_approval(approval: dict[str, Any]) -> dict[str, Any]:
    """Return a Web/API-safe approval summary.

    Only token, action type, tool name, summary/title, changed files, command, and a compact
    scope-check summary are exposed. Full payloads, file contents, secrets, and digest inputs are
    intentionally omitted.
    """

    summary = {
        "token": str(approval.get("token") or ""),
        "action_type": str(approval.get("action_type") or ""),
        "tool_name": _string_or_none(approval.get("tool_name")),
        "summary": _string_or_none(approval.get("summary") or approval.get("title")),
        "changed_files": _list_of_strings(approval.get("changed_files")),
        "command": _string_or_none(approval.get("command")),
    }
    scope_check = approval.get("scope_check")
    if isinstance(scope_check, dict):
        summary["scope_check"] = {
            "allowed": scope_check.get("allowed"),
            "reason": _string_or_none(scope_check.get("reason")),
            "matched_rule": _string_or_none(scope_check.get("matched_rule")),
            "risk_level": _string_or_none(scope_check.get("risk_level")),
        }
    else:
        summary["scope_check"] = None
    return summary


def summarize_timeline_block(block: Any) -> dict[str, Any]:
    """Return a compact Web/API timeline block summary.

    Timeline summaries expose type, title, status, summary/content preview, and a small details
    subset. Large manifests, payloads, full diffs, file contents, and secret-like fields are not
    included.
    """

    payload = to_jsonable(block)
    mapping = payload if isinstance(payload, dict) else {}
    return {
        "type": mapping.get("type"),
        "title": mapping.get("title"),
        "status": mapping.get("status"),
        "summary": _summary_preview(mapping.get("summary") or mapping.get("content")),
        "details": _compact_timeline_details(mapping.get("details")),
    }


def extract_validation_commands(source: Any) -> list[dict[str, Any]]:
    """Extract Web/API-safe validation command summaries.

    The helper accepts a `ValidationPlan`, `CodingWorkflow`, `CodingExecutionSession`,
    `ControlledToolLoopResult`, list, or dict and returns command metadata only. It does not run
    validation commands or request approval.
    """

    plan = getattr(source, "validation_plan", None)
    if plan is None and hasattr(source, "workflow"):
        plan = getattr(source.workflow, "validation_plan", None)
    if plan is None:
        plan = source
    if hasattr(plan, "commands"):
        return [_validation_command_to_dict(command) for command in plan.commands]
    if isinstance(plan, dict):
        commands = plan.get("commands") or plan.get("validation_commands") or []
        return [_validation_command_to_dict(command) for command in commands]
    if isinstance(plan, list):
        return [_validation_command_to_dict(command) for command in plan]
    return []


def _state_from_prepare(task_id: str, workflow: CodingWorkflow, session: CodingExecutionSession) -> CodingTaskState:
    return CodingTaskState(
        task_id=task_id,
        task=workflow.task,
        status=session.status,
        stop_reason=None,
        workflow_summary=workflow.summary_text,
        timeline_blocks=[summarize_timeline_block(block) for block in session.timeline_blocks],
        pending_approvals=[],
        validation_commands=extract_validation_commands(workflow.validation_plan),
        runtime_counters={"tool_calls": 0, "shell_commands": 0, "patch_candidates": 0},
        warnings=_unique([*workflow.warnings, *session.warnings]),
    )


def _state_from_controlled_result(task_id: str, result: ControlledToolLoopResult) -> CodingTaskState:
    return CodingTaskState(
        task_id=task_id,
        task=result.task,
        status=result.status,
        stop_reason=result.stop_reason,
        workflow_summary=result.summary_text or result.session.workflow.summary_text,
        timeline_blocks=[summarize_timeline_block(block) for block in result.timeline_blocks],
        pending_approvals=[sanitize_pending_approval(item) for item in result.pending_approvals],
        validation_commands=extract_validation_commands(result.validation_plan),
        runtime_counters=runtime_counters_to_dict(result.runtime_execution_context.counters),
        warnings=list(result.warnings),
    )


def _state_with_approval_result(
    state: CodingTaskState,
    token: str,
    approval: dict[str, Any],
    *,
    action: str,
    result: dict[str, Any],
    remove: bool,
) -> CodingTaskState:
    remaining = [item for item in state.pending_approvals if str(item.get("token") or "") != token] if remove else list(state.pending_approvals)
    success = _approval_result_success(result)
    status = "completed" if success and remove and not remaining else state.status
    if action == "approve" and not success:
        status = "approval_failed"
    stop_reason = None if status == "completed" else state.stop_reason
    warning = _approval_warning(action, result, remove)
    return CodingTaskState(
        task_id=state.task_id,
        task=state.task,
        status=status,
        stop_reason=stop_reason,
        workflow_summary=state.workflow_summary,
        timeline_blocks=[
            *state.timeline_blocks,
            _approval_result_timeline_block(token, approval, action=action, result=result, success=success),
        ],
        pending_approvals=[sanitize_pending_approval(item) for item in remaining],
        validation_commands=list(state.validation_commands),
        runtime_counters=dict(state.runtime_counters),
        warnings=_unique([*state.warnings, *([warning] if warning else [])]),
    )


def _approval_result_success(result: dict[str, Any]) -> bool:
    if result.get("success") is False:
        return False
    details = result.get("details")
    if isinstance(details, dict) and details.get("is_error") is True:
        return False
    return True


def _approval_warning(action: str, result: dict[str, Any], remove: bool) -> str | None:
    warning = _string_or_none(result.get("warning"))
    if warning:
        return warning
    if action == "reject" and result.get("result") == "service_level_rejected":
        return "Pending approval was rejected at the service layer; no staged action was executed."
    if action == "approve" and not remove:
        return "Approval backend did not report success; pending action remains visible."
    return None


def _approval_result_timeline_block(
    token: str,
    approval: dict[str, Any],
    *,
    action: str,
    result: dict[str, Any],
    success: bool,
) -> dict[str, Any]:
    return {
        "type": "approval_result",
        "title": "Approval action completed" if success else "Approval action failed",
        "status": "succeeded" if success else "failed",
        "summary": _summary_preview(result.get("result") or result.get("error") or f"{action} {token}"),
        "details": {
            "approval_action": action,
            "token": token,
            "action_type": approval.get("action_type"),
            "tool_name": approval.get("tool_name"),
            "success": success,
            "resumed": result.get("resumed"),
        },
    }


def _default_runtime_factory(workspace: Path) -> Any:
    from pp_agent.app.bootstrap import build_agent

    return build_agent(workspace)


def _default_approval_handler(workspace: Path, token: str) -> dict[str, Any]:
    try:
        from pp_agent.cli.commands.approvals import approve_or_execute_pending_action
    except Exception as exc:  # pragma: no cover
        raise CodingApprovalNotSupported("approval backend is not available") from exc
    return approve_or_execute_pending_action(workspace, token, render=False)


def _default_reject_handler(workspace: Path, token: str, reason: str | None = None) -> dict[str, Any]:
    try:
        from pp_agent.cli.commands.approvals import reject_pending_action
    except Exception as exc:  # pragma: no cover
        raise CodingApprovalNotSupported("approval backend is not available") from exc
    result = reject_pending_action(workspace, token, render=False)
    if reason:
        result = {**result, "reason": reason}
    return result


def _validation_command_to_dict(command: Any) -> dict[str, Any]:
    if isinstance(command, str):
        return {"command": command, "priority": None, "reason": None, "related_paths": []}
    if isinstance(command, dict):
        return {
            "command": str(command.get("command") or ""),
            "priority": _string_or_none(command.get("priority")),
            "reason": _string_or_none(command.get("reason")),
            "related_paths": _list_of_strings(command.get("related_paths")),
        }
    return {
        "command": str(getattr(command, "command", "") or ""),
        "priority": _string_or_none(getattr(command, "priority", None)),
        "reason": _string_or_none(getattr(command, "reason", None)),
        "related_paths": _list_of_strings(getattr(command, "related_paths", None)),
    }


def _compact_timeline_details(details: Any) -> dict[str, Any]:
    mapping = details if isinstance(details, dict) else {}
    compact: dict[str, Any] = {}
    for key in (
        "risk_level",
        "scope_risk_level",
        "impact_risk_level",
        "status",
        "phase",
        "stop_reason",
        "pending_approvals_count",
        "predicted_impact_not_actual",
    ):
        if key in mapping:
            compact[key] = mapping[key]
    if isinstance(mapping.get("validation_commands"), list):
        compact["validation_commands"] = _list_of_strings(mapping["validation_commands"])[:5]
    if isinstance(mapping.get("guardrails"), dict):
        compact["guardrails"] = dict(mapping["guardrails"])
    if isinstance(mapping.get("runtime_execution_context"), dict):
        counters = mapping["runtime_execution_context"].get("counters")
        if isinstance(counters, dict):
            compact["runtime_counters"] = dict(counters)
    if isinstance(mapping.get("write_scope"), dict):
        compact["write_scope"] = _write_scope_summary(mapping["write_scope"])
    if isinstance(mapping.get("runtime_execution_context"), dict):
        scope = mapping["runtime_execution_context"].get("write_scope")
        if isinstance(scope, dict):
            compact["write_scope"] = _write_scope_summary(scope)
    return compact


def _write_scope_summary(scope: dict[str, Any]) -> dict[str, Any]:
    return {
        "allowed_paths_count": len(scope.get("allowed_paths") or []),
        "disallowed_paths_count": len(scope.get("disallowed_paths") or []),
        "allow_delete": scope.get("allow_delete"),
        "max_files_changed": scope.get("max_files_changed"),
        "risk_level": scope.get("risk_level"),
        "source": scope.get("source"),
    }


def _summary_preview(value: Any, *, limit: int = 500) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _list_of_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)] if str(value).strip() else []


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


__all__ = [
    "CodingTaskState",
    "CodingApprovalNotFound",
    "CodingApprovalNotSupported",
    "CodingTaskNotFound",
    "CodingWorkflowService",
    "InMemoryCodingTaskStore",
    "coding_task_state_to_dict",
    "extract_validation_commands",
    "sanitize_pending_approval",
    "summarize_timeline_block",
]
