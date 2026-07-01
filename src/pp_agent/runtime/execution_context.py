from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from pp_agent.runtime.scope_contract import WriteScope, write_scope_from_dict, write_scope_to_dict


@dataclass(frozen=True)
class RuntimeExecutionGuardrails:
    """Runtime-consumable execution limits that do not import coding contracts.

    This model lives in runtime so ToolRegistry, tools, and future runtime loops can consume
    execution constraints without depending on `pp_agent.coding`. It only carries limits; it does
    not execute tools, request approvals, or change sandbox behavior.
    """

    max_tool_calls: int
    max_shell_commands: int
    max_patch_candidates: int
    stop_on_approval: bool
    stop_on_scope_block: bool
    stop_on_test_failure: bool


@dataclass(frozen=True)
class RuntimeExecutionCounters:
    """Runtime-side counters for guardrail checks without a tools -> coding dependency.

    Counters describe observed runtime activity for a neutral execution context. They do not start
    execution, mutate tool state, or bypass approval and sandbox layers.
    """

    tool_calls: int = 0
    shell_commands: int = 0
    patch_candidates: int = 0


@dataclass(frozen=True)
class RuntimeExecutionContext:
    """A neutral runtime/tools context adapted from a coding execution session.

    The context is intentionally smaller than coding intelligence models so runtime and tools can
    consume session id, phase, WriteScope, guardrails, and counters without importing coding. It
    carries execution constraints only and does not run tools, edit files, or create pending actions.
    """

    session_id: str
    status: str
    phase: str
    write_scope: WriteScope | None
    guardrails: RuntimeExecutionGuardrails
    counters: RuntimeExecutionCounters = field(default_factory=RuntimeExecutionCounters)
    predicted_impact_not_actual: bool = True
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RuntimeGuardrailCheckResult:
    """Result of checking a runtime action against RuntimeExecutionGuardrails.

    `allowed=True` means the action was checked and is below its limit, `False` means it was checked
    and blocked, and `None` means no RuntimeExecutionContext was provided so legacy flow skipped the
    check. This result does not execute or approve anything.
    """

    allowed: bool | None
    action: str
    reason: str
    matched_limit: str | None = None
    current_count: int | None = None
    max_count: int | None = None
    warnings: list[str] = field(default_factory=list)


def runtime_guardrails_to_dict(guardrails: RuntimeExecutionGuardrails) -> dict[str, Any]:
    """Serialize runtime guardrails for trace-safe context without importing coding.

    The payload is JSON-friendly and only carries constraints for future runtime/tool consumers; it
    does not perform a guardrail check or execute tools.
    """

    return {
        "max_tool_calls": guardrails.max_tool_calls,
        "max_shell_commands": guardrails.max_shell_commands,
        "max_patch_candidates": guardrails.max_patch_candidates,
        "stop_on_approval": guardrails.stop_on_approval,
        "stop_on_scope_block": guardrails.stop_on_scope_block,
        "stop_on_test_failure": guardrails.stop_on_test_failure,
    }


def runtime_counters_to_dict(counters: RuntimeExecutionCounters) -> dict[str, Any]:
    """Serialize runtime counters used by guardrail helpers.

    Counters remain in runtime so tools can later update/check limits without a tools -> coding
    dependency. This helper only serializes state.
    """

    return {
        "tool_calls": counters.tool_calls,
        "shell_commands": counters.shell_commands,
        "patch_candidates": counters.patch_candidates,
    }


def runtime_execution_context_to_dict(context: RuntimeExecutionContext | None) -> dict[str, Any] | None:
    """Serialize a RuntimeExecutionContext, returning None for skipped legacy flows.

    The context is the runtime bridge, not the full coding intelligence model. It carries WriteScope
    and guardrails without executing tools or changing sandbox/approval semantics.
    """

    if context is None:
        return None
    return {
        "session_id": context.session_id,
        "status": context.status,
        "phase": context.phase,
        "write_scope": write_scope_to_dict(context.write_scope) if context.write_scope is not None else None,
        "guardrails": runtime_guardrails_to_dict(context.guardrails),
        "counters": runtime_counters_to_dict(context.counters),
        "predicted_impact_not_actual": context.predicted_impact_not_actual,
        "warnings": list(context.warnings),
    }


def runtime_execution_context_from_dict(data: Mapping[str, Any] | None) -> RuntimeExecutionContext | None:
    """Deserialize a RuntimeExecutionContext from a JSON-friendly payload.

    Returning None preserves legacy flows with no runtime context. The deserialized object remains a
    neutral runtime contract and does not recreate coding-layer objects.
    """

    if data is None or not isinstance(data, Mapping):
        return None
    return RuntimeExecutionContext(
        session_id=str(data.get("session_id") or ""),
        status=str(data.get("status") or ""),
        phase=str(data.get("phase") or ""),
        write_scope=write_scope_from_dict(data.get("write_scope")),
        guardrails=_runtime_guardrails_from_dict(data.get("guardrails")),
        counters=_runtime_counters_from_dict(data.get("counters")),
        predicted_impact_not_actual=bool(data.get("predicted_impact_not_actual", True)),
        warnings=_list_of_strings(data.get("warnings")),
    )


def runtime_guardrail_check_to_dict(result: RuntimeGuardrailCheckResult) -> dict[str, Any]:
    """Serialize a runtime guardrail check result with allowed True/False/None semantics.

    `None` means the check was skipped because no runtime execution context was present; the helper
    only reports the decision and does not execute or approve tools.
    """

    return {
        "allowed": result.allowed,
        "action": result.action,
        "reason": result.reason,
        "matched_limit": result.matched_limit,
        "current_count": result.current_count,
        "max_count": result.max_count,
        "warnings": list(result.warnings),
    }


def check_runtime_guardrails(context: RuntimeExecutionContext | None, action: str) -> RuntimeGuardrailCheckResult:
    """Check a runtime action against guardrails without executing the action.

    This helper lives in runtime so future tools/runtime loops can check limits without importing
    coding. `allowed=True` is below limit, `False` is blocked or unknown action, and `None` means no
    context was provided so legacy flow skipped the check.
    """

    normalized = str(action or "").strip()
    if context is None:
        return RuntimeGuardrailCheckResult(
            allowed=None,
            action=normalized,
            reason="No runtime execution context was provided; guardrail check was skipped.",
            warnings=["Runtime guardrail check skipped."],
        )
    limit = _limit_for_action(context, normalized)
    if limit is None:
        return RuntimeGuardrailCheckResult(
            allowed=False,
            action=normalized,
            reason=f"Unknown runtime guardrail action: {normalized or '<empty>'}.",
        )
    matched_limit, current_count, max_count = limit
    if current_count >= max_count:
        return RuntimeGuardrailCheckResult(
            allowed=False,
            action=normalized,
            reason=f"Runtime guardrail limit reached for {normalized}.",
            matched_limit=matched_limit,
            current_count=current_count,
            max_count=max_count,
        )
    return RuntimeGuardrailCheckResult(
        allowed=True,
        action=normalized,
        reason=f"Runtime guardrail allows {normalized}.",
        matched_limit=matched_limit,
        current_count=current_count,
        max_count=max_count,
    )


def increment_runtime_counter(context: RuntimeExecutionContext, action: str) -> RuntimeExecutionContext:
    """Return a new RuntimeExecutionContext with the selected counter incremented.

    The context is frozen so updates are explicit and runtime-local. This helper does not execute a
    tool; it only records that a future runtime loop observed a tool_call, shell_command, or
    patch_candidate action without importing coding.
    """

    normalized = str(action or "").strip()
    counters = context.counters
    if normalized == "tool_call":
        updated = replace(counters, tool_calls=counters.tool_calls + 1)
    elif normalized == "shell_command":
        updated = replace(counters, shell_commands=counters.shell_commands + 1)
    elif normalized == "patch_candidate":
        updated = replace(counters, patch_candidates=counters.patch_candidates + 1)
    else:
        raise ValueError(f"Unknown runtime counter action: {normalized or '<empty>'}.")
    return replace(context, counters=updated)


def attach_runtime_context_to_patch_candidate_args(args: dict, context: RuntimeExecutionContext | None) -> dict:
    """Attach runtime context metadata and WriteScope to patch candidate args.

    This bridge lets patch candidate creation paths consume runtime context instead of coding
    session objects. It does not mutate input, call `apply_patch_candidate`, create pending actions,
    or change approval/sandbox semantics. A conflicting existing write_scope raises ValueError.
    """

    copied = dict(args or {})
    if context is None:
        return copied
    if context.write_scope is not None:
        payload = write_scope_to_dict(context.write_scope)
        existing = copied.get("write_scope")
        if existing is not None and existing != payload:
            raise ValueError("Patch candidate arguments already contain a different write_scope.")
        copied["write_scope"] = payload
    metadata = {
        "session_id": context.session_id,
        "phase": context.phase,
        "predicted_impact_not_actual": context.predicted_impact_not_actual,
    }
    existing_context = copied.get("execution_context")
    if existing_context is not None and existing_context != metadata:
        raise ValueError("Patch candidate arguments already contain a different execution_context.")
    copied["execution_context"] = metadata
    return copied


def _runtime_guardrails_from_dict(data: Any) -> RuntimeExecutionGuardrails:
    mapping = data if isinstance(data, Mapping) else {}
    return RuntimeExecutionGuardrails(
        max_tool_calls=_int_or_default(mapping.get("max_tool_calls"), 0),
        max_shell_commands=_int_or_default(mapping.get("max_shell_commands"), 0),
        max_patch_candidates=_int_or_default(mapping.get("max_patch_candidates"), 0),
        stop_on_approval=bool(mapping.get("stop_on_approval")),
        stop_on_scope_block=bool(mapping.get("stop_on_scope_block")),
        stop_on_test_failure=bool(mapping.get("stop_on_test_failure")),
    )


def _runtime_counters_from_dict(data: Any) -> RuntimeExecutionCounters:
    mapping = data if isinstance(data, Mapping) else {}
    return RuntimeExecutionCounters(
        tool_calls=_int_or_default(mapping.get("tool_calls"), 0),
        shell_commands=_int_or_default(mapping.get("shell_commands"), 0),
        patch_candidates=_int_or_default(mapping.get("patch_candidates"), 0),
    )


def _limit_for_action(context: RuntimeExecutionContext, action: str) -> tuple[str, int, int] | None:
    if action == "tool_call":
        return "max_tool_calls", context.counters.tool_calls, context.guardrails.max_tool_calls
    if action == "shell_command":
        return "max_shell_commands", context.counters.shell_commands, context.guardrails.max_shell_commands
    if action == "patch_candidate":
        return "max_patch_candidates", context.counters.patch_candidates, context.guardrails.max_patch_candidates
    return None


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _list_of_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return []
