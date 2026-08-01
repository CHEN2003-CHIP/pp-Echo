from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any

from pp_agent.coding.execution import (
    CodingExecutionSession,
    coding_session_to_runtime_execution_context,
    start_coding_execution_session,
)
from pp_agent.coding.orchestrator import CodingWorkflow, prepare_coding_workflow
from pp_agent.coding.scoped_activation import ScopedInstructionActivationState
from pp_agent.coding.scoped_instruction_context import scoped_instruction_records_to_context_items
from pp_agent.coding.testing import ValidationPlan
from pp_agent.coding.validation_execution import InitialValidationStagingResult, stage_initial_validation_workflow
from pp_agent.coding.workflow_checkpoint_store import CodingWorkflowCheckpointStore
from pp_agent.runtime.execution_context import RuntimeExecutionContext, runtime_counters_to_dict, runtime_execution_context_to_dict
from pp_agent.runtime.hooks import AfterToolCallDecision


_MISSING_SCOPED_CONTEXT_PROVIDER = object()
_SCOPED_CONTEXT_PROVIDER_NOT_INSTALLED = object()


@dataclass(frozen=True)
class ControlledLoopOptions:
    """Options for a finite controlled coding loop, not an autonomous agent loop.

    The loop consumes RuntimeExecutionContext through AgentRuntime/ToolRegistry, stops on approval,
    guardrail, or scope boundaries, and never auto-approves or auto-applies pending actions.
    """

    max_model_turns: int
    stop_on_approval: bool
    stop_on_guardrail_block: bool
    stop_on_scope_block: bool
    dry_run: bool


@dataclass
class ControlledToolLoopResult:
    """Result of a finite controlled coding loop for CLI/TUI/Web surfaces.

    The result packages the prepared workflow/session, runtime context, pending approval summaries,
    timeline blocks, and stop reason. It represents bounded execution only; it does not imply that
    approvals were granted, patches were applied, or sandbox/approval semantics changed.
    """

    task: str
    status: str
    stop_reason: str
    session: CodingExecutionSession
    runtime_execution_context: RuntimeExecutionContext
    timeline_blocks: list[Any] = field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = field(default_factory=list)
    validation_plan: ValidationPlan | None = None
    validation_staging: InitialValidationStagingResult | None = None
    scoped_instruction_activation_state: ScopedInstructionActivationState | None = None
    summary_text: str = ""
    warnings: list[str] = field(default_factory=list)


def default_controlled_loop_options() -> ControlledLoopOptions:
    """Return conservative defaults for a bounded controlled coding loop.

    Defaults limit model turns and stop on approval, guardrail, and scope boundaries. The loop does
    not auto-approve, auto-apply patches, or run without RuntimeExecutionContext guardrails.
    """

    return ControlledLoopOptions(
        max_model_turns=3,
        stop_on_approval=True,
        stop_on_guardrail_block=True,
        stop_on_scope_block=True,
        dry_run=False,
    )


def run_controlled_coding_loop(
    task: str,
    runtime: Any,
    workspace: Path | None = None,
    options: ControlledLoopOptions | None = None,
    workflow: CodingWorkflow | None = None,
    session: CodingExecutionSession | None = None,
    checkpoint_store: CodingWorkflowCheckpointStore | None = None,
    workflow_id: str | None = None,
    expected_checkpoint_revision: int | None = None,
) -> ControlledToolLoopResult:
    """Run a finite controlled coding loop through AgentRuntime.

    The function prepares or reuses CodingWorkflow and CodingExecutionSession, adapts them to
    RuntimeExecutionContext, attaches that context to the provided runtime, then runs a bounded
    prompt/continue loop. It stops on approval, guardrail block, scope block, max turns, completion,
    or runtime errors, and never auto-approves or auto-applies pending actions.
    """

    resolved_options = options or default_controlled_loop_options()
    normalized_task = task.strip() or "Unspecified task"
    resolved_workspace = workspace or _workspace_from_runtime(runtime)
    resolved_workflow = workflow or prepare_coding_workflow(normalized_task, workspace=resolved_workspace)
    resolved_session = session or start_coding_execution_session(resolved_workflow)
    context = coding_session_to_runtime_execution_context(resolved_session)
    activation_state = ScopedInstructionActivationState(repository_root=resolved_workspace) if resolved_workspace is not None else None
    if activation_state is not None:
        activation_state.seed_task_scope(resolved_workflow.task_scope)
    warnings = list(resolved_workflow.warnings) + list(resolved_session.warnings)
    status = "prepared" if resolved_options.dry_run else "running"
    stop_reason = "completed" if resolved_options.dry_run else "max_turns"
    _attach_runtime_execution_context(runtime, context)

    if not resolved_options.dry_run:
        hooks_snapshot = _install_scoped_instruction_observer(runtime, activation_state)
        context_provider_snapshot = _install_scoped_instruction_context_provider(runtime, activation_state)
        try:
            for turn_index in range(max(resolved_options.max_model_turns, 0)):
                if activation_state is not None:
                    activation_state.begin_continuation()
                turn_events = _run_runtime_turn(runtime, normalized_task, first_turn=turn_index == 0)
                context = _runtime_execution_context_from_runtime(runtime, fallback=context)
                pending = collect_pending_approvals(runtime)
                decision = _stop_decision(turn_events, pending, resolved_options)
                if decision is not None:
                    status, stop_reason = decision
                    break
            else:
                status = "completed"
                stop_reason = "max_turns"
        except Exception as exc:  # noqa: BLE001
            status = "failed"
            stop_reason = "runtime_error"
            warnings.append(f"Runtime error: {exc.__class__.__name__}: {exc}")
            context = _runtime_execution_context_from_runtime(runtime, fallback=context)
        finally:
            _restore_runtime_hooks(runtime, hooks_snapshot)
            _restore_scoped_instruction_context_provider(runtime, context_provider_snapshot)

    pending_approvals = collect_pending_approvals(runtime)
    if status in {"prepared", "running"}:
        if pending_approvals and resolved_options.stop_on_approval:
            status = "awaiting_approval"
            stop_reason = "approval_required"
        elif not resolved_options.dry_run:
            status = "completed"
            stop_reason = "completed" if stop_reason == "max_turns" and resolved_options.max_model_turns <= 0 else stop_reason

    validation_staging = _maybe_stage_initial_validation(
        status=status,
        pending_approvals=pending_approvals,
        options=resolved_options,
        workspace=resolved_workspace,
        workflow_id=workflow_id or resolved_session.id,
        runtime=runtime,
        validation_plan=resolved_workflow.validation_plan,
        checkpoint_store=checkpoint_store,
        expected_revision=expected_checkpoint_revision,
    )
    if validation_staging is not None:
        if validation_staging.awaiting_approval:
            pending_approvals = collect_pending_approvals(runtime)
            status = "awaiting_approval"
            stop_reason = "validation_approval_required"
        elif validation_staging.status.startswith("blocked_"):
            status = "validation_staging_blocked"
            stop_reason = validation_staging.status
            warnings.append(f"Initial validation staging blocked: {validation_staging.reason}")

    result = ControlledToolLoopResult(
        task=normalized_task,
        status=status,
        stop_reason=stop_reason,
        session=resolved_session,
        runtime_execution_context=context,
        timeline_blocks=[*resolved_session.timeline_blocks],
        pending_approvals=pending_approvals,
        validation_plan=resolved_workflow.validation_plan,
        validation_staging=validation_staging,
        scoped_instruction_activation_state=activation_state,
        warnings=_unique(warnings),
    )
    result.summary_text = controlled_loop_result_to_summary(result)
    result.timeline_blocks.append(controlled_loop_result_to_block(result))
    return result


def collect_pending_approvals(runtime: Any) -> list[dict[str, Any]]:
    """Collect JSON-friendly pending approval summaries from a runtime or registry.

    The helper returns trace-safe summaries only: token, action type, tool name, summary, changed
    files, command, and scope details when present. If no store is reachable, it returns an empty
    list so CLI/TUI/Web callers can keep running without depending on storage internals.
    """

    store = _pending_store(runtime)
    if store is None:
        return []
    try:
        items = store.list()
    except Exception:  # noqa: BLE001
        return []
    return [_pending_summary(item) for item in items if _is_active_pending(item)]


def controlled_loop_result_to_context_item(result: ControlledToolLoopResult) -> dict[str, Any]:
    """Convert a controlled loop result into JSON-friendly context for CLI/TUI/Web.

    This context reports bounded execution status and stop reason without exposing full pending
    payloads, secrets, prompts, or file contents.
    """

    details = _result_details(result)
    return {
        "id": "controlled-tool-loop",
        "type": "project_context",
        "title": "Controlled tool loop",
        "content": result.summary_text or controlled_loop_result_to_summary(result),
        "source_ref": {"source_type": "project_context", "source_id": result.session.id, "metadata": details},
        "priority": 50,
        "metadata": {"context_section": "project_context", "controlled_tool_loop": details},
    }


def controlled_loop_result_to_summary(result: ControlledToolLoopResult) -> str:
    """Render a stable summary for a finite controlled coding loop.

    The summary highlights status, stop reason, RuntimeExecutionContext counters, approval count,
    and recommended validation commands. It does not claim that validation was executed.
    """

    counters = runtime_counters_to_dict(result.runtime_execution_context.counters)
    commands = [command.command for command in result.validation_plan.commands] if result.validation_plan else []
    lines = [
        "Controlled Tool Loop:",
        f"- Task: {result.task}",
        f"- Status: {result.status}",
        f"- Stop reason: {result.stop_reason}",
        "- Runtime counters:",
        f"  - tool calls: {counters['tool_calls']}",
        f"  - shell commands: {counters['shell_commands']}",
        f"  - patch candidates: {counters['patch_candidates']}",
        f"- Pending approvals: {len(result.pending_approvals)}",
        "- Validation plan:",
    ]
    lines.extend(f"  - {command}" for command in commands) if commands else lines.append("  - None")
    if result.validation_staging is not None:
        lines.extend(
            [
                "- Validation staging:",
                f"  - status: {result.validation_staging.status}",
                f"  - checkpoint revision: {result.validation_staging.checkpoint_revision if result.validation_staging.checkpoint_revision is not None else 'none'}",
            ]
        )
    if result.warnings:
        lines.append("- Warnings:")
        lines.extend(f"  - {warning}" for warning in result.warnings)
    return "\n".join(lines).strip()


def controlled_loop_result_to_block(result: ControlledToolLoopResult) -> Any:
    """Build a controlled_tool_loop timeline block without modifying timeline contracts.

    The block is generated in coding to avoid runtime importing coding. It summarizes bounded loop
    status for Web/TUI while preserving approval, guardrail, and scope stop semantics.
    """

    from pp_agent.observability.timeline import TimelineBlock, to_jsonable

    return TimelineBlock(
        id="controlled-tool-loop",
        run_id=None,
        type="controlled_tool_loop",
        status=_timeline_status(result.status),
        title=_block_title(result.status),
        content=result.summary_text or controlled_loop_result_to_summary(result),
        details=to_jsonable(_result_details(result)),
        children=[],
        artifact_ids=[item.get("token", "") for item in result.pending_approvals if item.get("token")],
    )


def _attach_runtime_execution_context(runtime: Any, context: RuntimeExecutionContext) -> None:
    setattr(runtime, "runtime_execution_context", context)
    registry = getattr(runtime, "tool_registry", None)
    setter = getattr(registry, "set_runtime_execution_context", None)
    if callable(setter):
        setter(context)
    attach = getattr(runtime, "_attach_runtime_context_to_tool_registry", None)
    if callable(attach):
        attach()


def _install_scoped_instruction_observer(runtime: Any, state: ScopedInstructionActivationState | None) -> dict[str, list[Any]] | None:
    if state is None:
        return None
    hooks = getattr(runtime, "runtime_hooks", None)
    snapshot = getattr(hooks, "snapshot", None)
    if hooks is None or not callable(snapshot) or not hasattr(hooks, "after_tool_call_hooks"):
        return None
    hooks_snapshot = snapshot()

    def observe_read(_agent_state: Any, call: Any, result: Any) -> AfterToolCallDecision:
        state.observe_read_result(tool_name=str(getattr(call, "name", "")), result=result)
        return AfterToolCallDecision(continue_loop=True)

    hooks.after_tool_call_hooks.append(observe_read)
    return hooks_snapshot


def _restore_runtime_hooks(runtime: Any, snapshot: dict[str, list[Any]] | None) -> None:
    if snapshot is None:
        return
    hooks = getattr(runtime, "runtime_hooks", None)
    restore = getattr(hooks, "restore", None)
    if callable(restore):
        restore(snapshot)


def _install_scoped_instruction_context_provider(runtime: Any, state: ScopedInstructionActivationState | None) -> Any:
    if state is None:
        return _SCOPED_CONTEXT_PROVIDER_NOT_INSTALLED
    previous = getattr(runtime, "scoped_instruction_context_provider", _MISSING_SCOPED_CONTEXT_PROVIDER)

    def provider() -> tuple[Any, ...]:
        current = scoped_instruction_records_to_context_items(state.active_records())
        if callable(previous):
            return (*tuple(previous() or ()), *current)
        return current

    setattr(runtime, "scoped_instruction_context_provider", provider)
    return previous


def _restore_scoped_instruction_context_provider(runtime: Any, previous: Any) -> None:
    if previous is _SCOPED_CONTEXT_PROVIDER_NOT_INSTALLED:
        return
    if previous is _MISSING_SCOPED_CONTEXT_PROVIDER:
        try:
            delattr(runtime, "scoped_instruction_context_provider")
        except AttributeError:
            pass
        return
    setattr(runtime, "scoped_instruction_context_provider", previous)


def _runtime_execution_context_from_runtime(runtime: Any, *, fallback: RuntimeExecutionContext) -> RuntimeExecutionContext:
    registry = getattr(runtime, "tool_registry", None)
    getter = getattr(registry, "runtime_execution_context", None)
    if callable(getter):
        current = getter()
        if current is not None:
            setattr(runtime, "runtime_execution_context", current)
            return current
    return getattr(runtime, "runtime_execution_context", None) or fallback


def _run_runtime_turn(runtime: Any, task: str, *, first_turn: bool) -> list[Any]:
    method = getattr(runtime, "prompt", None) if first_turn else getattr(runtime, "continue_", None)
    if not callable(method):
        return []
    result = method(task) if first_turn else method()
    return list(result or [])


def _stop_decision(events: list[Any], pending: list[dict[str, Any]], options: ControlledLoopOptions) -> tuple[str, str] | None:
    if options.stop_on_guardrail_block and _events_contain_detail(events, "runtime_guardrail_blocked"):
        return "guardrail_blocked", "guardrail_limit"
    if options.stop_on_scope_block and _events_contain_detail(events, "scope_blocked"):
        return "scope_blocked", "scope_blocked"
    if options.stop_on_approval and pending:
        return "awaiting_approval", "approval_required"
    return None


def _maybe_stage_initial_validation(
    *,
    status: str,
    pending_approvals: list[dict[str, Any]],
    options: ControlledLoopOptions,
    workspace: Path | None,
    workflow_id: str,
    runtime: Any,
    validation_plan: ValidationPlan | None,
    checkpoint_store: CodingWorkflowCheckpointStore | None,
    expected_revision: int | None,
) -> InitialValidationStagingResult | None:
    if options.dry_run or status != "completed" or pending_approvals or workspace is None or validation_plan is None:
        return None
    session_id = _string_or_none(getattr(runtime, "session_id", None))
    registry = getattr(runtime, "tool_registry", None)
    if session_id is None or registry is None:
        return None
    return stage_initial_validation_workflow(
        workspace=workspace,
        workflow_id=workflow_id,
        session_id=session_id,
        validation_plan=validation_plan,
        registry=registry,
        checkpoint_store=checkpoint_store,
        expected_revision=expected_revision,
    )


def _events_contain_detail(events: list[Any], key: str) -> bool:
    for event in events:
        details = _as_mapping(getattr(event, "details", None) if not isinstance(event, dict) else event.get("details"))
        if _contains_key(details, key):
            return True
    return False


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        if bool(value.get(key)):
            return True
        return any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


def _pending_store(runtime: Any) -> Any:
    registry = getattr(runtime, "tool_registry", None)
    if registry is not None:
        pending_store = getattr(registry, "pending_store", None)
        if callable(pending_store):
            try:
                return pending_store()
            except Exception:  # noqa: BLE001
                return None
    pending_store = getattr(runtime, "_pending_action_store", None)
    if callable(pending_store):
        try:
            return pending_store()
        except Exception:  # noqa: BLE001
            return None
    return None


def _pending_summary(item: dict[str, Any]) -> dict[str, Any]:
    details = _as_mapping(item.get("details"))
    effect = _as_mapping(item.get("effect"))
    analysis = _as_mapping(effect.get("analysis"))
    title = _string_or_none(analysis.get("summary") or effect.get("summary") or details.get("patch_summary") or details.get("summary"))
    return {
        "token": str(item.get("token") or ""),
        "action_type": str(item.get("action_type") or ""),
        "tool_name": _string_or_none(effect.get("tool_name") or details.get("tool_name") or item.get("tool_name")),
        "title": title,
        "summary": title,
        "changed_files": _changed_files(details),
        "command": _string_or_none(item.get("command") or details.get("command")),
        "scope_check": details.get("scope_check") if isinstance(details.get("scope_check"), dict) else None,
    }


def _changed_files(details: dict[str, Any]) -> list[str]:
    files = details.get("changed_files")
    if not isinstance(files, list):
        return []
    result: list[str] = []
    for item in files:
        path = str(item.get("path") or "").strip() if isinstance(item, dict) else str(item or "").strip()
        if path:
            result.append(path)
    return result


def _is_active_pending(item: dict[str, Any]) -> bool:
    expires_at = item.get("expires_at")
    if isinstance(expires_at, (int, float)) and expires_at > 0 and time.time() > float(expires_at):
        return False
    lifecycle = _as_mapping(item.get("lifecycle"))
    return str(lifecycle.get("state") or "staged_not_granted") in {"staged_not_granted", "grant_attached"}


def _result_details(result: ControlledToolLoopResult) -> dict[str, Any]:
    return {
        "task": result.task,
        "status": result.status,
        "stop_reason": result.stop_reason,
        "session_id": result.session.id,
        "runtime_execution_context": runtime_execution_context_to_dict(result.runtime_execution_context),
        "pending_approvals_count": len(result.pending_approvals),
        "pending_approvals": list(result.pending_approvals),
        "validation_commands": [command.command for command in result.validation_plan.commands] if result.validation_plan else [],
        "validation_staging": _validation_staging_details(result.validation_staging),
        "scoped_instruction_activation": result.scoped_instruction_activation_state.summary() if result.scoped_instruction_activation_state is not None else None,
        "warnings": list(result.warnings),
    }


def _validation_staging_details(result: InitialValidationStagingResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    ref = result.pending_action_ref
    selection = result.selection
    return {
        "status": result.status,
        "workflow_id": result.workflow_id,
        "session_id": result.session_id,
        "checkpoint_revision": result.checkpoint_revision,
        "action_id": ref.action_id if ref is not None else None,
        "action_role": ref.role.value if ref is not None else None,
        "action_type": ref.action_type if ref is not None else None,
        "selected": bool(selection.selected) if selection is not None else False,
        "selected_command_index": selection.command_index if selection is not None else None,
        "selected_command_id": selection.command_id if selection is not None else None,
        "reason": result.reason,
    }


def _workspace_from_runtime(runtime: Any) -> Path | None:
    registry = getattr(runtime, "tool_registry", None)
    workspace = getattr(registry, "workspace", None)
    return Path(workspace) if workspace is not None else None


def _timeline_status(status: str) -> str:
    if status == "awaiting_approval":
        return "waiting_approval"
    if status in {"guardrail_blocked", "scope_blocked", "failed"}:
        return "failed"
    if status in {"prepared", "running"}:
        return "running"
    return "succeeded"


def _block_title(status: str) -> str:
    if status == "awaiting_approval":
        return "Controlled execution paused for approval"
    if status == "guardrail_blocked":
        return "Controlled execution stopped by guardrail"
    if status == "scope_blocked":
        return "Controlled execution stopped by scope"
    if status == "failed":
        return "Controlled execution failed"
    return "Controlled tool loop completed"


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="python")
        return dumped if isinstance(dumped, dict) else {}
    return dict(getattr(value, "__dict__", {}) or {})


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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
