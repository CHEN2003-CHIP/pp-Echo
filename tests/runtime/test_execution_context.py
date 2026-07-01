from __future__ import annotations

import pytest

from pp_agent.runtime.execution_context import (
    RuntimeExecutionContext,
    RuntimeExecutionCounters,
    RuntimeExecutionGuardrails,
    RuntimeGuardrailCheckResult,
    attach_runtime_context_to_patch_candidate_args,
    check_runtime_guardrails,
    increment_runtime_counter,
    runtime_counters_to_dict,
    runtime_execution_context_from_dict,
    runtime_execution_context_to_dict,
    runtime_guardrail_check_to_dict,
    runtime_guardrails_to_dict,
)
from pp_agent.runtime.scope_contract import WriteScope, write_scope_to_dict


def _guardrails() -> RuntimeExecutionGuardrails:
    return RuntimeExecutionGuardrails(
        max_tool_calls=2,
        max_shell_commands=1,
        max_patch_candidates=1,
        stop_on_approval=True,
        stop_on_scope_block=True,
        stop_on_test_failure=True,
    )


def _context(
    counters: RuntimeExecutionCounters | None = None,
    write_scope: WriteScope | None = None,
) -> RuntimeExecutionContext:
    return RuntimeExecutionContext(
        session_id="exec-1",
        status="prepared",
        phase="prepared",
        write_scope=write_scope,
        guardrails=_guardrails(),
        counters=counters or RuntimeExecutionCounters(),
        predicted_impact_not_actual=True,
        warnings=["predicted impact only"],
    )


def test_runtime_execution_context_serializes_to_dict() -> None:
    scope = WriteScope(allowed_paths=["src/**"], source="task_scope")
    payload = runtime_execution_context_to_dict(_context(write_scope=scope))

    assert payload == {
        "session_id": "exec-1",
        "status": "prepared",
        "phase": "prepared",
        "write_scope": write_scope_to_dict(scope),
        "guardrails": {
            "max_tool_calls": 2,
            "max_shell_commands": 1,
            "max_patch_candidates": 1,
            "stop_on_approval": True,
            "stop_on_scope_block": True,
            "stop_on_test_failure": True,
        },
        "counters": {"tool_calls": 0, "shell_commands": 0, "patch_candidates": 0},
        "predicted_impact_not_actual": True,
        "warnings": ["predicted impact only"],
    }


def test_runtime_execution_context_from_dict_round_trip() -> None:
    context = _context(write_scope=WriteScope(allowed_paths=["src/**"], source="task_scope"))

    assert runtime_execution_context_from_dict(runtime_execution_context_to_dict(context)) == context


def test_check_runtime_guardrails_skips_without_context() -> None:
    result = check_runtime_guardrails(None, "tool_call")

    assert result.allowed is None
    assert result.reason == "No runtime execution context was provided; guardrail check was skipped."


def test_check_runtime_guardrails_allows_below_limit() -> None:
    result = check_runtime_guardrails(_context(RuntimeExecutionCounters(tool_calls=1)), "tool_call")

    assert result.allowed is True
    assert result.matched_limit == "max_tool_calls"
    assert result.current_count == 1
    assert result.max_count == 2


def test_check_runtime_guardrails_blocks_tool_call_limit() -> None:
    result = check_runtime_guardrails(_context(RuntimeExecutionCounters(tool_calls=2)), "tool_call")

    assert result.allowed is False
    assert result.matched_limit == "max_tool_calls"


def test_check_runtime_guardrails_blocks_shell_limit() -> None:
    result = check_runtime_guardrails(_context(RuntimeExecutionCounters(shell_commands=1)), "shell_command")

    assert result.allowed is False
    assert result.matched_limit == "max_shell_commands"


def test_check_runtime_guardrails_blocks_patch_candidate_limit() -> None:
    result = check_runtime_guardrails(_context(RuntimeExecutionCounters(patch_candidates=1)), "patch_candidate")

    assert result.allowed is False
    assert result.matched_limit == "max_patch_candidates"


def test_check_runtime_guardrails_blocks_unknown_action() -> None:
    result = check_runtime_guardrails(_context(), "network")

    assert result.allowed is False
    assert result.reason == "Unknown runtime guardrail action: network."


def test_increment_runtime_counter_tool_call() -> None:
    updated = increment_runtime_counter(_context(), "tool_call")

    assert updated.counters.tool_calls == 1


def test_increment_runtime_counter_shell_command() -> None:
    updated = increment_runtime_counter(_context(), "shell_command")

    assert updated.counters.shell_commands == 1


def test_increment_runtime_counter_patch_candidate() -> None:
    updated = increment_runtime_counter(_context(), "patch_candidate")

    assert updated.counters.patch_candidates == 1


def test_increment_runtime_counter_rejects_unknown_action() -> None:
    with pytest.raises(ValueError, match="Unknown runtime counter action"):
        increment_runtime_counter(_context(), "network")


def test_attach_runtime_context_to_patch_candidate_args_without_context_keeps_args() -> None:
    args = {"patch": "x"}

    assert attach_runtime_context_to_patch_candidate_args(args, None) == args


def test_attach_runtime_context_to_patch_candidate_args_adds_write_scope() -> None:
    scope = WriteScope(allowed_paths=["src/**"], source="task_scope")
    args = attach_runtime_context_to_patch_candidate_args({"patch": "x"}, _context(write_scope=scope))

    assert args["write_scope"] == write_scope_to_dict(scope)


def test_attach_runtime_context_to_patch_candidate_args_adds_session_metadata() -> None:
    args = attach_runtime_context_to_patch_candidate_args({"patch": "x"}, _context())

    assert args["execution_context"] == {
        "session_id": "exec-1",
        "phase": "prepared",
        "predicted_impact_not_actual": True,
    }


def test_attach_runtime_context_to_patch_candidate_args_does_not_mutate_original() -> None:
    original = {"patch": "x"}

    attach_runtime_context_to_patch_candidate_args(original, _context(write_scope=WriteScope(allowed_paths=["src/**"])))

    assert original == {"patch": "x"}


def test_attach_runtime_context_to_patch_candidate_args_rejects_conflicting_write_scope() -> None:
    args = {"write_scope": {"allowed_paths": ["docs/**"]}}

    with pytest.raises(ValueError, match="different write_scope"):
        attach_runtime_context_to_patch_candidate_args(args, _context(write_scope=WriteScope(allowed_paths=["src/**"])))


def test_runtime_guardrail_check_to_dict() -> None:
    result = RuntimeGuardrailCheckResult(False, "tool_call", "blocked", "max_tool_calls", 2, 2, ["limit"])

    assert runtime_guardrail_check_to_dict(result) == {
        "allowed": False,
        "action": "tool_call",
        "reason": "blocked",
        "matched_limit": "max_tool_calls",
        "current_count": 2,
        "max_count": 2,
        "warnings": ["limit"],
    }


def test_runtime_execution_context_public_models_have_docstrings() -> None:
    assert RuntimeExecutionGuardrails.__doc__
    assert RuntimeExecutionCounters.__doc__
    assert RuntimeExecutionContext.__doc__
    assert RuntimeGuardrailCheckResult.__doc__


def test_runtime_execution_context_public_helpers_have_docstrings() -> None:
    assert runtime_guardrails_to_dict.__doc__
    assert runtime_counters_to_dict.__doc__
    assert runtime_execution_context_to_dict.__doc__
    assert runtime_execution_context_from_dict.__doc__
    assert runtime_guardrail_check_to_dict.__doc__
    assert check_runtime_guardrails.__doc__
    assert increment_runtime_counter.__doc__
    assert attach_runtime_context_to_patch_candidate_args.__doc__
