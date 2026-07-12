from __future__ import annotations

import json
from pathlib import Path

import pytest

from pp_agent.coding import (
    ValidationCommand,
    ValidationPlan,
    build_instrumented_validation_command,
    select_primary_pytest_validation_command,
    validation_observation_from_result_details,
    verify_pytest_provenance_attestation,
    write_pytest_provenance_attestation,
)
from pp_agent.coding.pytest_provenance import (
    PYTEST_PROVENANCE_MAX_BYTES,
    PYTEST_PROVENANCE_PLUGIN_ID,
    PYTEST_PROVENANCE_PLUGIN_VERSION,
    PYTEST_PROVENANCE_SCHEMA_VERSION,
    PytestProvenanceRequest,
)


def _selection(command: str = "python -m pytest tests/coding -q"):
    return select_primary_pytest_validation_command(ValidationPlan(commands=[ValidationCommand(command=command)]))


def test_instrumentation_preserves_python_runner_target_and_logical_identity(tmp_path: Path) -> None:
    selection = _selection("python -m pytest tests/coding -q")

    instrumented = build_instrumented_validation_command(selection, workspace=tmp_path)

    assert instrumented.runner == "python"
    assert instrumented.target == "tests/coding"
    assert instrumented.quiet is True
    assert instrumented.logical_command == "python -m pytest tests/coding -q"
    assert instrumented.provenance_request.artifact_relative_path.startswith(".pp-agent/validation-provenance/")
    args = instrumented.to_stage_test_internal_args()
    assert args["runner"] == "python"
    assert args["target"] == "tests/coding"
    assert args["quiet"] is True
    assert args["provenance"]["plugin_id"] == PYTEST_PROVENANCE_PLUGIN_ID  # type: ignore[index]


@pytest.mark.parametrize(
    "command, runner",
    [
        ("pytest tests/coding -q", "pytest"),
        ("python -m pytest tests/coding -q", "python"),
        ("python3 -m pytest tests/coding -q", "python3"),
    ],
)
def test_instrumentation_preserves_supported_pytest_runner(tmp_path: Path, command: str, runner: str) -> None:
    instrumented = build_instrumented_validation_command(_selection(command), workspace=tmp_path)

    assert instrumented.runner == runner
    assert instrumented.target == "tests/coding"


@pytest.mark.parametrize(
    "command",
    [
        "python -m pytest tests/coding --pp-echo-pytest-provenance-file x",
        "python -m pytest tests/coding -p no:pp_agent.coding.pytest_provenance_plugin",
    ],
)
def test_reserved_provenance_arguments_fail_closed(tmp_path: Path, command: str) -> None:
    selection = select_primary_pytest_validation_command(ValidationPlan(commands=[ValidationCommand(command=command)]))

    assert selection.selected is False


@pytest.mark.parametrize(
    "exit_status, category",
    [
        (0, "passed"),
        (1, "tests_failed"),
        (2, "interrupted"),
        (3, "internal_error"),
        (4, "usage_error"),
        (5, "no_tests_collected"),
        (99, "unknown"),
    ],
)
def test_attestation_maps_pytest_exit_statuses(tmp_path: Path, exit_status: int, category: str) -> None:
    request = _request(tmp_path)

    write_pytest_provenance_attestation(
        artifact_path=request.artifact_path,
        nonce=request.nonce,
        logical_command_digest=request.logical_command_digest,
        pytest_exit_status=exit_status,
    )
    verified = verify_pytest_provenance_attestation(request, exit_code=exit_status, timed_out=False)

    assert verified.status == "valid"
    assert verified.category == category
    assert verified.pytest_exit_status == exit_status
    assert request.artifact_path.exists() is False


def test_attestation_schema_is_bounded_and_contains_no_output_or_absolute_paths(tmp_path: Path) -> None:
    request = _request(tmp_path)

    write_pytest_provenance_attestation(
        artifact_path=request.artifact_path,
        nonce=request.nonce,
        logical_command_digest=request.logical_command_digest,
        pytest_exit_status=1,
    )
    payload = json.loads(request.artifact_path.read_text(encoding="utf-8"))

    assert set(payload) == {
        "schema_version",
        "plugin_id",
        "plugin_version",
        "nonce",
        "logical_command_digest",
        "category",
        "pytest_exit_status",
    }
    assert "stdout" not in payload
    assert "stderr" not in payload
    assert str(tmp_path) not in json.dumps(payload)


@pytest.mark.parametrize(
    "payload, failure_kind",
    [
        (None, "artifact_missing"),
        ("", "artifact_malformed"),
        ("{", "artifact_malformed"),
        ({"schema_version": 999}, "artifact_schema_fields"),
        (
            {
                "schema_version": PYTEST_PROVENANCE_SCHEMA_VERSION,
                "plugin_id": "wrong",
                "plugin_version": PYTEST_PROVENANCE_PLUGIN_VERSION,
                "nonce": "nonce",
                "logical_command_digest": "digest",
                "category": "tests_failed",
                "pytest_exit_status": 1,
            },
            "plugin_identity_mismatch",
        ),
        (
            {
                "schema_version": PYTEST_PROVENANCE_SCHEMA_VERSION,
                "plugin_id": PYTEST_PROVENANCE_PLUGIN_ID,
                "plugin_version": PYTEST_PROVENANCE_PLUGIN_VERSION,
                "nonce": "wrong",
                "logical_command_digest": "digest",
                "category": "tests_failed",
                "pytest_exit_status": 1,
            },
            "nonce_mismatch",
        ),
        (
            {
                "schema_version": PYTEST_PROVENANCE_SCHEMA_VERSION,
                "plugin_id": PYTEST_PROVENANCE_PLUGIN_ID,
                "plugin_version": PYTEST_PROVENANCE_PLUGIN_VERSION,
                "nonce": "nonce",
                "logical_command_digest": "wrong",
                "category": "tests_failed",
                "pytest_exit_status": 1,
            },
            "logical_command_digest_mismatch",
        ),
        (
            {
                "schema_version": PYTEST_PROVENANCE_SCHEMA_VERSION,
                "plugin_id": PYTEST_PROVENANCE_PLUGIN_ID,
                "plugin_version": PYTEST_PROVENANCE_PLUGIN_VERSION,
                "nonce": "nonce",
                "logical_command_digest": "digest",
                "category": "surprise",
                "pytest_exit_status": 1,
            },
            "unknown_category",
        ),
        (
            {
                "schema_version": PYTEST_PROVENANCE_SCHEMA_VERSION,
                "plugin_id": PYTEST_PROVENANCE_PLUGIN_ID,
                "plugin_version": PYTEST_PROVENANCE_PLUGIN_VERSION,
                "nonce": "nonce",
                "logical_command_digest": "digest",
                "category": "tests_failed",
                "pytest_exit_status": 0,
            },
            "category_exit_status_mismatch",
        ),
    ],
)
def test_verification_fail_closed_cases(tmp_path: Path, payload: object, failure_kind: str) -> None:
    request = _request(tmp_path)
    if isinstance(payload, dict):
        request.artifact_path.write_text(json.dumps(payload), encoding="utf-8")
    elif isinstance(payload, str):
        request.artifact_path.write_text(payload, encoding="utf-8")

    verified = verify_pytest_provenance_attestation(request, exit_code=1, timed_out=False)

    assert verified.valid is False
    assert verified.repair_eligible is False
    assert verified.failure_kind == failure_kind


def test_verification_rejects_oversized_artifact(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request.artifact_path.write_text("x" * (PYTEST_PROVENANCE_MAX_BYTES + 1), encoding="utf-8")

    verified = verify_pytest_provenance_attestation(request, exit_code=1, timed_out=False)

    assert verified.failure_kind == "artifact_oversized"


@pytest.mark.parametrize("timed_out, tool_failed, failure", [(True, False, "timeout"), (False, True, "tool_failed")])
def test_timeout_and_tool_failure_override_valid_artifact(tmp_path: Path, timed_out: bool, tool_failed: bool, failure: str) -> None:
    request = _request(tmp_path)
    write_pytest_provenance_attestation(
        artifact_path=request.artifact_path,
        nonce=request.nonce,
        logical_command_digest=request.logical_command_digest,
        pytest_exit_status=1,
    )

    verified = verify_pytest_provenance_attestation(request, exit_code=None, timed_out=timed_out, tool_failed=tool_failed)

    assert verified.valid is False
    assert verified.failure_kind == failure


def test_raw_exit_one_without_attestation_is_not_repair_eligible() -> None:
    selection = _selection()
    observation = validation_observation_from_result_details(selection, {"exit_code": 1, "stdout": "FAILED", "stderr": ""})

    assert observation.validation_status == "validation_nonzero"
    assert observation.repair_eligible is False
    assert observation.pytest_provenance_status is None


def test_valid_tests_failed_attestation_is_repair_eligible(tmp_path: Path) -> None:
    selection = _selection()
    request = _request(tmp_path)
    write_pytest_provenance_attestation(
        artifact_path=request.artifact_path,
        nonce=request.nonce,
        logical_command_digest=request.logical_command_digest,
        pytest_exit_status=1,
    )
    provenance = verify_pytest_provenance_attestation(request, exit_code=1, timed_out=False)

    observation = validation_observation_from_result_details(
        selection,
        {"exit_code": 1, "stdout": "FAILED text is ignored", "stderr": "", "stdout_truncated": True},
        pytest_provenance=provenance,
    )

    assert observation.validation_status == "failed"
    assert observation.repair_eligible is True
    assert observation.pytest_provenance_status == "valid"
    assert observation.pytest_completion_category == "tests_failed"
    assert observation.stdout_truncated is True


def _request(tmp_path: Path) -> PytestProvenanceRequest:
    path = tmp_path / ".pp-agent" / "validation-provenance" / "nonce.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return PytestProvenanceRequest(
        nonce="nonce",
        logical_command_digest="digest",
        artifact_path=path,
        artifact_relative_path=".pp-agent/validation-provenance/nonce.json",
    )
