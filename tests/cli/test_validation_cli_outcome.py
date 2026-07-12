from __future__ import annotations

import json

import pytest

from pp_agent.cli.commands import coding as coding_cli
from pp_agent.coding import (
    ControlledToolLoopResult,
    ValidationCommand,
    ValidationCycleResult,
    ValidationOutcome,
    ValidationPlan,
    ValidationRepairCycleState,
    select_primary_pytest_validation_command,
    validation_observation_from_result_details,
    validation_outcome_from_observation,
)
from pp_agent.coding.pytest_provenance import PytestProvenanceVerification
from pp_agent.runtime.execution_context import (
    RuntimeExecutionContext,
    RuntimeExecutionCounters,
    RuntimeExecutionGuardrails,
)


def _selection():
    return select_primary_pytest_validation_command(
        ValidationPlan(commands=[ValidationCommand(command="python -m pytest tests/coding -q")])
    )


def _outcome(
    *,
    final_status: str,
    exit_code: int | None = None,
    provenance: PytestProvenanceVerification | None = None,
    execution_status: str = "executed",
    validation_status: str | None = None,
    repair_attempted: bool = False,
    revalidation_attempted: bool = False,
    stdout: str = "",
) -> ValidationOutcome:
    observation = validation_observation_from_result_details(
        _selection(),
        {
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": "err",
            "stdout_chars": len(stdout),
            "stderr_chars": 3,
            "stdout_truncated": len(stdout) > 10,
            "stderr_truncated": False,
        },
        execution_status=execution_status,  # type: ignore[arg-type]
        validation_status=validation_status,  # type: ignore[arg-type]
        pytest_provenance=provenance,
    )
    return validation_outcome_from_observation(
        observation,
        final_status=final_status,  # type: ignore[arg-type]
        repair_attempted=repair_attempted,
        revalidation_attempted=revalidation_attempted,
    )


def _trusted_tests_failed() -> PytestProvenanceVerification:
    return PytestProvenanceVerification(status="valid", category="tests_failed", pytest_exit_status=1)


def test_validation_outcome_json_for_not_run_and_pending_is_stable() -> None:
    not_run = coding_cli.validation_outcome_to_cli_dict(None)
    pending = _outcome(
        final_status="approval_pending",
        execution_status="not_executed",
        validation_status="approval_pending",
    )

    pending_payload = coding_cli.validation_outcome_to_cli_dict(pending)

    assert not_run["present"] is False
    assert not_run["final_status"] == "not_run"
    assert pending_payload["final_status"] == "approval_pending"
    assert pending_payload["diagnostics"]["execution_status"] == "not_executed"
    assert "awaiting approval" in pending_payload["explanation"]
    json.dumps(pending_payload, sort_keys=True)


@pytest.mark.parametrize(
    "category, expected",
    [
        ("internal_error", "not a genuine tests_failed"),
        ("usage_error", "not a genuine tests_failed"),
        ("no_tests_collected", "not a genuine tests_failed"),
        ("interrupted", "not a genuine tests_failed"),
    ],
)
def test_validation_outcome_explainability_does_not_treat_infra_categories_as_test_failure(category: str, expected: str) -> None:
    outcome = _outcome(
        final_status="validation_nonzero",
        exit_code={"internal_error": 3, "usage_error": 4, "no_tests_collected": 5, "interrupted": 2}[category],
        provenance=PytestProvenanceVerification(status="valid", category=category, pytest_exit_status=3),  # type: ignore[arg-type]
        stdout="FAILED appears in stdout but is ignored",
    )

    text = coding_cli.explain_validation_outcome(outcome)

    assert expected in text
    assert "Trusted pytest provenance reported tests_failed" not in text


def test_validation_outcome_json_redacts_sensitive_provenance_and_unbounded_output() -> None:
    outcome = _outcome(
        final_status="failed",
        exit_code=1,
        provenance=_trusted_tests_failed(),
        stdout="x" * 9000,
    )

    payload = coding_cli.validation_outcome_to_cli_dict(outcome)
    encoded = json.dumps(payload, ensure_ascii=False)

    assert payload["diagnostics"]["pytest_completion_category"] == "tests_failed"
    assert payload["diagnostics"]["repair_eligible"] is True
    assert payload["diagnostics"]["stdout_truncated"] is True
    assert "nonce" not in encoded.lower()
    assert "validation-provenance" not in encoded
    assert "approval token" not in encoded.lower()
    assert "x" * 1000 not in encoded


def test_validation_human_output_distinguishes_repaired_and_passed() -> None:
    outcome = _outcome(
        final_status="passed",
        exit_code=0,
        repair_attempted=True,
        revalidation_attempted=True,
    )

    text = coding_cli.format_validation_outcome(outcome)

    assert "Validation Outcome:" in text
    assert "Final status: passed" in text
    assert "Repair attempted: true" in text
    assert "Re-validation attempted: true" in text
    assert "Repair was attempted and re-validation passed" in text


def test_validation_human_output_does_not_leak_sensitive_fields() -> None:
    outcome = _outcome(final_status="failed", exit_code=1, provenance=_trusted_tests_failed())

    text = coding_cli.format_validation_outcome(outcome)

    assert "tests_failed" in text
    assert "nonce" not in text.lower()
    assert ".pp-agent" not in text
    assert "approval token" not in text.lower()


def test_controlled_loop_serializer_exposes_optional_validation_outcome_additively(tmp_path) -> None:
    result = ControlledToolLoopResult(
        task="task",
        status="completed",
        stop_reason="completed",
        session=type("Session", (), {"id": "exec", "timeline_blocks": [], "warnings": []})(),
        runtime_execution_context=RuntimeExecutionContext(
            session_id="exec",
            status="prepared",
            phase="prepared",
            write_scope=None,
            guardrails=RuntimeExecutionGuardrails(
                max_tool_calls=0,
                max_shell_commands=0,
                max_patch_candidates=0,
                stop_on_approval=True,
                stop_on_scope_block=True,
                stop_on_test_failure=True,
            ),
            counters=RuntimeExecutionCounters(),
        ),
        validation_plan=ValidationPlan(commands=[]),
    )
    result.validation_outcome = _outcome(final_status="failed", exit_code=1, provenance=_trusted_tests_failed())

    payload = coding_cli.controlled_loop_result_to_cli_dict(result)

    assert payload["validation_outcome"]["present"] is True
    assert payload["validation_outcome"]["final_status"] == "failed"
    assert payload["validation_repair"]["present"] is False


def test_validation_repair_state_json_and_human_summary_are_redacted() -> None:
    initial_outcome = _outcome(final_status="failed", exit_code=1, provenance=_trusted_tests_failed())
    initial_result = ValidationCycleResult(
        status="executed",
        selection=_selection(),
        outcome=initial_outcome,
        observation=initial_outcome.observation,
    )
    state = ValidationRepairCycleState(
        selection=_selection(),
        initial_result=initial_result,
        repair_attempted=True,
        revalidation_attempted=False,
        final_outcome=validation_outcome_from_observation(
            initial_outcome.observation,
            final_status="approval_pending",  # type: ignore[arg-type]
            repair_attempted=True,
            revalidation_attempted=False,
        ),
        status="revalidation_pending",
        validation_executions=1,
    )

    payload = coding_cli.validation_repair_state_to_cli_dict(state)
    text = coding_cli.format_validation_repair_state(state)
    encoded = json.dumps(payload)

    assert payload["status"] == "revalidation_pending"
    assert "same-command re-validation is awaiting approval" in payload["explanation"]
    assert "Validation Repair:" in text
    assert "nonce" not in encoded.lower()
    assert "validation-provenance" not in encoded
    assert "approval token" not in text.lower()
