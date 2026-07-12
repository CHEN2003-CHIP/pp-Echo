from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Literal

from pp_agent.coding.testing import ValidationCommand, ValidationPlan
from pp_agent.coding.pytest_provenance import PytestProvenanceVerification

ValidationSelectionStatus = Literal["selected", "no_eligible_validation"]
ValidationExecutionStatus = Literal["not_executed", "executed", "blocked"]
ValidationStatus = Literal["not_run", "approval_pending", "passed", "failed", "blocked", "validation_nonzero"]

_PYTEST_INTERPRETERS = {"python", "python3", "py"}
_FORBIDDEN_TARGET_CHARS = set(";|&`<>$")


@dataclass(frozen=True)
class SelectedValidationCommand:
    """A deterministic selection result for one eligible pytest validation command."""

    status: ValidationSelectionStatus
    command: str | None = None
    normalized_command: str | None = None
    target: str | None = None
    command_index: int | None = None
    reason: str = ""

    @property
    def selected(self) -> bool:
        return self.status == "selected"

    @property
    def command_id(self) -> str | None:
        if not self.normalized_command:
            return None
        return f"validation-command:{self.normalized_command}"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "command": self.command,
            "normalized_command": self.normalized_command,
            "target": self.target,
            "command_index": self.command_index,
            "command_id": self.command_id,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ValidationObservation:
    """Trace-safe evidence for one already-existing validation execution result."""

    command_id: str | None
    command: str | None
    normalized_command: str | None
    target: str | None
    execution_status: ValidationExecutionStatus
    validation_status: ValidationStatus
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    stdout_chars: int = 0
    stderr_chars: int = 0
    timed_out: bool = False
    backend: str | None = None
    failure_kind: str | None = None
    failure_summary: str = ""
    repair_eligible: bool = False
    pytest_provenance_status: str | None = None
    pytest_completion_category: str | None = None
    pytest_exit_status: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "command_id": self.command_id,
            "command": self.command,
            "normalized_command": self.normalized_command,
            "target": self.target,
            "execution_status": self.execution_status,
            "validation_status": self.validation_status,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "stdout_chars": self.stdout_chars,
            "stderr_chars": self.stderr_chars,
            "timed_out": self.timed_out,
            "backend": self.backend,
            "failure_kind": self.failure_kind,
            "failure_summary": self.failure_summary,
            "repair_eligible": self.repair_eligible,
            "pytest_provenance_status": self.pytest_provenance_status,
            "pytest_completion_category": self.pytest_completion_category,
            "pytest_exit_status": self.pytest_exit_status,
        }


@dataclass(frozen=True)
class ValidationOutcome:
    """Minimal validation-aware completion contract for future controlled-loop integration."""

    final_status: ValidationStatus
    observation: ValidationObservation | None = None
    repair_attempted: bool = False
    revalidation_attempted: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "final_status": self.final_status,
            "observation": self.observation.to_dict() if self.observation is not None else None,
            "repair_attempted": self.repair_attempted,
            "revalidation_attempted": self.revalidation_attempted,
        }


def select_primary_pytest_validation_command(plan: ValidationPlan | None) -> SelectedValidationCommand:
    """Select the first eligible pytest command from the existing deterministic ValidationPlan order."""

    if plan is None or not plan.commands:
        return SelectedValidationCommand(status="no_eligible_validation", reason="ValidationPlan has no commands.")
    for index, command in enumerate(plan.commands):
        eligible = _eligible_pytest_command(command)
        if eligible is not None:
            normalized_command, target = eligible
            return SelectedValidationCommand(
                status="selected",
                command=command.command,
                normalized_command=normalized_command,
                target=target,
                command_index=index,
                reason=command.reason,
            )
    return SelectedValidationCommand(status="no_eligible_validation", reason="ValidationPlan has no eligible pytest command.")


def validation_observation_from_result_details(
    selection: SelectedValidationCommand,
    result_details: dict[str, Any] | None,
    *,
    execution_status: ValidationExecutionStatus = "executed",
    validation_status: ValidationStatus | None = None,
    failure_kind: str | None = None,
    pytest_provenance: PytestProvenanceVerification | None = None,
) -> ValidationObservation:
    """Normalize an already-existing bounded shell result into validation evidence without executing anything."""

    details = dict(result_details or {})
    if selection.command_id is None:
        return _not_run_observation(selection, "no_eligible_validation")
    if execution_status == "not_executed":
        status = validation_status or "approval_pending"
        return _not_executed_observation(selection, status, failure_kind=failure_kind)
    if execution_status == "blocked":
        return _blocked_observation(selection, details, failure_kind=failure_kind or _failure_kind(details))

    timed_out = bool(details.get("timed_out", False))
    exit_code = _optional_int(details.get("exit_code", details.get("returncode")))
    if timed_out:
        status: ValidationStatus = "blocked"
        resolved_failure = failure_kind or "timeout"
    elif pytest_provenance is not None and pytest_provenance.valid:
        status = _status_from_pytest_category(pytest_provenance.category)
        resolved_failure = failure_kind or (
            None if status == "passed" else f"pytest_{pytest_provenance.category}"
        )
    elif pytest_provenance is not None and pytest_provenance.status != "skipped":
        status = "validation_nonzero" if exit_code is not None else "blocked"
        resolved_failure = failure_kind or pytest_provenance.failure_kind or "pytest_provenance_invalid"
    elif validation_status is not None:
        status = validation_status
        resolved_failure = failure_kind
    elif exit_code == 0:
        status = "passed"
        resolved_failure = None
    elif exit_code is None:
        status = "blocked"
        resolved_failure = failure_kind or _failure_kind(details) or "missing_exit_code"
    else:
        status = "validation_nonzero"
        resolved_failure = failure_kind or _failure_kind(details) or "validation_nonzero"

    return ValidationObservation(
        command_id=selection.command_id,
        command=selection.command,
        normalized_command=selection.normalized_command,
        target=selection.target,
        execution_status="executed",
        validation_status=status,
        exit_code=exit_code,
        stdout=str(details.get("stdout") or ""),
        stderr=str(details.get("stderr") or ""),
        stdout_truncated=bool(details.get("stdout_truncated", False)),
        stderr_truncated=bool(details.get("stderr_truncated", False)),
        stdout_chars=_int_or_len(details.get("stdout_chars"), str(details.get("stdout") or "")),
        stderr_chars=_int_or_len(details.get("stderr_chars"), str(details.get("stderr") or "")),
        timed_out=timed_out,
        backend=_optional_str(details.get("backend") or details.get("sandbox_backend")),
        failure_kind=resolved_failure,
        failure_summary=_failure_summary(status, exit_code=exit_code, failure_kind=resolved_failure, timed_out=timed_out),
        repair_eligible=bool(pytest_provenance.repair_eligible) if pytest_provenance is not None else status == "failed",
        pytest_provenance_status=pytest_provenance.status if pytest_provenance is not None else None,
        pytest_completion_category=pytest_provenance.category if pytest_provenance is not None else None,
        pytest_exit_status=pytest_provenance.pytest_exit_status if pytest_provenance is not None else None,
    )


def validation_outcome_from_observation(
    observation: ValidationObservation | None,
    *,
    final_status: ValidationStatus | None = None,
    repair_attempted: bool = False,
    revalidation_attempted: bool = False,
) -> ValidationOutcome:
    """Build a deterministic ValidationOutcome without lifecycle transitions."""

    status = final_status or (observation.validation_status if observation is not None else "not_run")
    return ValidationOutcome(
        final_status=status,
        observation=observation,
        repair_attempted=bool(repair_attempted),
        revalidation_attempted=bool(revalidation_attempted),
    )


def _eligible_pytest_command(command: ValidationCommand) -> tuple[str, str] | None:
    raw = str(command.command or "").strip()
    if not raw:
        return None
    parts = raw.split()
    if not parts:
        return None
    if parts[0] in _PYTEST_INTERPRETERS:
        if len(parts) < 4 or parts[1:3] != ["-m", "pytest"]:
            return None
        remaining = parts[3:]
        normalized_prefix = f"{parts[0]} -m pytest"
    elif parts[0] == "pytest":
        remaining = parts[1:]
        normalized_prefix = "pytest"
    else:
        return None
    target, quiet = _parse_pytest_target_args(remaining)
    if target is None or not _safe_stage_test_target(target):
        return None
    normalized = f"{normalized_prefix} {target}"
    if quiet:
        normalized += " -q"
    return normalized, target


def _parse_pytest_target_args(args: list[str]) -> tuple[str | None, bool]:
    if len(args) == 1:
        return args[0], False
    if len(args) == 2 and args[1] == "-q":
        return args[0], True
    return None, False


def _safe_stage_test_target(target: str) -> bool:
    if not target or target.startswith("-") or any(char in target for char in _FORBIDDEN_TARGET_CHARS) or "$(" in target or ":" in target:
        return False
    posix = PurePosixPath(target)
    windows = PureWindowsPath(target)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        return False
    if any(part in {"", ".", ".."} for part in posix.parts):
        return False
    return True


def _not_run_observation(selection: SelectedValidationCommand, failure_kind: str | None = None) -> ValidationObservation:
    return ValidationObservation(
        command_id=selection.command_id,
        command=selection.command,
        normalized_command=selection.normalized_command,
        target=selection.target,
        execution_status="not_executed",
        validation_status="not_run",
        failure_kind=failure_kind,
        failure_summary=_failure_summary("not_run", failure_kind=failure_kind),
    )


def _not_executed_observation(
    selection: SelectedValidationCommand,
    status: ValidationStatus,
    *,
    failure_kind: str | None = None,
) -> ValidationObservation:
    return ValidationObservation(
        command_id=selection.command_id,
        command=selection.command,
        normalized_command=selection.normalized_command,
        target=selection.target,
        execution_status="not_executed",
        validation_status=status,
        failure_kind=failure_kind,
        failure_summary=_failure_summary(status, failure_kind=failure_kind),
    )


def _blocked_observation(
    selection: SelectedValidationCommand,
    details: dict[str, Any],
    *,
    failure_kind: str | None = None,
) -> ValidationObservation:
    exit_code = _optional_int(details.get("exit_code", details.get("returncode")))
    timed_out = bool(details.get("timed_out", False))
    resolved_failure = failure_kind or ("timeout" if timed_out else "blocked")
    return ValidationObservation(
        command_id=selection.command_id,
        command=selection.command,
        normalized_command=selection.normalized_command,
        target=selection.target,
        execution_status="blocked",
        validation_status="blocked",
        exit_code=exit_code,
        stdout=str(details.get("stdout") or ""),
        stderr=str(details.get("stderr") or ""),
        stdout_truncated=bool(details.get("stdout_truncated", False)),
        stderr_truncated=bool(details.get("stderr_truncated", False)),
        stdout_chars=_int_or_len(details.get("stdout_chars"), str(details.get("stdout") or "")),
        stderr_chars=_int_or_len(details.get("stderr_chars"), str(details.get("stderr") or "")),
        timed_out=timed_out,
        backend=_optional_str(details.get("backend") or details.get("sandbox_backend")),
        failure_kind=resolved_failure,
        failure_summary=_failure_summary("blocked", exit_code=exit_code, failure_kind=resolved_failure, timed_out=timed_out),
    )


def _failure_summary(
    status: ValidationStatus,
    *,
    exit_code: int | None = None,
    failure_kind: str | None = None,
    timed_out: bool = False,
) -> str:
    parts = [f"validation_status={status}"]
    if exit_code is not None:
        parts.append(f"exit_code={exit_code}")
    if timed_out:
        parts.append("timed_out=true")
    if failure_kind:
        parts.append(f"failure_kind={failure_kind}")
    return "; ".join(parts)


def _failure_kind(details: dict[str, Any]) -> str | None:
    value = details.get("failure_kind") or details.get("failure_reason_code")
    return _optional_str(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_or_len(value: Any, text: str) -> int:
    parsed = _optional_int(value)
    return parsed if parsed is not None else len(text)


def _status_from_pytest_category(category: str | None) -> ValidationStatus:
    if category == "passed":
        return "passed"
    if category == "tests_failed":
        return "failed"
    return "validation_nonzero"
