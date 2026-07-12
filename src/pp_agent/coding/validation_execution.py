from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pp_agent.coding.testing import ValidationPlan
from pp_agent.coding.validation_outcome import (
    SelectedValidationCommand,
    ValidationObservation,
    ValidationOutcome,
    select_primary_pytest_validation_command,
    validation_observation_from_result_details,
    validation_outcome_from_observation,
)

ValidationCycleStatus = Literal["not_run", "approval_pending", "executed", "blocked"]


@dataclass(frozen=True)
class ValidationCycleResult:
    """Result for one approval-gated validation cycle without repair or re-validation."""

    status: ValidationCycleStatus
    selection: SelectedValidationCommand
    outcome: ValidationOutcome
    observation: ValidationObservation | None = None
    approval_token: str | None = None
    details: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "selection": self.selection.to_dict(),
            "outcome": self.outcome.to_dict(),
            "observation": self.observation.to_dict() if self.observation is not None else None,
            "approval_token": self.approval_token,
            "details": dict(self.details),
        }


def stage_validation_cycle(validation_plan: ValidationPlan | None, registry: Any, *, reason: str = "Run validation") -> ValidationCycleResult:
    """Stage one selected pytest validation command through the existing stage_test_command path."""

    selection = select_primary_pytest_validation_command(validation_plan)
    if not selection.selected:
        observation = validation_observation_from_result_details(selection, None)
        return _cycle_result("not_run", selection, observation, details={"reason": selection.reason})
    try:
        staged = registry.execute(
            "stage_test_command",
            {
                "framework": "pytest",
                "target": selection.target,
                "reason": reason,
                "quiet": _selection_uses_quiet(selection),
            },
        )
    except Exception as exc:  # noqa: BLE001
        observation = _blocked_exception_observation(selection, exc)
        return _cycle_result("blocked", selection, observation, details={"failure_kind": "stage_failed"})

    details = _as_mapping(getattr(staged, "details", None))
    token = _string_or_none(details.get("token"))
    observation = validation_observation_from_result_details(
        selection,
        None,
        execution_status="not_executed",
        validation_status="approval_pending",
        failure_kind="approval_pending",
    )
    return _cycle_result(
        "approval_pending",
        selection,
        observation,
        approval_token=token,
        details={
            "staged_tool": "stage_test_command",
            "delegates_to": _string_or_none(details.get("delegates_to")) or "run_shell",
            "generated_command": _string_or_none(details.get("generated_command")),
            "proposal_digest": _proposal_digest(details),
        },
    )


def approve_staged_validation_cycle(selection: SelectedValidationCommand, registry: Any, approval_token: str) -> ValidationCycleResult:
    """Execute one already-staged validation action through the existing approve_pending_action path."""

    if not selection.selected:
        observation = validation_observation_from_result_details(selection, None)
        return _cycle_result("not_run", selection, observation)
    try:
        approved = registry.host_execute("approve_pending_action", {"token": approval_token})
    except Exception as exc:  # noqa: BLE001
        observation = _blocked_exception_observation(selection, exc)
        return _cycle_result("blocked", selection, observation, approval_token=approval_token, details={"failure_kind": "approval_or_execution_failed"})

    details = _as_mapping(getattr(approved, "details", None))
    has_exit_code = "exit_code" in details or "returncode" in details
    if bool(details.get("idempotent")) and not has_exit_code:
        observation = validation_observation_from_result_details(
            selection,
            details,
            execution_status="blocked",
            failure_kind="already_consumed",
        )
    elif bool(getattr(approved, "is_error", False)) and not has_exit_code:
        observation = validation_observation_from_result_details(
            selection,
            details,
            execution_status="blocked",
            failure_kind=str(details.get("failure_kind") or "execution_failed"),
        )
    else:
        observation = validation_observation_from_result_details(selection, details)
    status: ValidationCycleStatus = "executed" if observation.execution_status == "executed" else "blocked"
    return _cycle_result(
        status,
        selection,
        observation,
        approval_token=approval_token,
        details={
            "approval_tool": "approve_pending_action",
            "tool_is_error": bool(getattr(approved, "is_error", False)),
            "lifecycle": details.get("lifecycle") if isinstance(details.get("lifecycle"), dict) else None,
        },
    )


def reject_staged_validation_cycle(selection: SelectedValidationCommand, registry: Any, approval_token: str) -> ValidationCycleResult:
    """Reject one staged validation action through the existing reject_pending_action path."""

    try:
        rejected = registry.host_execute("reject_pending_action", {"token": approval_token})
        details = _as_mapping(getattr(rejected, "details", None))
    except Exception as exc:  # noqa: BLE001
        details = {"failure_kind": "approval_reject_failed", "error": exc.__class__.__name__}
    observation = validation_observation_from_result_details(
        selection,
        details,
        execution_status="blocked",
        failure_kind="approval_denied",
    )
    return _cycle_result(
        "blocked",
        selection,
        observation,
        approval_token=approval_token,
        details={
            "approval_tool": "reject_pending_action",
            "lifecycle": details.get("lifecycle") if isinstance(details.get("lifecycle"), dict) else None,
        },
    )


def _cycle_result(
    status: ValidationCycleStatus,
    selection: SelectedValidationCommand,
    observation: ValidationObservation,
    *,
    approval_token: str | None = None,
    details: dict[str, object] | None = None,
) -> ValidationCycleResult:
    return ValidationCycleResult(
        status=status,
        selection=selection,
        observation=observation,
        outcome=validation_outcome_from_observation(observation),
        approval_token=approval_token,
        details=dict(details or {}),
    )


def _blocked_exception_observation(selection: SelectedValidationCommand, exc: Exception) -> ValidationObservation:
    return validation_observation_from_result_details(
        selection,
        {"failure_kind": exc.__class__.__name__},
        execution_status="blocked",
        failure_kind=exc.__class__.__name__,
    )


def _selection_uses_quiet(selection: SelectedValidationCommand) -> bool:
    command = selection.normalized_command or selection.command or ""
    return command.split()[-1:] == ["-q"]


def _proposal_digest(details: dict[str, Any]) -> str | None:
    proposal = details.get("command_proposal")
    if not isinstance(proposal, dict):
        return _string_or_none(details.get("proposal_digest"))
    return _string_or_none(proposal.get("proposal_digest") or details.get("proposal_digest"))


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="python")
        return dumped if isinstance(dumped, dict) else {}
    return dict(getattr(value, "__dict__", {}) or {})


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
