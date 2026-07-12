from __future__ import annotations

import json
import subprocess

import pytest

from pp_agent.coding import (
    ValidationCommand,
    ValidationPlan,
    select_primary_pytest_validation_command,
    validation_observation_from_result_details,
    validation_outcome_from_observation,
)


def _plan(*commands: str) -> ValidationPlan:
    return ValidationPlan(commands=[ValidationCommand(command=command, reason=f"reason:{index}") for index, command in enumerate(commands)])


def test_selects_one_eligible_pytest_command_deterministically() -> None:
    selection = select_primary_pytest_validation_command(_plan("python -m pytest tests/coding -q"))

    assert selection.selected is True
    assert selection.command == "python -m pytest tests/coding -q"
    assert selection.normalized_command == "python -m pytest tests/coding -q"
    assert selection.target == "tests/coding"
    assert selection.command_index == 0
    assert selection.command_id == "validation-command:python -m pytest tests/coding -q"


def test_multiple_commands_use_existing_plan_order_only() -> None:
    selection = select_primary_pytest_validation_command(
        _plan(
            "cd web && npm test",
            "python -m pytest tests/runtime -q",
            "python -m pytest tests/coding -q",
        )
    )

    assert selection.command == "python -m pytest tests/runtime -q"
    assert selection.command_index == 1


def test_no_eligible_pytest_command_returns_explicit_result() -> None:
    selection = select_primary_pytest_validation_command(_plan("cd web && npm test", "python -m pytest -q"))

    assert selection.selected is False
    assert selection.status == "no_eligible_validation"
    assert selection.command is None
    assert selection.command_id is None


@pytest.mark.parametrize(
    "command",
    [
        "npm test",
        "python -m unittest tests/coding",
        "python -m pytest tests/coding::test_case -q",
        "python -m pytest ../tests -q",
        "python -m pytest C:/repo/tests -q",
        "python -m pytest tests/coding;Remove-Item -Recurse . -q",
    ],
)
def test_unsupported_or_unsafe_command_family_is_not_selected(command: str) -> None:
    selection = select_primary_pytest_validation_command(_plan(command))

    assert selection.status == "no_eligible_validation"


def test_stable_repeated_selection() -> None:
    plan = _plan("pytest tests/tools -q", "python3 -m pytest tests/coding -q")

    first = select_primary_pytest_validation_command(plan)
    second = select_primary_pytest_validation_command(plan)

    assert first.to_dict() == second.to_dict()


def test_selection_performs_no_process_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_run(*_args, **_kwargs):  # pragma: no cover - should never run
        raise AssertionError("selection must not execute commands")

    monkeypatch.setattr(subprocess, "run", fail_run)

    selection = select_primary_pytest_validation_command(_plan("python -m pytest tests/coding -q"))

    assert selection.selected is True


def test_observation_for_executed_pass_is_bounded_and_json_safe() -> None:
    selection = select_primary_pytest_validation_command(_plan("python -m pytest tests/coding -q"))
    observation = validation_observation_from_result_details(
        selection,
        {
            "exit_code": 0,
            "stdout": "1 passed",
            "stderr": "",
            "stdout_chars": 8,
            "stderr_chars": 0,
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timed_out": False,
            "backend": "fake",
        },
    )

    payload = observation.to_dict()
    assert payload["execution_status"] == "executed"
    assert payload["validation_status"] == "passed"
    assert payload["repair_eligible"] is False
    assert payload["stdout"] == "1 passed"
    json.dumps(payload, sort_keys=True)


def test_nonzero_pytest_result_is_conservative_not_repair_eligible() -> None:
    selection = select_primary_pytest_validation_command(_plan("python -m pytest tests/coding -q"))
    observation = validation_observation_from_result_details(
        selection,
        {
            "returncode": 1,
            "stdout": "bounded failure output",
            "stderr": "",
            "stdout_chars": 22,
            "stderr_chars": 0,
            "timed_out": False,
        },
    )

    assert observation.execution_status == "executed"
    assert observation.validation_status == "validation_nonzero"
    assert observation.failure_kind == "validation_nonzero"
    assert observation.repair_eligible is False


def test_execution_error_is_blocked_not_test_failure() -> None:
    selection = select_primary_pytest_validation_command(_plan("python -m pytest tests/coding -q"))
    observation = validation_observation_from_result_details(
        selection,
        {"failure_kind": "execution_failed", "stderr": "could not start", "stderr_chars": 15},
        execution_status="blocked",
    )

    assert observation.validation_status == "blocked"
    assert observation.execution_status == "blocked"
    assert observation.repair_eligible is False


def test_timeout_is_blocked_not_repair_eligible() -> None:
    selection = select_primary_pytest_validation_command(_plan("python -m pytest tests/coding -q"))
    observation = validation_observation_from_result_details(
        selection,
        {"returncode": 0, "timed_out": True, "stdout": "partial", "stdout_chars": 7},
    )

    assert observation.validation_status == "blocked"
    assert observation.failure_kind == "timeout"
    assert observation.repair_eligible is False


def test_approval_pending_representation_does_not_execute_approval() -> None:
    selection = select_primary_pytest_validation_command(_plan("python -m pytest tests/coding -q"))
    observation = validation_observation_from_result_details(
        selection,
        None,
        execution_status="not_executed",
        validation_status="approval_pending",
        failure_kind="approval_pending",
    )

    assert observation.execution_status == "not_executed"
    assert observation.validation_status == "approval_pending"
    assert observation.repair_eligible is False


def test_truncated_output_flags_are_preserved_without_expansion() -> None:
    selection = select_primary_pytest_validation_command(_plan("python -m pytest tests/coding -q"))
    observation = validation_observation_from_result_details(
        selection,
        {
            "exit_code": 1,
            "stdout": "x" * 10,
            "stderr": "e" * 5,
            "stdout_chars": 9000,
            "stderr_chars": 8001,
            "stdout_truncated": True,
            "stderr_truncated": True,
            "timed_out": False,
        },
    )

    assert observation.stdout == "x" * 10
    assert observation.stderr == "e" * 5
    assert observation.stdout_chars == 9000
    assert observation.stderr_chars == 8001
    assert observation.stdout_truncated is True
    assert observation.stderr_truncated is True


@pytest.mark.parametrize("status", ["not_run", "approval_pending", "passed", "failed", "blocked"])
def test_validation_outcome_statuses_are_serializable(status: str) -> None:
    outcome = validation_outcome_from_observation(None, final_status=status)  # type: ignore[arg-type]

    payload = outcome.to_dict()
    assert payload["final_status"] == status
    assert payload["repair_attempted"] is False
    assert payload["revalidation_attempted"] is False
    json.dumps(payload, sort_keys=True)


def test_outcome_does_not_mutate_validation_plan() -> None:
    plan = _plan("python -m pytest tests/coding -q")
    before = [command.command for command in plan.commands]
    selection = select_primary_pytest_validation_command(plan)
    observation = validation_observation_from_result_details(selection, {"exit_code": 0, "stdout": "", "stderr": ""})

    validation_outcome_from_observation(observation)

    assert [command.command for command in plan.commands] == before


def test_selection_normalization_accepts_supported_pytest_forms() -> None:
    assert select_primary_pytest_validation_command(_plan("pytest tests/coding -q")).normalized_command == "pytest tests/coding -q"
    assert select_primary_pytest_validation_command(_plan("python3 -m pytest tests/coding -q")).normalized_command == "python3 -m pytest tests/coding -q"
