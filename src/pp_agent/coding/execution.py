from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from pp_agent.coding.orchestrator import CodingWorkflow
from pp_agent.coding.scope import task_scope_to_write_scope
from pp_agent.runtime.execution_context import (
    RuntimeExecutionContext,
    RuntimeExecutionCounters,
    RuntimeExecutionGuardrails,
)
from pp_agent.runtime.scope_contract import WriteScope, write_scope_to_dict


@dataclass
class ExecutionGuardrails:
    """Guardrails for a future controlled execution session, not an autonomous loop.

    These limits describe how a later runtime integration, CLI/TUI, or Web flow should stop.
    They do not run shell commands, edit files, or bypass sandbox and approval layers.
    """

    max_tool_calls: int
    max_shell_commands: int
    max_patch_candidates: int
    stop_on_approval: bool
    stop_on_scope_block: bool
    stop_on_test_failure: bool


@dataclass
class CodingExecutionEvent:
    """A serializable controlled-execution lifecycle event contract for future runtime loops."""

    type: str
    status: str
    title: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class CodingExecutionSession:
    """A prepared controlled coding execution session.

    The session carries CodingWorkflow, guardrails, and WriteScope forward for later runtime
    integration. It does not call an LLM, execute shell, edit files, or apply patches.
    """

    id: str
    workflow: CodingWorkflow
    status: str
    phase: str
    write_scope: WriteScope | None
    guardrails: ExecutionGuardrails
    timeline_blocks: list[Any] = field(default_factory=list)
    context_items: list[dict[str, Any]] = field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary_text: str = ""


def default_execution_guardrails() -> ExecutionGuardrails:
    """Return default controlled-session guardrails without executing any tools."""

    return ExecutionGuardrails(
        max_tool_calls=20,
        max_shell_commands=5,
        max_patch_candidates=3,
        stop_on_approval=True,
        stop_on_scope_block=True,
        stop_on_test_failure=True,
    )


def start_coding_execution_session(
    workflow: CodingWorkflow,
    guardrails: ExecutionGuardrails | None = None,
    session_id: str | None = None,
) -> CodingExecutionSession:
    """Prepare a controlled coding execution session without starting an execution loop.

    The session derives WriteScope from TaskScope and packages workflow timeline/context for later
    runtime, CLI/TUI, or Web integration.
    """

    resolved_guardrails = guardrails or default_execution_guardrails()
    write_scope = task_scope_to_write_scope(workflow.task_scope)
    session = CodingExecutionSession(
        id=session_id or f"coding-exec-{uuid4().hex[:12]}",
        workflow=workflow,
        status="prepared",
        phase="prepared",
        write_scope=write_scope,
        guardrails=resolved_guardrails,
        warnings=list(workflow.warnings),
    )
    session.timeline_blocks = [*workflow.timeline_blocks, execution_session_to_block(session), execution_guardrails_to_block(resolved_guardrails)]
    session.context_items = [*workflow.context_items, coding_execution_session_to_context_item(session)]
    session.summary_text = _render_summary_text(session)
    return session


def execution_guardrails_to_context_item(guardrails: ExecutionGuardrails) -> dict[str, Any]:
    """Convert guardrails into JSON-friendly context without running any tools."""

    return {
        "id": "execution-guardrails",
        "type": "project_context",
        "title": "Execution guardrails",
        "content": _guardrails_summary(guardrails),
        "source_ref": {"source_type": "project_context", "source_id": "execution_guardrails", "metadata": _guardrails_details(guardrails)},
        "priority": 52,
        "metadata": {"context_section": "project_context", "execution_guardrails": _guardrails_details(guardrails)},
    }


def coding_execution_session_to_context_item(session: CodingExecutionSession) -> dict[str, Any]:
    """Convert a prepared execution session into JSON-friendly context for future runtime integration."""

    details = _session_details(session)
    return {
        "id": "coding-execution-session",
        "type": "project_context",
        "title": "Coding execution session",
        "content": session.summary_text or _render_summary_text(session),
        "source_ref": {"source_type": "project_context", "source_id": session.id, "metadata": details},
        "priority": 51,
        "metadata": {"context_section": "project_context", "coding_execution_session": details},
    }


def attach_write_scope_to_patch_candidate_args(args: dict, write_scope: WriteScope | None) -> dict:
    """Attach WriteScope to patch candidate args for later creation paths without mutating input.

    Existing matching write_scope is preserved. A conflicting write_scope raises ValueError so digest
    and approval semantics stay explicit.
    """

    copied = dict(args or {})
    if write_scope is None:
        return copied
    payload = write_scope_to_dict(write_scope)
    existing = copied.get("write_scope")
    if existing is not None and existing != payload:
        raise ValueError("Patch candidate arguments already contain a different write_scope.")
    copied["write_scope"] = payload
    return copied


def coding_session_to_runtime_execution_context(session: CodingExecutionSession) -> RuntimeExecutionContext:
    """Adapt a coding execution session into the neutral runtime execution context.

    Coding owns the full session/workflow contract, while runtime/tools consume only this smaller
    context to avoid tools -> coding dependencies. The adapter carries guardrails, WriteScope,
    counters, and warnings but does not execute tools, edit files, or change approval/sandbox
    semantics.
    """

    return RuntimeExecutionContext(
        session_id=session.id,
        status=session.status,
        phase=session.phase,
        write_scope=session.write_scope,
        guardrails=RuntimeExecutionGuardrails(
            max_tool_calls=session.guardrails.max_tool_calls,
            max_shell_commands=session.guardrails.max_shell_commands,
            max_patch_candidates=session.guardrails.max_patch_candidates,
            stop_on_approval=session.guardrails.stop_on_approval,
            stop_on_scope_block=session.guardrails.stop_on_scope_block,
            stop_on_test_failure=session.guardrails.stop_on_test_failure,
        ),
        counters=RuntimeExecutionCounters(),
        predicted_impact_not_actual=True,
        warnings=list(session.warnings),
    )


def execution_session_to_block(session: CodingExecutionSession):
    """Build an execution_session timeline block without executing shell or applying patches."""

    from pp_agent.observability.timeline import TimelineBlock, to_jsonable

    return TimelineBlock(
        id="coding-execution-session",
        run_id=None,
        type="execution_session",
        status=session.status,
        title="Prepared controlled execution session",
        content=session.summary_text or _render_summary_text(session),
        details=to_jsonable(_session_details(session)),
        children=[],
        artifact_ids=[],
    )


def execution_guardrails_to_block(guardrails: ExecutionGuardrails):
    """Build an execution_guardrails timeline block for Web/TUI preparation displays."""

    from pp_agent.observability.timeline import TimelineBlock, to_jsonable

    return TimelineBlock(
        id="execution-guardrails",
        run_id=None,
        type="execution_guardrails",
        status="succeeded",
        title="Configured execution guardrails",
        content=_guardrails_summary(guardrails),
        details=to_jsonable(_guardrails_details(guardrails)),
        children=[],
        artifact_ids=[],
    )


def _guardrails_details(guardrails: ExecutionGuardrails) -> dict[str, Any]:
    return {
        "max_tool_calls": guardrails.max_tool_calls,
        "max_shell_commands": guardrails.max_shell_commands,
        "max_patch_candidates": guardrails.max_patch_candidates,
        "stop_on_approval": guardrails.stop_on_approval,
        "stop_on_scope_block": guardrails.stop_on_scope_block,
        "stop_on_test_failure": guardrails.stop_on_test_failure,
    }


def _write_scope_summary(scope: WriteScope | None) -> dict[str, Any] | None:
    if scope is None:
        return None
    return {
        "allowed_paths": list(scope.allowed_paths),
        "disallowed_paths": list(scope.disallowed_paths),
        "allow_delete": scope.allow_delete,
        "max_files_changed": scope.max_files_changed,
        "risk_level": scope.risk_level,
        "source": scope.source,
    }


def _session_details(session: CodingExecutionSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "status": session.status,
        "phase": session.phase,
        "guardrails": _guardrails_details(session.guardrails),
        "write_scope": _write_scope_summary(session.write_scope),
        "pending_approvals_count": len(session.pending_approvals),
        "warnings": list(session.warnings),
        "predicted_impact_not_actual": True,
    }


def _guardrails_summary(guardrails: ExecutionGuardrails) -> str:
    return "\n".join(
        [
            "Execution Guardrails:",
            f"- Max tool calls: {guardrails.max_tool_calls}",
            f"- Max shell commands: {guardrails.max_shell_commands}",
            f"- Max patch candidates: {guardrails.max_patch_candidates}",
            f"- Stop on approval: {str(guardrails.stop_on_approval).lower()}",
            f"- Stop on scope block: {str(guardrails.stop_on_scope_block).lower()}",
            f"- Stop on test failure: {str(guardrails.stop_on_test_failure).lower()}",
        ]
    )


def _render_summary_text(session: CodingExecutionSession) -> str:
    scope = session.write_scope
    return "\n".join(
        [
            "Coding Execution Session:",
            f"- Status: {session.status}",
            f"- Phase: {session.phase}",
            "- Guardrails:",
            f"  - max tool calls: {session.guardrails.max_tool_calls}",
            f"  - max shell commands: {session.guardrails.max_shell_commands}",
            f"  - max patch candidates: {session.guardrails.max_patch_candidates}",
            f"  - stop on approval: {str(session.guardrails.stop_on_approval).lower()}",
            "- Write scope:",
            f"  - source: {scope.source if scope is not None else 'none'}",
            f"  - max files changed: {scope.max_files_changed if scope is not None and scope.max_files_changed is not None else 'unlimited'}",
            "- Next: wait for controlled tool execution.",
        ]
    ).strip()
