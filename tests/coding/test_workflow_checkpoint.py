from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import builtins
import json
import subprocess

import pytest

from pp_agent.coding import (
    CODING_WORKFLOW_CHECKPOINT_DIGEST_ALGORITHM,
    CODING_WORKFLOW_CHECKPOINT_INITIAL_REVISION,
    CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION,
    CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V2,
    CheckpointValidationError,
    CodingWorkflowCheckpoint,
    CodingWorkflowCompletion,
    CodingWorkflowKind,
    CodingWorkflowPhase,
    ModelContinuationIntent,
    ModelContinuationState,
    PendingActionReference,
    PendingActionRole,
    SessionCompletionEvidenceReference,
    ValidationFinalStatus,
    ValidationOutcomeSummary,
    checkpoint_from_dict,
    checkpoint_integrity_digest,
    checkpoint_to_canonical_json,
    next_checkpoint_revision,
)


DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64


def _now() -> datetime:
    return datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def _minimal(**overrides: object) -> CodingWorkflowCheckpoint:
    values: dict[str, object] = {
        "schema_version": CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION,
        "workflow_id": "workflow-1",
        "session_id": "session-1",
        "workflow_kind": CodingWorkflowKind.CONTROLLED_CODING,
        "revision": CODING_WORKFLOW_CHECKPOINT_INITIAL_REVISION,
        "phase": CodingWorkflowPhase.PREPARED,
        "validation_execution_count": 0,
        "repair_attempted": False,
        "revalidation_attempted": False,
        "created_at": _now(),
        "updated_at": _now(),
    }
    values.update(overrides)
    return CodingWorkflowCheckpoint(**values)  # type: ignore[arg-type]


def _completed(**overrides: object) -> CodingWorkflowCheckpoint:
    values: dict[str, object] = {
        "phase": CodingWorkflowPhase.COMPLETED,
        "selected_validation_command_digest": DIGEST,
        "selected_validation_command_digest_algorithm": CODING_WORKFLOW_CHECKPOINT_DIGEST_ALGORITHM,
        "validation_execution_count": 1,
        "final_outcome_summary": ValidationOutcomeSummary(
            final_status=ValidationFinalStatus.PASSED,
            repair_attempted=False,
            revalidation_attempted=False,
        ),
        "completion_marker": CodingWorkflowCompletion(completed_at=_now()),
    }
    values.update(overrides)
    return _minimal(**values)


def _with_integrity(checkpoint: CodingWorkflowCheckpoint) -> CodingWorkflowCheckpoint:
    return CodingWorkflowCheckpoint(
        **{
            **checkpoint.to_dict(include_integrity=False),
            "workflow_kind": checkpoint.workflow_kind,
            "phase": checkpoint.phase,
            "pending_action_ref": checkpoint.pending_action_ref,
            "last_completed_action_ref": checkpoint.last_completed_action_ref,
            "final_outcome_summary": checkpoint.final_outcome_summary,
            "completion_marker": checkpoint.completion_marker,
            "model_continuation_intent": checkpoint.model_continuation_intent,
            "created_at": checkpoint.created_at,
            "updated_at": checkpoint.updated_at,
            "integrity_digest": checkpoint_integrity_digest(checkpoint),
        }
    )


def test_minimal_legal_checkpoint_is_immutable_and_json_safe() -> None:
    checkpoint = _minimal()

    assert checkpoint.workflow_kind == CodingWorkflowKind.CONTROLLED_CODING
    assert checkpoint.phase == CodingWorkflowPhase.PREPARED
    assert checkpoint.revision == 0
    with pytest.raises(FrozenInstanceError):
        checkpoint.revision = 2  # type: ignore[misc]
    json.dumps(checkpoint.to_dict(), sort_keys=True)


def test_full_completed_checkpoint_has_terminal_contract() -> None:
    checkpoint = _completed()

    assert checkpoint.phase == CodingWorkflowPhase.COMPLETED
    assert checkpoint.final_outcome_summary is not None
    assert checkpoint.completion_marker is not None
    assert checkpoint.pending_action_ref is None


def test_pending_reference_is_safe_and_role_checked() -> None:
    ref = PendingActionReference(
        action_id="effect-1",
        action_digest=DIGEST,
        role=PendingActionRole.VALIDATION,
        action_type="run_shell",
    )
    checkpoint = _minimal(
        phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL,
        selected_validation_command_digest=DIGEST,
        selected_validation_command_digest_algorithm=CODING_WORKFLOW_CHECKPOINT_DIGEST_ALGORITHM,
        pending_action_ref=ref,
    )

    assert checkpoint.pending_action_ref == ref
    assert "token" not in checkpoint.to_dict()["pending_action_ref"]  # type: ignore[operator]


def test_nested_enum_values_must_be_typed_when_constructed_directly() -> None:
    with pytest.raises(CheckpointValidationError):
        PendingActionReference(action_id="effect-1", role="tool")  # type: ignore[arg-type]

    with pytest.raises(CheckpointValidationError):
        ValidationOutcomeSummary(
            final_status="passed",  # type: ignore[arg-type]
            repair_attempted=False,
            revalidation_attempted=False,
        )


def test_revision_helper_rejects_bool_and_negative_values() -> None:
    assert next_checkpoint_revision(0) == 1
    with pytest.raises(CheckpointValidationError):
        next_checkpoint_revision(-1)
    with pytest.raises(CheckpointValidationError):
        next_checkpoint_revision(True)  # type: ignore[arg-type]


@pytest.mark.parametrize("version", [None, "1", 0, 3])
def test_schema_version_must_be_current_integer(version: object) -> None:
    payload = _minimal().to_dict()
    if version is None:
        payload.pop("schema_version")
    else:
        payload["schema_version"] = version

    with pytest.raises(CheckpointValidationError):
        checkpoint_from_dict(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("workflow_id", ""),
        ("session_id", ""),
        ("workflow_id", "x" * 129),
        ("workflow_kind", "generic"),
        ("phase", "awaiting_unknown"),
        ("revision", -1),
        ("revision", True),
        ("validation_execution_count", -1),
        ("validation_execution_count", 3),
        ("selected_validation_command_digest", "not-a-digest"),
    ],
)
def test_invalid_scalar_fields_fail_closed(field: str, value: object) -> None:
    payload = _minimal().to_dict()
    payload[field] = value
    if field == "selected_validation_command_digest":
        payload["selected_validation_command_digest_algorithm"] = CODING_WORKFLOW_CHECKPOINT_DIGEST_ALGORITHM

    with pytest.raises(CheckpointValidationError):
        checkpoint_from_dict(payload)


def test_naive_timestamp_and_created_after_updated_are_rejected() -> None:
    with pytest.raises(CheckpointValidationError):
        _minimal(created_at=datetime(2026, 1, 2, 3, 4, 5))
    with pytest.raises(CheckpointValidationError):
        _minimal(created_at=_now() + timedelta(seconds=1), updated_at=_now())


def test_unknown_fields_and_sensitive_fields_fail_closed() -> None:
    payload = _minimal().to_dict()
    payload["future"] = "value"
    with pytest.raises(CheckpointValidationError):
        checkpoint_from_dict(payload)

    payload = _minimal().to_dict()
    payload["token"] = "secret"
    with pytest.raises(CheckpointValidationError):
        checkpoint_from_dict(payload)


def test_malformed_nested_structures_fail_closed() -> None:
    payload = _minimal().to_dict()
    payload["phase"] = "awaiting_tool_approval"
    payload["pending_action_ref"] = "not-object"
    with pytest.raises(CheckpointValidationError):
        checkpoint_from_dict(payload)

    payload = _completed().to_dict()
    payload["final_outcome_summary"] = {"stdout": "leak"}
    with pytest.raises(CheckpointValidationError):
        checkpoint_from_dict(payload)


def test_revalidation_requires_repair_and_validation_count_consistency() -> None:
    with pytest.raises(CheckpointValidationError):
        _minimal(revalidation_attempted=True, validation_execution_count=1)
    with pytest.raises(CheckpointValidationError):
        _minimal(validation_execution_count=2, revalidation_attempted=False)
    with pytest.raises(CheckpointValidationError):
        _minimal(repair_attempted=True, revalidation_attempted=True, validation_execution_count=0)


def test_repair_and_revalidation_phases_require_matching_flags() -> None:
    with pytest.raises(CheckpointValidationError):
        _minimal(
            phase=CodingWorkflowPhase.REPAIR_STARTED,
            selected_validation_command_digest=DIGEST,
            selected_validation_command_digest_algorithm=CODING_WORKFLOW_CHECKPOINT_DIGEST_ALGORITHM,
            validation_execution_count=1,
            repair_attempted=False,
        )
    with pytest.raises(CheckpointValidationError):
        _minimal(
            phase=CodingWorkflowPhase.AWAITING_REVALIDATION_APPROVAL,
            selected_validation_command_digest=DIGEST,
            selected_validation_command_digest_algorithm=CODING_WORKFLOW_CHECKPOINT_DIGEST_ALGORITHM,
            validation_execution_count=1,
            repair_attempted=True,
            revalidation_attempted=False,
            pending_action_ref=PendingActionReference(action_id="effect-1", role=PendingActionRole.REVALIDATION),
        )


def test_pending_action_reference_must_match_awaiting_phase_role() -> None:
    with pytest.raises(CheckpointValidationError):
        _minimal(phase=CodingWorkflowPhase.AWAITING_TOOL_APPROVAL)
    with pytest.raises(CheckpointValidationError):
        _minimal(
            phase=CodingWorkflowPhase.AWAITING_TOOL_APPROVAL,
            pending_action_ref=PendingActionReference(action_id="effect-1", role=PendingActionRole.VALIDATION),
        )
    with pytest.raises(CheckpointValidationError):
        _minimal(pending_action_ref=PendingActionReference(action_id="effect-1", role=PendingActionRole.TOOL))


def test_completed_requires_outcome_marker_and_no_pending_action() -> None:
    with pytest.raises(CheckpointValidationError):
        _minimal(phase=CodingWorkflowPhase.COMPLETED)
    with pytest.raises(CheckpointValidationError):
        _completed(completion_marker=None)
    with pytest.raises(CheckpointValidationError):
        _completed(pending_action_ref=PendingActionReference(action_id="effect-1", role=PendingActionRole.TOOL))


def test_non_completed_cannot_have_completion_marker_or_final_outcome() -> None:
    with pytest.raises(CheckpointValidationError):
        _minimal(completion_marker=CodingWorkflowCompletion(completed_at=_now()))
    with pytest.raises(CheckpointValidationError):
        _minimal(
            validation_execution_count=1,
            final_outcome_summary=ValidationOutcomeSummary(
                final_status=ValidationFinalStatus.PASSED,
                repair_attempted=False,
                revalidation_attempted=False,
            ),
        )


def test_selected_command_digest_required_once_validation_starts() -> None:
    with pytest.raises(CheckpointValidationError):
        _minimal(validation_execution_count=1)
    with pytest.raises(CheckpointValidationError):
        _minimal(phase=CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL)


def test_round_trip_deterministic_mapping_and_timestamp_format() -> None:
    checkpoint = _with_integrity(_completed())
    payload = checkpoint.to_dict()
    restored = checkpoint_from_dict(payload)

    assert restored == checkpoint
    assert payload == restored.to_dict()
    assert payload["workflow_kind"] == "controlled_coding"
    assert payload["phase"] == "completed"
    assert str(payload["created_at"]).endswith("Z")
    assert checkpoint_to_canonical_json(checkpoint) == checkpoint_to_canonical_json(restored)


def test_integrity_digest_detects_tampering() -> None:
    checkpoint = _with_integrity(_completed())
    payload = checkpoint.to_dict()

    payload["revision"] = 99

    with pytest.raises(CheckpointValidationError):
        checkpoint_from_dict(payload)


def test_optional_fields_are_serialized_as_json_primitives() -> None:
    payload = _minimal().to_dict()

    assert payload["pending_action_ref"] is None
    assert payload["final_outcome_summary"] is None
    assert json.loads(checkpoint_to_canonical_json(_minimal()))["phase"] == "prepared"
    assert "model_continuation_intent" not in payload


def _action_ref() -> PendingActionReference:
    return PendingActionReference(
        action_id="effect-1",
        action_digest=DIGEST,
        role=PendingActionRole.TOOL,
        action_type="run_shell",
    )


def _intent(**overrides: object) -> ModelContinuationIntent:
    values: dict[str, object] = {
        "continuation_id": "cont-1",
        "source_action_ref": _action_ref(),
        "source_result_digest": OTHER_DIGEST,
        "pre_call_session_id": "session-1",
        "pre_call_turn_id": "turn-1",
        "state": ModelContinuationState.INTENT_COMMITTED,
        "created_at": _now(),
    }
    values.update(overrides)
    return ModelContinuationIntent(**values)  # type: ignore[arg-type]


def _minimal_v2(**overrides: object) -> CodingWorkflowCheckpoint:
    return _minimal(schema_version=CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V2, **overrides)


def test_v1_canonical_serialization_is_frozen_without_v2_fields() -> None:
    checkpoint = _minimal()

    assert checkpoint_to_canonical_json(checkpoint) == (
        '{"completion_marker":null,"created_at":"2026-01-02T03:04:05Z",'
        '"final_outcome_summary":null,"integrity_digest":null,"last_completed_action_ref":null,'
        '"pending_action_ref":null,"phase":"prepared","repair_attempted":false,'
        '"revalidation_attempted":false,"revision":0,"schema_version":1,"selected_validation_command_digest":null,'
        '"selected_validation_command_digest_algorithm":null,"session_id":"session-1",'
        '"updated_at":"2026-01-02T03:04:05Z","validation_execution_count":0,'
        '"workflow_id":"workflow-1","workflow_kind":"controlled_coding"}'
    )


def test_v1_rejects_v2_continuation_field() -> None:
    payload = _minimal().to_dict()
    payload["model_continuation_intent"] = None

    with pytest.raises(CheckpointValidationError):
        checkpoint_from_dict(payload)


def test_v2_minimal_round_trip_and_integrity() -> None:
    checkpoint = _with_integrity(_minimal_v2())
    restored = checkpoint_from_dict(checkpoint.to_dict())

    assert restored == checkpoint
    assert restored.schema_version == CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V2
    assert "model_continuation_intent" in restored.to_dict()
    assert checkpoint_to_canonical_json(restored) == checkpoint_to_canonical_json(checkpoint)


def test_v2_minimal_continuation_intent_round_trip() -> None:
    checkpoint = _minimal_v2(
        phase=CodingWorkflowPhase.TOOL_COMPLETED,
        last_completed_action_ref=_action_ref(),
        model_continuation_intent=_intent(),
    )

    restored = checkpoint_from_dict(checkpoint.to_dict())

    assert restored.model_continuation_intent == checkpoint.model_continuation_intent
    assert restored.to_dict()["model_continuation_intent"] is not None


def test_v2_session_committed_requires_matching_completion_evidence() -> None:
    evidence = SessionCompletionEvidenceReference(
        session_id="session-1",
        continuation_id="cont-1",
        source_action_id="effect-1",
        source_result_digest=OTHER_DIGEST,
        committed_turn_id="turn-2",
    )
    checkpoint = _minimal_v2(
        phase=CodingWorkflowPhase.TOOL_COMPLETED,
        last_completed_action_ref=_action_ref(),
        model_continuation_intent=_intent(
            state=ModelContinuationState.SESSION_COMMITTED,
            completed_session_evidence_ref=evidence,
        ),
    )

    assert checkpoint.model_continuation_intent is not None
    assert checkpoint.model_continuation_intent.completed_session_evidence_ref == evidence

    with pytest.raises(CheckpointValidationError):
        _intent(state=ModelContinuationState.SESSION_COMMITTED)


def test_v2_blocked_uncertain_requires_reason_and_has_no_retry_semantics() -> None:
    checkpoint = _minimal_v2(
        phase=CodingWorkflowPhase.TOOL_COMPLETED,
        last_completed_action_ref=_action_ref(),
        model_continuation_intent=_intent(
            state=ModelContinuationState.BLOCKED_UNCERTAIN,
            blocked_reason_code="session_evidence_missing",
        ),
    )

    assert checkpoint.model_continuation_intent is not None
    assert checkpoint.model_continuation_intent.blocked_reason_code == "session_evidence_missing"

    with pytest.raises(CheckpointValidationError):
        _intent(state=ModelContinuationState.BLOCKED_UNCERTAIN)


@pytest.mark.parametrize(
    "overrides",
    [
        {"continuation_id": ""},
        {"continuation_id": "x" * 129},
        {"continuation_id": "workflow-1"},
        {"source_result_digest": None},
        {"source_action_ref": None},
        {"state": "retry"},
    ],
)
def test_v2_intent_rejects_invalid_identity_and_missing_evidence(overrides: dict[str, object]) -> None:
    with pytest.raises(CheckpointValidationError):
        _intent(**overrides)


def test_v2_checkpoint_rejects_inconsistent_continuation_cross_fields() -> None:
    with pytest.raises(CheckpointValidationError):
        _minimal_v2(model_continuation_intent=_intent())

    with pytest.raises(CheckpointValidationError):
        _minimal_v2(
            phase=CodingWorkflowPhase.TOOL_COMPLETED,
            last_completed_action_ref=_action_ref(),
            pending_action_ref=_action_ref(),
            model_continuation_intent=_intent(),
        )

    with pytest.raises(CheckpointValidationError):
        _minimal_v2(
            phase=CodingWorkflowPhase.TOOL_COMPLETED,
            last_completed_action_ref=PendingActionReference(action_id="effect-2", role=PendingActionRole.TOOL),
            model_continuation_intent=_intent(),
        )

    with pytest.raises(CheckpointValidationError):
        _completed(
            schema_version=CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V2,
            last_completed_action_ref=_action_ref(),
            model_continuation_intent=_intent(),
        )


def test_v2_rejects_sensitive_continuation_payload_fields() -> None:
    payload = _minimal_v2(
        phase=CodingWorkflowPhase.TOOL_COMPLETED,
        last_completed_action_ref=_action_ref(),
        model_continuation_intent=_intent(),
    ).to_dict()
    intent = payload["model_continuation_intent"]
    assert isinstance(intent, dict)
    intent["stdout"] = "secret output"

    with pytest.raises(CheckpointValidationError):
        checkpoint_from_dict(payload)


def test_scope_protection_no_io_store_runtime_or_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args, **_kwargs):  # pragma: no cover - should never run
        raise AssertionError("contract validation must not perform side effects")

    monkeypatch.setattr(builtins, "open", fail)
    monkeypatch.setattr(subprocess, "run", fail)

    checkpoint = _minimal()

    assert checkpoint.phase == CodingWorkflowPhase.PREPARED
    assert checkpoint.to_dict()["schema_version"] == CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION
