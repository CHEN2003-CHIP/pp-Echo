from __future__ import annotations

import json

from pp_agent.cli.commands.coding import validation_outcome_to_cli_dict
from pp_agent.coding import (
    MAX_REPAIR_CONTINUATIONS,
    MAX_REVALIDATION_ATTEMPTS,
    MAX_VALIDATION_EXECUTIONS,
    ValidationCommand,
    ValidationPlan,
    select_primary_pytest_validation_command,
    validation_observation_from_result_details,
    validation_outcome_from_observation,
    validation_repair_trigger_allowed,
)
from pp_agent.coding.pytest_provenance import PytestProvenanceVerification
from pp_agent.coding.validation_execution import ValidationCycleResult


def test_mission_07_release_gate_core_invariants_are_exposed() -> None:
    selection = select_primary_pytest_validation_command(
        ValidationPlan(
            commands=[
                ValidationCommand(command="cd web && npm test"),
                ValidationCommand(command="python -m pytest tests/coding -q"),
            ]
        )
    )
    provenance = PytestProvenanceVerification(status="valid", category="tests_failed", pytest_exit_status=1)
    observation = validation_observation_from_result_details(
        selection,
        {"exit_code": 1, "stdout": "FAILED", "stderr": "", "stdout_truncated": False, "stderr_truncated": False},
        pytest_provenance=provenance,
    )
    outcome = validation_outcome_from_observation(observation)
    cycle = ValidationCycleResult(status="executed", selection=selection, outcome=outcome, observation=observation)

    payload = validation_outcome_to_cli_dict(outcome)
    encoded = json.dumps(payload, ensure_ascii=False)

    assert MAX_REPAIR_CONTINUATIONS == 1
    assert MAX_REVALIDATION_ATTEMPTS == 1
    assert MAX_VALIDATION_EXECUTIONS == 2
    assert selection.command_index == 1
    assert selection.normalized_command == "python -m pytest tests/coding -q"
    assert validation_repair_trigger_allowed(cycle) is True
    assert payload["final_status"] == "failed"
    assert payload["diagnostics"]["pytest_completion_category"] == "tests_failed"
    assert "nonce" not in encoded.lower()
    assert "validation-provenance" not in encoded


def test_mission_07_release_gate_rejects_stdout_or_raw_exit_code_as_repair_trigger() -> None:
    selection = select_primary_pytest_validation_command(ValidationPlan(commands=[ValidationCommand(command="python -m pytest tests/coding -q")]))
    observation = validation_observation_from_result_details(
        selection,
        {"exit_code": 1, "stdout": "FAILED", "stderr": ""},
    )
    outcome = validation_outcome_from_observation(observation)
    cycle = ValidationCycleResult(status="executed", selection=selection, outcome=outcome, observation=observation)

    assert observation.validation_status == "validation_nonzero"
    assert observation.repair_eligible is False
    assert validation_repair_trigger_allowed(cycle) is False
