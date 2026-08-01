from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any, Literal

from pp_agent.coding.workflow_checkpoint import (
    CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V3,
    CodingWorkflowCheckpoint,
    CodingWorkflowKind,
    CodingWorkflowPhase,
    PendingActionReference,
    PendingActionRole,
)
from pp_agent.coding.workflow_checkpoint_store import (
    CheckpointAlreadyExists,
    CheckpointNotFound,
    CheckpointStaleRevision,
    CheckpointStorageError,
    CheckpointTerminal,
    CheckpointUnsupportedSchema,
    CodingWorkflowCheckpointStore,
)

from pp_agent.coding.testing import ValidationPlan
from pp_agent.coding.pytest_provenance import (
    PytestProvenanceRequest,
    PytestProvenanceVerification,
    build_instrumented_validation_command,
    verify_pytest_provenance_attestation,
)
from pp_agent.coding.validation_outcome import (
    SelectedValidationCommand,
    ValidationObservation,
    ValidationOutcome,
    select_primary_pytest_validation_command,
    validation_observation_from_result_details,
    validation_outcome_from_observation,
)
from pp_agent.storage.sessions import (
    ExternalResultEvidenceDetails,
    PytestProvenanceRequestEvidence,
    SessionEvidenceLookupStatus,
    SessionEvidenceReference,
    SessionStore,
    SessionValidationEvidence,
    SessionValidationEvidenceConflict,
)

ValidationCycleStatus = Literal["not_run", "approval_pending", "executed", "blocked"]
InitialValidationStagingStatus = Literal[
    "staged",
    "already_staged",
    "blocked_no_command",
    "blocked_conflict",
    "blocked_stale_revision",
    "blocked_orphan_risk",
    "blocked_terminal",
    "blocked_unsupported_schema",
    "blocked_stage_failed",
]


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


@dataclass(frozen=True)
class InitialValidationStagingResult:
    """Durable initial validation staging result without executing approval or pytest."""

    status: InitialValidationStagingStatus
    workflow_id: str
    session_id: str
    selection: SelectedValidationCommand | None = None
    checkpoint_revision: int | None = None
    pending_action_ref: PendingActionReference | None = None
    approval_token: str | None = None
    reason: str = ""
    details: dict[str, object] = field(default_factory=dict)

    @property
    def awaiting_approval(self) -> bool:
        return self.status in {"staged", "already_staged"}

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "workflow_id": self.workflow_id,
            "session_id": self.session_id,
            "selection": self.selection.to_dict() if self.selection is not None else None,
            "checkpoint_revision": self.checkpoint_revision,
            "pending_action_ref": self.pending_action_ref.to_dict() if self.pending_action_ref is not None else None,
            "approval_token": self.approval_token,
            "reason": self.reason,
            "details": dict(self.details),
        }


def stage_initial_validation_workflow(
    *,
    workspace: Path,
    workflow_id: str,
    session_id: str,
    validation_plan: ValidationPlan | None,
    registry: Any,
    checkpoint_store: CodingWorkflowCheckpointStore | None = None,
    expected_revision: int | None = None,
) -> InitialValidationStagingResult:
    """Stage initial validation and persist the schema v3 awaiting checkpoint."""

    store = checkpoint_store or CodingWorkflowCheckpointStore(workspace)
    try:
        existing = _load_initial_validation_checkpoint(store, workflow_id)
    except CheckpointUnsupportedSchema:
        return InitialValidationStagingResult(
            status="blocked_unsupported_schema",
            workflow_id=workflow_id,
            session_id=session_id,
            reason="initial validation staging does not migrate legacy checkpoints",
        )
    except CheckpointStorageError:
        return InitialValidationStagingResult(
            status="blocked_conflict",
            workflow_id=workflow_id,
            session_id=session_id,
            reason="checkpoint could not be loaded",
        )
    if existing is not None:
        existing_result = _existing_initial_validation_result(
            checkpoint=existing,
            workflow_id=workflow_id,
            session_id=session_id,
            expected_revision=expected_revision,
        )
        if existing_result is not None:
            return existing_result

    selection = select_primary_pytest_validation_command(validation_plan)
    if not selection.selected:
        return InitialValidationStagingResult(
            status="blocked_no_command",
            workflow_id=workflow_id,
            session_id=session_id,
            selection=selection,
            reason=selection.reason,
        )
    try:
        selected_digest = _logical_command_digest(selection.normalized_command or "")
    except ValueError:
        return InitialValidationStagingResult(
            status="blocked_no_command",
            workflow_id=workflow_id,
            session_id=session_id,
            selection=selection,
            reason="selected command digest unavailable",
        )

    pre_stage = _conflicting_active_validation_action(registry, session_id=session_id, selected_digest=selected_digest)
    if pre_stage is not None:
        return InitialValidationStagingResult(
            status="blocked_orphan_risk",
            workflow_id=workflow_id,
            session_id=session_id,
            selection=selection,
            approval_token=_string_or_none(pre_stage.get("token")),
            reason="active validation action exists without matching checkpoint",
            details={"action_id": _string_or_none(pre_stage.get("token")) or ""},
        )

    staged = stage_selected_validation_cycle(selection, registry, reason="Run initial validation")
    if staged.status != "approval_pending":
        return InitialValidationStagingResult(
            status="blocked_stage_failed",
            workflow_id=workflow_id,
            session_id=session_id,
            selection=selection,
            reason=str(staged.details.get("failure_kind") or staged.status),
            details=staged.details,
        )
    action_id = staged.approval_token
    if not action_id:
        return InitialValidationStagingResult(
            status="blocked_orphan_risk",
            workflow_id=workflow_id,
            session_id=session_id,
            selection=selection,
            reason="staged validation action did not return an action id",
        )
    action = _load_pending_action(registry, action_id)
    ref = _pending_validation_reference_from_action(action, expected_digest=selected_digest)
    if ref is None:
        return InitialValidationStagingResult(
            status="blocked_orphan_risk",
            workflow_id=workflow_id,
            session_id=session_id,
            selection=selection,
            approval_token=action_id,
            reason="staged validation action identity did not match selected command",
            details={"action_id": action_id},
        )

    checkpoint = _initial_validation_checkpoint(
        workflow_id=workflow_id,
        session_id=session_id,
        selected_digest=selected_digest,
        pending_ref=ref,
    )
    try:
        if existing is None:
            committed = store.create_checkpoint(checkpoint)
        else:
            if expected_revision is None:
                return InitialValidationStagingResult(
                    status="blocked_stale_revision",
                    workflow_id=workflow_id,
                    session_id=session_id,
                    selection=selection,
                    pending_action_ref=ref,
                    approval_token=action_id,
                    reason="expected revision is required for existing checkpoint CAS",
                    details={"action_id": action_id},
                )
            committed = store.replace_checkpoint(
                _replace_initial_checkpoint(existing, selected_digest=selected_digest, pending_ref=ref),
                expected_revision=expected_revision,
            )
    except CheckpointAlreadyExists:
        return InitialValidationStagingResult(
            status="blocked_orphan_risk",
            workflow_id=workflow_id,
            session_id=session_id,
            selection=selection,
            pending_action_ref=ref,
            approval_token=action_id,
            reason="checkpoint appeared after validation action was staged",
            details={"action_id": action_id},
        )
    except CheckpointStaleRevision:
        return InitialValidationStagingResult(
            status="blocked_orphan_risk",
            workflow_id=workflow_id,
            session_id=session_id,
            selection=selection,
            pending_action_ref=ref,
            approval_token=action_id,
            reason="checkpoint revision became stale after validation action was staged",
            details={"action_id": action_id},
        )
    except (CheckpointTerminal, CheckpointStorageError):
        return InitialValidationStagingResult(
            status="blocked_orphan_risk",
            workflow_id=workflow_id,
            session_id=session_id,
            selection=selection,
            pending_action_ref=ref,
            approval_token=action_id,
            reason="checkpoint write failed after validation action was staged",
            details={"action_id": action_id},
        )

    return InitialValidationStagingResult(
        status="staged",
        workflow_id=workflow_id,
        session_id=session_id,
        selection=selection,
        checkpoint_revision=committed.revision,
        pending_action_ref=committed.pending_action_ref,
        approval_token=action_id,
        reason="initial validation staged and checkpoint committed",
    )


def stage_validation_cycle(validation_plan: ValidationPlan | None, registry: Any, *, reason: str = "Run validation") -> ValidationCycleResult:
    """Stage one selected pytest validation command through the existing stage_test_command path."""

    selection = select_primary_pytest_validation_command(validation_plan)
    return stage_selected_validation_cycle(selection, registry, reason=reason)


def stage_selected_validation_cycle(
    selection: SelectedValidationCommand,
    registry: Any,
    *,
    reason: str = "Run validation",
) -> ValidationCycleResult:
    """Stage an already-selected immutable validation command without re-running command selection."""

    if not selection.selected:
        observation = validation_observation_from_result_details(selection, None)
        return _cycle_result("not_run", selection, observation, details={"reason": selection.reason})
    try:
        instrumented = build_instrumented_validation_command(selection, workspace=registry.workspace)
    except Exception as exc:  # noqa: BLE001
        observation = _blocked_exception_observation(selection, exc)
        return _cycle_result("blocked", selection, observation, details={"failure_kind": "instrumentation_failed"})
    try:
        staged = registry.execute(
            "stage_test_command",
            {
                "framework": "pytest",
                "target": instrumented.target,
                "reason": reason,
                "quiet": instrumented.quiet,
                "_internal": instrumented.to_stage_test_internal_args(),
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
            "logical_command": selection.normalized_command,
            "logical_command_digest": instrumented.logical_command_digest,
            "adapter_mode": "trusted_pytest_provenance",
            "proposal_digest": _proposal_digest(details),
        },
    )


def approve_staged_validation_cycle(
    selection: SelectedValidationCommand,
    *,
    evidence_reference: SessionEvidenceReference,
    session_store: SessionStore,
    workspace: Path,
) -> ValidationCycleResult:
    """Compatibility entrypoint for interpreting a runtime-persisted validation result."""

    return interpret_persisted_validation_result(
        selection=selection,
        evidence_reference=evidence_reference,
        session_store=session_store,
        workspace=workspace,
    )


def interpret_persisted_validation_result(
    *,
    selection: SelectedValidationCommand,
    evidence_reference: SessionEvidenceReference,
    session_store: SessionStore,
    workspace: Path,
) -> ValidationCycleResult:
    """Interpret one already-executed, SessionStore-persisted validation result."""

    if not selection.selected:
        observation = validation_observation_from_result_details(selection, None)
        return _cycle_result("not_run", selection, observation)

    expected_digest = _logical_command_digest(selection.normalized_command or "")
    external_lookup = session_store.lookup_external_result_details(evidence_reference)
    if external_lookup.status != SessionEvidenceLookupStatus.FOUND or external_lookup.details is None:
        observation = _blocked_lookup_observation(
            selection,
            "external_result",
            external_lookup.status,
            external_lookup.reason,
        )
        return _cycle_result("blocked", selection, observation, details={"lookup_status": external_lookup.status})

    external = external_lookup.details
    identity_failure = _external_identity_failure(external, evidence_reference, expected_digest)
    if identity_failure is not None:
        observation = validation_observation_from_result_details(
            selection,
            external.details,
            execution_status="blocked",
            failure_kind=identity_failure,
        )
        return _cycle_result("blocked", selection, observation, details={"failure_kind": identity_failure})

    existing = session_store.lookup_validation_evidence(
        external.session_id,
        action_id=external.action_id,
        external_result_digest=external.result_digest,
        logical_command_digest=expected_digest,
    )
    if existing.status == SessionEvidenceLookupStatus.FOUND and existing.evidence is not None:
        observation = _observation_from_validation_evidence(selection, external, existing.evidence)
        return _cycle_result(
            "executed" if observation.execution_status == "executed" else "blocked",
            selection,
            observation,
            details={"validation_evidence": "found"},
        )
    if existing.status not in {SessionEvidenceLookupStatus.NOT_FOUND, SessionEvidenceLookupStatus.SESSION_MISSING}:
        observation = validation_observation_from_result_details(
            selection,
            external.details,
            execution_status="blocked",
            failure_kind=f"validation_evidence_{existing.status}",
        )
        return _cycle_result("blocked", selection, observation, details={"lookup_status": existing.status})

    request_lookup = session_store.lookup_pytest_provenance_request(evidence_reference)
    if request_lookup.status != SessionEvidenceLookupStatus.FOUND or request_lookup.request is None:
        observation = validation_observation_from_result_details(
            selection,
            external.details,
            execution_status="blocked",
            failure_kind=f"pytest_provenance_request_{request_lookup.status}",
        )
        return _cycle_result("blocked", selection, observation, details={"lookup_status": request_lookup.status, "reason": request_lookup.reason})

    request_identity_failure = _provenance_request_identity_failure(request_lookup.request, evidence_reference, expected_digest)
    if request_identity_failure is not None:
        observation = validation_observation_from_result_details(
            selection,
            external.details,
            execution_status="blocked",
            failure_kind=request_identity_failure,
        )
        return _cycle_result("blocked", selection, observation, details={"failure_kind": request_identity_failure})

    request = PytestProvenanceRequest(
        nonce=request_lookup.request.nonce,
        logical_command_digest=request_lookup.request.logical_command_digest,
        artifact_path=(workspace / request_lookup.request.artifact_relative_path).resolve(),
        artifact_relative_path=request_lookup.request.artifact_relative_path,
    )
    provenance = verify_pytest_provenance_attestation(
        request,
        exit_code=_optional_int(external.details.get("exit_code", external.details.get("returncode"))),
        timed_out=bool(external.details.get("timed_out", False)),
        tool_failed=external.success is False,
    )
    if provenance.status == "missing":
        observation = validation_observation_from_result_details(
            selection,
            external.details,
            execution_status="blocked",
            failure_kind=provenance.failure_kind or "pytest_provenance_missing",
        )
        return _cycle_result("blocked", selection, observation, details={"pytest_provenance_status": provenance.status})
    observation = validation_observation_from_result_details(selection, external.details, pytest_provenance=provenance)
    evidence = _validation_evidence_from_observation(
        session_id=external.session_id,
        action_id=external.action_id,
        external_result_digest=external.result_digest,
        selection=selection,
        observation=observation,
    )
    evidence_failure: str | None = None
    if evidence is None:
        evidence_failure = "validation_evidence_identity_missing"
    else:
        try:
            session_store.append_validation_evidence(evidence)
        except SessionValidationEvidenceConflict:
            evidence_failure = "validation_evidence_conflict"
        except Exception:  # noqa: BLE001
            evidence_failure = "validation_evidence_persistence_failed"
    if evidence_failure is not None:
        observation = validation_observation_from_result_details(
            selection,
            external.details,
            execution_status="blocked",
            failure_kind=evidence_failure,
        )

    status: ValidationCycleStatus = "executed" if observation.execution_status == "executed" else "blocked"
    return _cycle_result(
        status,
        selection,
        observation,
        details={
            "external_result": "session_store",
            "action_id": external.action_id,
            "message_id": external.message_id,
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


def _load_initial_validation_checkpoint(store: CodingWorkflowCheckpointStore, workflow_id: str) -> CodingWorkflowCheckpoint | None:
    try:
        return store.load_checkpoint(workflow_id)
    except CheckpointNotFound:
        return None


def _existing_initial_validation_result(
    *,
    checkpoint: CodingWorkflowCheckpoint,
    workflow_id: str,
    session_id: str,
    expected_revision: int | None,
) -> InitialValidationStagingResult | None:
    if checkpoint.session_id != session_id:
        return InitialValidationStagingResult(
            status="blocked_conflict",
            workflow_id=workflow_id,
            session_id=session_id,
            checkpoint_revision=checkpoint.revision,
            reason="checkpoint session identity mismatch",
        )
    if checkpoint.schema_version != CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V3:
        return InitialValidationStagingResult(
            status="blocked_unsupported_schema",
            workflow_id=workflow_id,
            session_id=session_id,
            checkpoint_revision=checkpoint.revision,
            reason="initial validation staging does not migrate legacy checkpoints",
        )
    if expected_revision is not None and checkpoint.revision != expected_revision:
        return InitialValidationStagingResult(
            status="blocked_stale_revision",
            workflow_id=workflow_id,
            session_id=session_id,
            checkpoint_revision=checkpoint.revision,
            reason="checkpoint revision is stale",
        )
    if checkpoint.phase in {CodingWorkflowPhase.COMPLETED, CodingWorkflowPhase.FINALIZED}:
        return InitialValidationStagingResult(
            status="blocked_terminal",
            workflow_id=workflow_id,
            session_id=session_id,
            checkpoint_revision=checkpoint.revision,
            reason="checkpoint is terminal",
        )
    if checkpoint.phase == CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL:
        ref = checkpoint.pending_action_ref
        if (
            checkpoint.selected_validation_command_digest is not None
            and checkpoint.selected_validation_command_digest_algorithm == "sha256"
            and ref is not None
            and ref.role == PendingActionRole.VALIDATION
        ):
            return InitialValidationStagingResult(
                status="already_staged",
                workflow_id=workflow_id,
                session_id=session_id,
                checkpoint_revision=checkpoint.revision,
                pending_action_ref=ref,
                approval_token=ref.action_id,
                reason="initial validation is already staged",
            )
        return InitialValidationStagingResult(
            status="blocked_conflict",
            workflow_id=workflow_id,
            session_id=session_id,
            checkpoint_revision=checkpoint.revision,
            reason="awaiting validation checkpoint is missing exact validation reference",
        )
    if checkpoint.phase not in {CodingWorkflowPhase.PREPARED, CodingWorkflowPhase.RUNTIME_STARTED, CodingWorkflowPhase.TOOL_COMPLETED}:
        return InitialValidationStagingResult(
            status="blocked_conflict",
            workflow_id=workflow_id,
            session_id=session_id,
            checkpoint_revision=checkpoint.revision,
            reason=f"checkpoint phase {checkpoint.phase.value} cannot stage initial validation",
        )
    if checkpoint.selected_validation_command_digest is not None or checkpoint.pending_action_ref is not None:
        return InitialValidationStagingResult(
            status="blocked_conflict",
            workflow_id=workflow_id,
            session_id=session_id,
            checkpoint_revision=checkpoint.revision,
            reason="checkpoint already contains validation or pending action state",
        )
    return None


def _conflicting_active_validation_action(registry: Any, *, session_id: str, selected_digest: str) -> dict[str, Any] | None:
    store = _registry_pending_store(registry)
    if store is None:
        return None
    try:
        actions = list(store.list())
    except Exception:  # noqa: BLE001
        return None
    for action in actions:
        if not _active_pending_action(action):
            continue
        if str(action.get("action_type") or "") != "run_shell":
            continue
        action_session_id = _string_or_none(action.get("session_id") or _as_mapping(action.get("details")).get("session_id"))
        if action_session_id and action_session_id != session_id:
            continue
        details = _as_mapping(action.get("details"))
        provenance = _as_mapping(details.get("pytest_provenance_request"))
        digest = _string_or_none(provenance.get("logical_command_digest") or details.get("logical_command_digest"))
        if digest == selected_digest or digest is None:
            return action
    return None


def _load_pending_action(registry: Any, action_id: str) -> dict[str, Any] | None:
    store = _registry_pending_store(registry)
    if store is None:
        return None
    try:
        return store.load(action_id)
    except Exception:  # noqa: BLE001
        return None


def _registry_pending_store(registry: Any) -> Any:
    pending_store = getattr(registry, "pending_store", None)
    if callable(pending_store):
        try:
            return pending_store()
        except Exception:  # noqa: BLE001
            return None
    return None


def _pending_validation_reference_from_action(action: dict[str, Any] | None, *, expected_digest: str) -> PendingActionReference | None:
    if action is None:
        return None
    action_id = _string_or_none(action.get("token"))
    if not action_id or str(action.get("action_type") or "") != "run_shell":
        return None
    details = _as_mapping(action.get("details"))
    proposal = _as_mapping(details.get("test_command_proposal"))
    provenance = _as_mapping(details.get("pytest_provenance_request"))
    effect = _as_mapping(action.get("effect"))
    action_digest = _string_or_none(action.get("canonical_key") or effect.get("payload_digest"))
    if not action_digest:
        return None
    if proposal.get("delegates_to") != "run_shell":
        return None
    generated = _string_or_none(proposal.get("generated_command") or details.get("generated_command"))
    target = _string_or_none(proposal.get("target"))
    proposal_digest = _string_or_none(proposal.get("logical_command_digest") or details.get("logical_command_digest"))
    if proposal_digest is None and generated is not None and target is not None:
        logical = _logical_command_from_generated_pytest_command(generated, target)
        if logical is not None:
            try:
                proposal_digest = _logical_command_digest(logical)
            except ValueError:
                proposal_digest = None
    provenance_digest = _string_or_none(provenance.get("logical_command_digest"))
    if proposal_digest != expected_digest:
        return None
    if provenance_digest != expected_digest:
        return None
    return PendingActionReference(
        action_id=action_id,
        role=PendingActionRole.VALIDATION,
        action_digest=action_digest,
        action_type="run_shell",
    )


def _initial_validation_checkpoint(
    *,
    workflow_id: str,
    session_id: str,
    selected_digest: str,
    pending_ref: PendingActionReference,
) -> CodingWorkflowCheckpoint:
    now = datetime.now(timezone.utc)
    return CodingWorkflowCheckpoint(
        schema_version=CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V3,
        workflow_id=workflow_id,
        session_id=session_id,
        workflow_kind=CodingWorkflowKind.CONTROLLED_CODING,
        revision=0,
        phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
        selected_validation_command_digest=selected_digest,
        selected_validation_command_digest_algorithm="sha256",
        validation_execution_count=0,
        repair_attempted=False,
        revalidation_attempted=False,
        pending_action_ref=pending_ref,
        last_completed_action_ref=None,
        final_outcome_summary=None,
        completion_marker=None,
        model_continuation_intent=None,
        terminal_outcome=None,
        created_at=now,
        updated_at=now,
    )


def _replace_initial_checkpoint(
    checkpoint: CodingWorkflowCheckpoint,
    *,
    selected_digest: str,
    pending_ref: PendingActionReference,
) -> CodingWorkflowCheckpoint:
    return CodingWorkflowCheckpoint(
        schema_version=checkpoint.schema_version,
        workflow_id=checkpoint.workflow_id,
        session_id=checkpoint.session_id,
        workflow_kind=checkpoint.workflow_kind,
        revision=checkpoint.revision + 1,
        phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
        selected_validation_command_digest=selected_digest,
        selected_validation_command_digest_algorithm="sha256",
        validation_execution_count=0,
        repair_attempted=False,
        revalidation_attempted=False,
        pending_action_ref=pending_ref,
        last_completed_action_ref=None,
        final_outcome_summary=None,
        completion_marker=None,
        model_continuation_intent=None,
        terminal_outcome=None,
        created_at=checkpoint.created_at,
        updated_at=datetime.now(timezone.utc),
    )


def _active_pending_action(action: dict[str, Any]) -> bool:
    lifecycle = _as_mapping(action.get("lifecycle"))
    state = str(lifecycle.get("state") or "staged_not_granted")
    if state not in {"staged_not_granted", "grant_attached"}:
        return False
    expires_at = action.get("expires_at")
    return not isinstance(expires_at, (int, float)) or expires_at <= 0 or time.time() <= float(expires_at)


def _logical_command_from_generated_pytest_command(generated: str, target: str) -> str | None:
    parts = generated.split()
    if not parts or not target:
        return None
    if parts[:3] in (["python", "-m", "pytest"], ["python3", "-m", "pytest"], ["py", "-m", "pytest"]):
        prefix = f"{parts[0]} -m pytest"
        rest = parts[3:]
    elif parts[:1] == ["pytest"]:
        prefix = "pytest"
        rest = parts[1:]
    else:
        return None
    if not rest or rest[0] != target:
        return None
    quiet = len(rest) > 1 and rest[1] == "-q"
    return f"{prefix} {target}{' -q' if quiet else ''}"


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


def _blocked_lookup_observation(
    selection: SelectedValidationCommand,
    evidence_type: str,
    status: str,
    reason: str,
) -> ValidationObservation:
    failure_kind = f"{evidence_type}_{status}"
    details: dict[str, object] = {"failure_kind": failure_kind}
    if reason:
        details["failure_reason_code"] = reason
    return validation_observation_from_result_details(
        selection,
        details,
        execution_status="blocked",
        failure_kind=failure_kind,
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


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _external_identity_failure(
    external: ExternalResultEvidenceDetails,
    reference: SessionEvidenceReference,
    expected_logical_command_digest: str,
) -> str | None:
    if external.session_id != reference.session_id:
        return "session_id_mismatch"
    if external.action_id != reference.action_id:
        return "action_id_mismatch"
    if external.message_id != reference.message_id:
        return "message_id_mismatch"
    if external.result_digest != reference.result_digest:
        return "result_digest_mismatch"
    if external.logical_command_digest != expected_logical_command_digest:
        return "logical_command_digest_mismatch"
    return None


def _provenance_request_identity_failure(
    request: PytestProvenanceRequestEvidence,
    reference: SessionEvidenceReference,
    expected_logical_command_digest: str,
) -> str | None:
    if request.session_id != reference.session_id:
        return "provenance_session_id_mismatch"
    if request.action_id != reference.action_id:
        return "provenance_action_id_mismatch"
    if request.message_id != reference.message_id:
        return "provenance_message_id_mismatch"
    if request.result_digest != reference.result_digest:
        return "provenance_result_digest_mismatch"
    if request.logical_command_digest != expected_logical_command_digest:
        return "provenance_logical_command_digest_mismatch"
    return None


def _observation_from_validation_evidence(
    selection: SelectedValidationCommand,
    external: ExternalResultEvidenceDetails,
    evidence: SessionValidationEvidence,
) -> ValidationObservation:
    provenance = PytestProvenanceVerification(
        status=evidence.pytest_provenance_status,  # type: ignore[arg-type]
        category=evidence.pytest_completion_category,  # type: ignore[arg-type]
        pytest_exit_status=evidence.pytest_exit_status,
        failure_kind=evidence.failure_reason_code,
    )
    if evidence.execution_status == "blocked":
        return validation_observation_from_result_details(
            selection,
            external.details,
            execution_status="blocked",
            failure_kind=evidence.failure_reason_code,
        )
    return validation_observation_from_result_details(
        selection,
        external.details,
        validation_status=evidence.validation_status,  # type: ignore[arg-type]
        failure_kind=evidence.failure_reason_code,
        pytest_provenance=provenance,
    )


def _validation_evidence_from_observation(
    *,
    session_id: str | None,
    action_id: str,
    external_result_digest: str,
    selection: SelectedValidationCommand,
    observation: ValidationObservation,
) -> SessionValidationEvidence | None:
    if session_id is None or not selection.normalized_command:
        return None
    if observation.pytest_provenance_status is None:
        return None
    message_id = f"validation-evidence-{action_id}"
    return SessionValidationEvidence(
        session_id=session_id,
        action_id=action_id,
        external_result_digest=external_result_digest,
        logical_command_digest=_logical_command_digest(selection.normalized_command),
        execution_status=observation.execution_status,
        validation_status=observation.validation_status,
        pytest_provenance_status=observation.pytest_provenance_status,
        pytest_completion_category=observation.pytest_completion_category,
        pytest_exit_status=observation.pytest_exit_status,
        failure_reason_code=observation.failure_kind,
        completed_at=time.time(),
        evidence_message_id=message_id,
    )


def _logical_command_digest(command: str) -> str:
    from pp_agent.coding.pytest_provenance import logical_command_digest

    return logical_command_digest(command)
