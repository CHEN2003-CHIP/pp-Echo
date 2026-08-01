from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pp_agent.coding.runtime_loop import collect_pending_approvals
from pp_agent.coding.validation_execution import (
    ValidationCycleResult,
    approve_staged_validation_cycle,
    stage_selected_validation_cycle,
)
from pp_agent.coding.validation_outcome import (
    SelectedValidationCommand,
    ValidationObservation,
    ValidationOutcome,
    validation_outcome_from_observation,
)

MAX_REPAIR_CONTINUATIONS = 1
MAX_REVALIDATION_ATTEMPTS = 1
MAX_VALIDATION_EXECUTIONS = 2
REPAIR_OUTPUT_PREVIEW_CHARS = 4000

ValidationRepairCycleStatus = Literal[
    "not_repairable",
    "repair_pending",
    "repair_blocked",
    "repair_completed",
    "revalidation_pending",
    "completed",
]


@dataclass(frozen=True)
class ValidationRepairCycleState:
    """Run-local guardrails for one bounded validation repair cycle."""

    selection: SelectedValidationCommand
    initial_result: ValidationCycleResult
    repair_attempted: bool = False
    revalidation_attempted: bool = False
    repair_prompt: str | None = None
    repair_result: Any | None = None
    revalidation_result: ValidationCycleResult | None = None
    final_outcome: ValidationOutcome | None = None
    status: ValidationRepairCycleStatus = "not_repairable"
    validation_executions: int = 1
    details: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "selection": self.selection.to_dict(),
            "initial_result": self.initial_result.to_dict(),
            "repair_attempted": self.repair_attempted,
            "revalidation_attempted": self.revalidation_attempted,
            "revalidation_result": self.revalidation_result.to_dict() if self.revalidation_result is not None else None,
            "final_outcome": self.final_outcome.to_dict() if self.final_outcome is not None else None,
            "validation_executions": self.validation_executions,
            "details": dict(self.details),
        }


def validation_repair_trigger_allowed(
    initial_result: ValidationCycleResult,
    *,
    repair_attempted: bool = False,
) -> bool:
    """Return true only for trusted tests_failed provenance that has not already triggered repair."""

    observation = initial_result.observation
    return (
        observation is not None
        and initial_result.status == "executed"
        and observation.execution_status == "executed"
        and observation.validation_status == "failed"
        and observation.pytest_provenance_status == "valid"
        and observation.pytest_completion_category == "tests_failed"
        and observation.repair_eligible is True
        and repair_attempted is False
    )


def build_validation_repair_prompt(
    *,
    task: str,
    selection: SelectedValidationCommand,
    observation: ValidationObservation,
) -> str:
    """Build a deterministic, bounded repair prompt without secrets or provenance internals."""

    stdout = _bounded(observation.stdout, REPAIR_OUTPUT_PREVIEW_CHARS)
    stderr = _bounded(observation.stderr, REPAIR_OUTPUT_PREVIEW_CHARS)
    lines = [
        "Mission 07 bounded validation repair continuation.",
        "",
        "This is the only allowed repair attempt for the current validation cycle.",
        "Trusted pytest provenance structurally proved that the selected validation command completed with tests_failed.",
        "",
        "Repair scope:",
        f"- Original task: {task.strip() or 'Unspecified task'}",
        f"- Immutable validation command: {selection.normalized_command or selection.command or ''}",
        f"- Command index: {selection.command_index}",
        f"- Target: {selection.target or ''}",
        "- Do not change the validation command.",
        "- Do not select another validation command.",
        "- Do not run a full suite instead of this command.",
        "- Do not narrow to a pytest node id.",
        "- Do not skip, xfail, delete, or weaken tests to manufacture a pass.",
        "- Do not modify the pytest provenance plugin or verifier to hide the failure.",
        "- Do not bypass tool approval.",
        "- Make only the minimal task-scoped repair, then stop. Re-validation is owned by the orchestrator.",
        "",
        "Validation observation:",
        f"- status: {observation.validation_status}",
        f"- pytest completion category: {observation.pytest_completion_category}",
        f"- pytest exit status: {observation.pytest_exit_status}",
        f"- process exit code: {observation.exit_code}",
        f"- stdout truncated: {str(observation.stdout_truncated).lower()}",
        f"- stderr truncated: {str(observation.stderr_truncated).lower()}",
        "",
        "Bounded stdout:",
        stdout or "[empty]",
        "",
        "Bounded stderr:",
        stderr or "[empty]",
    ]
    return "\n".join(lines).strip()


def run_one_bounded_validation_repair_cycle(
    *,
    task: str,
    runtime: Any,
    registry: Any,
    initial_result: ValidationCycleResult,
) -> ValidationRepairCycleState:
    """Run at most one repair continuation and then stage one same-command re-validation."""

    selection = initial_result.selection
    if not validation_repair_trigger_allowed(initial_result):
        return _state(
            selection=selection,
            initial_result=initial_result,
            status="not_repairable",
            final_outcome=validation_outcome_from_observation(
                initial_result.observation,
                repair_attempted=False,
                revalidation_attempted=False,
            ),
            details={"reason": "repair_trigger_not_allowed"},
        )
    observation = initial_result.observation
    assert observation is not None
    prompt = build_validation_repair_prompt(task=task, selection=selection, observation=observation)
    try:
        repair_events = _run_one_repair_continuation(runtime, prompt)
    except Exception as exc:  # noqa: BLE001
        return _state(
            selection=selection,
            initial_result=initial_result,
            status="repair_blocked",
            repair_attempted=True,
            repair_prompt=prompt,
            final_outcome=validation_outcome_from_observation(
                observation,
                final_status="blocked",
                repair_attempted=True,
                revalidation_attempted=False,
            ),
            details={"failure_kind": "repair_model_failure", "error": exc.__class__.__name__},
        )
    pending = collect_pending_approvals(runtime)
    if pending:
        return _state(
            selection=selection,
            initial_result=initial_result,
            status="repair_pending",
            repair_attempted=True,
            repair_prompt=prompt,
            repair_result=repair_events,
            final_outcome=validation_outcome_from_observation(
                observation,
                final_status="approval_pending",
                repair_attempted=True,
                revalidation_attempted=False,
            ),
            details={"pending_approvals": pending},
        )
    if _events_blocked(repair_events):
        return _state(
            selection=selection,
            initial_result=initial_result,
            status="repair_blocked",
            repair_attempted=True,
            repair_prompt=prompt,
            repair_result=repair_events,
            final_outcome=validation_outcome_from_observation(
                observation,
                final_status="blocked",
                repair_attempted=True,
                revalidation_attempted=False,
            ),
            details={"failure_kind": "repair_blocked"},
        )
    revalidation = stage_selected_validation_cycle(
        selection,
        registry,
        reason="Run same validation command after one bounded repair attempt",
    )
    final_status = "approval_pending" if revalidation.status == "approval_pending" else revalidation.outcome.final_status
    return _state(
        selection=selection,
        initial_result=initial_result,
        status="revalidation_pending" if revalidation.status == "approval_pending" else "completed",
        repair_attempted=True,
        revalidation_attempted=False,
        repair_prompt=prompt,
        repair_result=repair_events,
        revalidation_result=revalidation,
        final_outcome=validation_outcome_from_observation(
            revalidation.observation,
            final_status=final_status,
            repair_attempted=True,
            revalidation_attempted=False,
        ),
        details={"revalidation_stage_status": revalidation.status},
    )


def complete_revalidation_after_approval(
    state: ValidationRepairCycleState,
    *,
    evidence_reference: Any,
    session_store: Any,
    workspace: Any,
) -> ValidationRepairCycleState:
    """Interpret one runtime-persisted same-command re-validation result and finalize the repair cycle."""

    if state.revalidation_attempted:
        return _state(
            selection=state.selection,
            initial_result=state.initial_result,
            status="completed",
            repair_attempted=True,
            revalidation_attempted=True,
            repair_prompt=state.repair_prompt,
            repair_result=state.repair_result,
            revalidation_result=state.revalidation_result,
            final_outcome=state.final_outcome,
            validation_executions=min(state.validation_executions, MAX_VALIDATION_EXECUTIONS),
            details={**state.details, "idempotent": True, "reason": "revalidation_already_attempted"},
        )
    if not state.repair_attempted or state.revalidation_result is None:
        return _state(
            selection=state.selection,
            initial_result=state.initial_result,
            status="repair_blocked",
            repair_attempted=state.repair_attempted,
            revalidation_attempted=False,
            repair_prompt=state.repair_prompt,
            repair_result=state.repair_result,
            final_outcome=validation_outcome_from_observation(
                state.initial_result.observation,
                final_status="blocked",
                repair_attempted=state.repair_attempted,
                revalidation_attempted=False,
            ),
            validation_executions=state.validation_executions,
            details={**state.details, "failure_kind": "revalidation_not_staged"},
        )
    result = approve_staged_validation_cycle(
        state.selection,
        evidence_reference=evidence_reference,
        session_store=session_store,
        workspace=workspace,
    )
    status = "completed" if result.status in {"executed", "blocked"} else "revalidation_pending"
    final_status = _final_status_after_revalidation(result)
    return _state(
        selection=state.selection,
        initial_result=state.initial_result,
        status=status,
        repair_attempted=True,
        revalidation_attempted=True,
        repair_prompt=state.repair_prompt,
        repair_result=state.repair_result,
        revalidation_result=result,
        final_outcome=validation_outcome_from_observation(
            result.observation,
            final_status=final_status,
            repair_attempted=True,
            revalidation_attempted=True,
        ),
        validation_executions=min(state.validation_executions + 1, MAX_VALIDATION_EXECUTIONS),
        details={**state.details, "revalidation_status": result.status},
    )


def _run_one_repair_continuation(runtime: Any, prompt: str) -> list[Any]:
    method = getattr(runtime, "prompt", None)
    if not callable(method):
        raise RuntimeError("runtime prompt continuation is unavailable")
    return list(method(prompt) or [])


def _events_blocked(events: list[Any]) -> bool:
    for event in events:
        details = getattr(event, "details", None)
        if isinstance(event, dict):
            details = event.get("details")
        if _contains_blocking_detail(details):
            return True
        if bool(getattr(event, "is_error", False)):
            return True
    return False


def _contains_blocking_detail(value: Any) -> bool:
    if isinstance(value, dict):
        if any(bool(value.get(key)) for key in ("scope_blocked", "runtime_guardrail_blocked", "approval_unavailable")):
            return True
        return any(_contains_blocking_detail(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_blocking_detail(item) for item in value)
    return False


def _final_status_after_revalidation(result: ValidationCycleResult) -> str:
    observation = result.observation
    if observation is None:
        return "blocked"
    if result.status == "blocked":
        return "blocked"
    return observation.validation_status


def _bounded(text: str, limit: int) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    omitted = len(value) - limit
    return f"{value[:limit]}\n[repair context truncated {omitted} chars]"


def _state(
    *,
    selection: SelectedValidationCommand,
    initial_result: ValidationCycleResult,
    status: ValidationRepairCycleStatus,
    repair_attempted: bool = False,
    revalidation_attempted: bool = False,
    repair_prompt: str | None = None,
    repair_result: Any | None = None,
    revalidation_result: ValidationCycleResult | None = None,
    final_outcome: ValidationOutcome | None = None,
    validation_executions: int = 1,
    details: dict[str, object] | None = None,
) -> ValidationRepairCycleState:
    return ValidationRepairCycleState(
        selection=selection,
        initial_result=initial_result,
        repair_attempted=repair_attempted,
        revalidation_attempted=revalidation_attempted,
        repair_prompt=repair_prompt,
        repair_result=repair_result,
        revalidation_result=revalidation_result,
        final_outcome=final_outcome,
        status=status,
        validation_executions=min(validation_executions, MAX_VALIDATION_EXECUTIONS),
        details=dict(details or {}),
    )
