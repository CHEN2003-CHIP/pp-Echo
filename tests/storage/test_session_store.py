from pathlib import Path

import pytest
from typing import Optional

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.llm import ModelConfig
from pp_agent.storage.sessions import (
    SESSION_CORRELATION_KEY,
    SESSION_MESSAGE_ID_KEY,
    SESSION_VALIDATION_EVIDENCE_KEY,
    SessionEvidenceLookupStatus,
    SessionStore,
    SessionValidationEvidence,
    SessionValidationEvidenceConflict,
    build_external_tool_result_correlation,
    build_model_continuation_completion_correlation,
    build_session_result_digest,
    ensure_session_message_id,
)


def test_session_store_save_and_load_uses_per_session_jsonl_file(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    record.metadata.compaction.summary = "old messages"
    record.metadata.compaction.summarized_message_count = 2
    saved_path = store.save(record)

    assert saved_path.exists()
    assert saved_path.name == f"{record.id}.jsonl"
    loaded = store.load(record.id)
    assert loaded.id == record.id
    assert loaded.system_prompt == "hello"
    assert loaded.model.model == record.model.model
    assert loaded.compaction.summary == "old messages"


def test_external_tool_result_evidence_lookup_survives_reload(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    digest = build_session_result_digest({"result": "ok", "success": True, "token": "secret-token"})
    message = ChatMessage(
        role="tool",
        tool_call_id="call-1",
        tool_name="approve_pending_action",
        content=[TextPart(text="ok")],
        timestamp=2.0,
    )
    ensure_session_message_id(message)
    message.metadata[SESSION_CORRELATION_KEY] = build_external_tool_result_correlation(
        action_id="action-1",
        result_digest=digest,
        tool_name="approve_pending_action",
        completed_at=2.0,
        turn_id="turn-1",
    )
    record.messages = [ChatMessage(role="user", content=[TextPart(text="u")], timestamp=1.0), message]
    store.save(record)

    loaded = store.load(record.id)
    result = store.lookup_external_tool_result_evidence(record.id, action_id="action-1", result_digest=digest)

    assert loaded.messages[1].metadata[SESSION_MESSAGE_ID_KEY] == message.metadata[SESSION_MESSAGE_ID_KEY]
    assert "secret-token" not in digest
    assert result.status == SessionEvidenceLookupStatus.FOUND
    assert result.evidence is not None
    assert result.evidence.action_id == "action-1"
    assert result.evidence.result_digest == digest


def test_external_tool_result_lookup_fails_closed_for_mismatch_and_duplicates(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    digest = build_session_result_digest({"result": "ok"})
    other_digest = build_session_result_digest({"result": "different"})

    def correlated_message(message_id: str) -> ChatMessage:
        message = ChatMessage(
            role="tool",
            tool_call_id=message_id,
            tool_name="approve_pending_action",
            content=[TextPart(text="ok")],
            metadata={SESSION_MESSAGE_ID_KEY: message_id},
            timestamp=2.0,
        )
        message.metadata[SESSION_CORRELATION_KEY] = build_external_tool_result_correlation(
            action_id="action-1",
            result_digest=digest,
            tool_name="approve_pending_action",
            completed_at=2.0,
        )
        return message

    record.messages = [correlated_message("msg-one"), correlated_message("msg-two")]
    store.save(record)

    duplicate = store.lookup_external_tool_result_evidence(record.id, action_id="action-1", result_digest=digest)
    mismatch = store.lookup_external_tool_result_evidence(record.id, action_id="action-1", result_digest=other_digest)

    assert duplicate.status == SessionEvidenceLookupStatus.AMBIGUOUS
    assert mismatch.status == SessionEvidenceLookupStatus.IDENTITY_MISMATCH


def _external_result_message(
    *,
    action_id: str = "action-1",
    message_id: str = "msg-result",
    result_digest: Optional[str] = None,
    content: str = "ok",
    tool_details: Optional[dict] = None,
    completed_at: object = 2.0,
) -> ChatMessage:
    digest = result_digest or build_session_result_digest({"result": content, "action_id": action_id})
    message = ChatMessage(
        role="tool",
        tool_call_id="call-1",
        tool_name="approve_pending_action",
        content=[TextPart(text=content)],
        metadata={SESSION_MESSAGE_ID_KEY: message_id},
        timestamp=2.0,
    )
    message.metadata[SESSION_CORRELATION_KEY] = {
        **build_external_tool_result_correlation(
            action_id=action_id,
            result_digest=digest,
            tool_name="approve_pending_action",
            completed_at=2.0,
            turn_id="turn-1",
        ),
        "completed_at": completed_at,
    }
    if tool_details is not None:
        message.metadata["tool_details"] = tool_details
    return message


def _external_result_reference(store: SessionStore, session_id: str, *, action_id: str = "action-1", result_digest: str) -> object:
    lookup = store.lookup_external_tool_result_evidence(session_id, action_id=action_id, result_digest=result_digest)
    assert lookup.status == SessionEvidenceLookupStatus.FOUND
    assert lookup.evidence is not None
    return lookup.evidence


def test_external_result_details_lookup_returns_bounded_typed_record(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    digest = build_session_result_digest({"result": "ok", "action_id": "action-1"})
    long_stdout = "x" * 5000
    record.messages = [
        _external_result_message(
            result_digest=digest,
            content="ok",
            tool_details={
                "action_type": "run_shell",
                "success": True,
                "lifecycle": {"state": "grant_consumed", "token": "secret-token"},
                "result_details": {
                    "exit_code": 0,
                    "stdout": long_stdout,
                    "stderr": "err",
                    "token": "secret-token",
                    "nonce": "secret-nonce",
                    "pytest_provenance_request": {
                        "schema_version": 1,
                        "plugin_id": "pytest-plugin",
                        "plugin_version": "1",
                        "logical_command_digest": "a" * 64,
                        "nonce": "secret-nonce",
                        "artifact_relative_path": ".pp-agent/validation-provenance/secret.json",
                    },
                },
            },
        )
    ]
    store.save(record)
    reference = _external_result_reference(store, record.id, result_digest=digest)

    result = store.lookup_external_result_details(reference)

    assert result.status == SessionEvidenceLookupStatus.FOUND
    assert result.details is not None
    assert result.details.session_id == record.id
    assert result.details.action_id == "action-1"
    assert result.details.message_id == reference.message_id
    assert result.details.result_digest == digest
    assert result.details.action_type == "run_shell"
    assert result.details.logical_command_digest == "a" * 64
    assert result.details.details["exit_code"] == 0
    assert len(str(result.details.details["stdout"])) == 4000
    assert result.details.provenance_request == {
        "logical_command_digest": "a" * 64,
        "plugin_id": "pytest-plugin",
        "plugin_version": "1",
        "schema_version": 1,
    }
    rendered = result.model_dump_json()
    assert "secret-token" not in rendered
    assert "secret-nonce" not in rendered
    assert "validation-provenance" not in rendered
    assert not isinstance(result.details, ChatMessage)


def test_external_result_details_lookup_identity_failures(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    digest = build_session_result_digest({"result": "ok", "action_id": "action-1"})
    record.messages = [_external_result_message(result_digest=digest)]
    store.save(record)
    reference = _external_result_reference(store, record.id, result_digest=digest)

    session_missing = store.lookup_external_result_details(reference.model_copy(update={"session_id": "missing-session"}))
    action_mismatch = store.lookup_external_result_details(reference.model_copy(update={"action_id": "action-2"}))
    message_mismatch = store.lookup_external_result_details(reference.model_copy(update={"message_id": "msg-missing"}))
    digest_mismatch = store.lookup_external_result_details(
        reference.model_copy(update={"result_digest": build_session_result_digest({"result": "different"})})
    )

    assert session_missing.status == SessionEvidenceLookupStatus.SESSION_MISSING
    assert action_mismatch.status == SessionEvidenceLookupStatus.IDENTITY_MISMATCH
    assert message_mismatch.status == SessionEvidenceLookupStatus.IDENTITY_MISMATCH
    assert digest_mismatch.status == SessionEvidenceLookupStatus.IDENTITY_MISMATCH


def test_external_result_details_lookup_missing_ambiguous_and_corrupt_records(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    digest = build_session_result_digest({"result": "ok", "action_id": "action-1"})
    missing_reference = _external_result_message(result_digest=digest)
    record.messages = []
    store.save(record)
    valid_ref = _external_result_reference_for_test(record.id, "msg-result", "action-1", digest)

    missing = store.lookup_external_result_details(valid_ref)

    record.messages = [
        _external_result_message(result_digest=digest),
        _external_result_message(result_digest=digest),
    ]
    store.save(record)
    ambiguous = store.lookup_external_result_details(valid_ref)

    record.messages = [_external_result_message(result_digest=digest, completed_at="bad")]
    store.save(record)
    corrupt = store.lookup_external_result_details(valid_ref)

    assert missing_reference
    assert missing.status == SessionEvidenceLookupStatus.NOT_FOUND
    assert ambiguous.status == SessionEvidenceLookupStatus.AMBIGUOUS
    assert corrupt.status == SessionEvidenceLookupStatus.SESSION_CORRUPT


def _external_result_reference_for_test(session_id: str, message_id: str, action_id: str, result_digest: str):
    from pp_agent.storage.sessions import SessionEvidenceReference

    return SessionEvidenceReference(
        session_id=session_id,
        message_id=message_id,
        turn_id="turn-1",
        correlation_kind="external_tool_result",
        correlation_id=action_id,
        action_id=action_id,
        result_digest=result_digest,
        tool_name="approve_pending_action",
        completed_at=2.0,
    )


def test_external_result_details_lookup_survives_reload_and_supports_legacy_correlated_record(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    digest = build_session_result_digest({"result": "legacy", "action_id": "action-1"})
    record.messages = [_external_result_message(result_digest=digest, content="legacy", tool_details=None)]
    store.save(record)
    reference = _external_result_reference(store, record.id, result_digest=digest)

    result = SessionStore(tmp_path).lookup_external_result_details(reference)

    assert result.status == SessionEvidenceLookupStatus.FOUND
    assert result.details is not None
    assert result.details.result == "legacy"
    assert result.details.details == {}
    assert result.details.provenance_request == {}


def _pytest_tool_details(
    *,
    nonce: str = "a" * 32,
    logical_command_digest: str = "b" * 64,
    artifact_relative_path: str = ".pp-agent/validation-provenance/artifact.json",
    include_request: bool = True,
    extra_result_details: Optional[dict] = None,
) -> dict:
    result_details = {
        "exit_code": 1,
        "stdout": "FAILED\n",
        "stderr": "err\n",
        "logical_command_digest": logical_command_digest,
        **(extra_result_details or {}),
    }
    if include_request:
        result_details["pytest_provenance_request"] = {
            "schema_version": 1,
            "plugin_id": "pp_agent.coding.pytest_provenance_plugin",
            "plugin_version": "1",
            "nonce": nonce,
            "logical_command_digest": logical_command_digest,
            "artifact_relative_path": artifact_relative_path,
        }
    return {
        "action_type": "run_shell",
        "success": True,
        "result_details": result_details,
        "lifecycle": {"state": "grant_consumed"},
    }


def test_pytest_provenance_request_lookup_returns_verifier_only_typed_input(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    digest = build_session_result_digest({"result": "pytest", "action_id": "action-1"})
    record.messages = [_external_result_message(result_digest=digest, tool_details=_pytest_tool_details())]
    store.save(record)
    reference = _external_result_reference(store, record.id, result_digest=digest)

    result = store.lookup_pytest_provenance_request(reference)

    assert result.status == SessionEvidenceLookupStatus.FOUND
    assert result.request is not None
    assert result.request.session_id == record.id
    assert result.request.action_id == "action-1"
    assert result.request.message_id == reference.message_id
    assert result.request.result_digest == digest
    assert result.request.nonce == "a" * 32
    assert result.request.logical_command_digest == "b" * 64
    assert result.request.artifact_relative_path == ".pp-agent/validation-provenance/artifact.json"
    assert result.request.plugin_id == "pp_agent.coding.pytest_provenance_plugin"
    rendered = result.model_dump_json()
    assert "stdout" not in rendered
    assert "stderr" not in rendered
    assert "token" not in rendered
    assert "ChatMessage" not in rendered
    assert "metadata" not in rendered


def test_pytest_provenance_request_lookup_identity_failures(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    digest = build_session_result_digest({"result": "pytest", "action_id": "action-1"})
    record.messages = [_external_result_message(result_digest=digest, tool_details=_pytest_tool_details())]
    store.save(record)
    reference = _external_result_reference(store, record.id, result_digest=digest)

    session_missing = store.lookup_pytest_provenance_request(reference.model_copy(update={"session_id": "missing-session"}))
    action_mismatch = store.lookup_pytest_provenance_request(reference.model_copy(update={"action_id": "action-2"}))
    message_mismatch = store.lookup_pytest_provenance_request(reference.model_copy(update={"message_id": "msg-missing"}))
    digest_mismatch = store.lookup_pytest_provenance_request(
        reference.model_copy(update={"result_digest": build_session_result_digest({"result": "different"})})
    )

    assert session_missing.status == SessionEvidenceLookupStatus.SESSION_MISSING
    assert action_mismatch.status == SessionEvidenceLookupStatus.IDENTITY_MISMATCH
    assert message_mismatch.status == SessionEvidenceLookupStatus.IDENTITY_MISMATCH
    assert digest_mismatch.status == SessionEvidenceLookupStatus.IDENTITY_MISMATCH


def test_pytest_provenance_request_lookup_rejects_command_digest_mismatch(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    digest = build_session_result_digest({"result": "pytest", "action_id": "action-1"})
    record.messages = [
        _external_result_message(
            result_digest=digest,
            tool_details=_pytest_tool_details(
                logical_command_digest="b" * 64,
                extra_result_details={"logical_command_digest": "c" * 64},
            ),
        )
    ]
    store.save(record)
    reference = _external_result_reference(store, record.id, result_digest=digest)

    result = store.lookup_pytest_provenance_request(reference)

    assert result.status == SessionEvidenceLookupStatus.INVALID_PROVENANCE_REQUEST
    assert result.reason == "logical_command_digest_mismatch"


@pytest.mark.parametrize(
    ("request_update", "expected_reason"),
    [
        ({}, "pytest_provenance_request_missing"),
        ({"nonce": "not-a-nonce"}, "invalid_provenance_nonce"),
        ({"artifact_relative_path": "/abs/path.json"}, "pytest_provenance_artifact_absolute"),
        ({"artifact_relative_path": ".pp-agent/validation-provenance/../escape.json"}, "pytest_provenance_artifact_traversal"),
        ({"artifact_relative_path": ".pp-agent/other/artifact.json"}, "pytest_provenance_artifact_outside_root"),
    ],
)
def test_pytest_provenance_request_lookup_rejects_missing_or_malformed_request(
    tmp_path: Path,
    request_update: dict,
    expected_reason: str,
) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    digest = build_session_result_digest({"result": "pytest", "action_id": "action-1"})
    tool_details = _pytest_tool_details(include_request=bool(request_update))
    if request_update:
        tool_details["result_details"]["pytest_provenance_request"].update(request_update)
    record.messages = [_external_result_message(result_digest=digest, tool_details=tool_details)]
    store.save(record)
    reference = _external_result_reference(store, record.id, result_digest=digest)

    result = store.lookup_pytest_provenance_request(reference)

    assert result.status == SessionEvidenceLookupStatus.INVALID_PROVENANCE_REQUEST
    assert result.reason == expected_reason


def test_pytest_provenance_request_lookup_handles_ambiguous_corrupt_reload_and_read_only(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    digest = build_session_result_digest({"result": "pytest", "action_id": "action-1"})
    record.messages = [_external_result_message(result_digest=digest, tool_details=_pytest_tool_details())]
    store.save(record)
    reference = _external_result_reference(store, record.id, result_digest=digest)
    session_file = tmp_path / f"{record.id}.jsonl"
    before = session_file.read_text(encoding="utf-8")

    reloaded = SessionStore(tmp_path).lookup_pytest_provenance_request(reference)
    after = session_file.read_text(encoding="utf-8")

    assert reloaded.status == SessionEvidenceLookupStatus.FOUND
    assert after == before

    loaded = store.load(record.id)
    loaded.messages.append(_external_result_message(result_digest=digest, tool_details=_pytest_tool_details()))
    store.save(loaded)
    ambiguous = store.lookup_pytest_provenance_request(reference)
    assert ambiguous.status == SessionEvidenceLookupStatus.AMBIGUOUS

    corrupt_store = SessionStore(tmp_path / "corrupt")
    corrupt = corrupt_store.create("hello", ModelConfig())
    corrupt_path = tmp_path / "corrupt" / f"{corrupt.id}.jsonl"
    corrupt_path.write_text("{not-json\n", encoding="utf-8")
    corrupt_ref = _external_result_reference_for_test(corrupt.id, "msg-result", "action-1", digest)
    corrupt_result = corrupt_store.lookup_pytest_provenance_request(corrupt_ref)
    assert corrupt_result.status == SessionEvidenceLookupStatus.SESSION_CORRUPT


def test_pytest_provenance_request_lookup_does_not_check_artifact_existence(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    digest = build_session_result_digest({"result": "pytest", "action_id": "action-1"})
    missing_artifact = ".pp-agent/validation-provenance/missing.json"
    record.messages = [
        _external_result_message(
            result_digest=digest,
            tool_details=_pytest_tool_details(artifact_relative_path=missing_artifact),
        )
    ]
    store.save(record)
    reference = _external_result_reference(store, record.id, result_digest=digest)

    result = store.lookup_pytest_provenance_request(reference)

    assert result.status == SessionEvidenceLookupStatus.FOUND
    assert result.request is not None
    assert result.request.artifact_relative_path == missing_artifact
    assert not (tmp_path / missing_artifact).exists()


def test_external_result_details_lookup_still_hides_verifier_only_fields(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    digest = build_session_result_digest({"result": "pytest", "action_id": "action-1"})
    record.messages = [_external_result_message(result_digest=digest, tool_details=_pytest_tool_details())]
    store.save(record)
    reference = _external_result_reference(store, record.id, result_digest=digest)

    result = store.lookup_external_result_details(reference)

    assert result.status == SessionEvidenceLookupStatus.FOUND
    rendered = result.model_dump_json()
    assert "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in rendered
    assert "artifact.json" not in rendered
    assert "validation-provenance" not in rendered


def test_legacy_tool_message_is_insufficient_recovery_evidence(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    record.messages = [
        ChatMessage(role="tool", tool_call_id="call-1", tool_name="approve_pending_action", content=[TextPart(text="ok")], timestamp=1.0)
    ]
    store.save(record)

    result = store.lookup_external_tool_result_evidence(record.id, action_id="action-1")

    assert result.status == SessionEvidenceLookupStatus.LEGACY_INSUFFICIENT


def _validation_evidence(
    session_id: str,
    *,
    action_id: str = "action-1",
    command_digest: str = "a" * 64,
    validation_status: str = "failed",
    provenance_status: str = "valid",
    category: Optional[str] = "tests_failed",
    exit_status: Optional[int] = 1,
    failure_reason: Optional[str] = "pytest_tests_failed",
) -> SessionValidationEvidence:
    return SessionValidationEvidence(
        session_id=session_id,
        action_id=action_id,
        external_result_digest=build_session_result_digest({"result": "ok", "action_id": action_id}),
        logical_command_digest=command_digest,
        execution_status="executed",
        validation_status=validation_status,
        pytest_provenance_status=provenance_status,
        pytest_completion_category=category,
        pytest_exit_status=exit_status,
        failure_reason_code=failure_reason,
        completed_at=2.0,
        evidence_message_id=f"validation-evidence-{action_id}",
    )


def _record_external_result(store: SessionStore, session_id: str, evidence: SessionValidationEvidence, *, message_id: str = "msg-result") -> None:
    record = store.load(session_id)
    message = ChatMessage(
        role="tool",
        tool_call_id="call-result",
        tool_name="approve_pending_action",
        content=[TextPart(text="ok")],
        metadata={SESSION_MESSAGE_ID_KEY: message_id},
        timestamp=1.0,
    )
    message.metadata[SESSION_CORRELATION_KEY] = build_external_tool_result_correlation(
        action_id=evidence.action_id,
        result_digest=evidence.external_result_digest,
        tool_name="approve_pending_action",
        completed_at=1.0,
    )
    record.messages.append(message)
    store.save(record)


def test_validation_evidence_persists_reload_and_hides_sensitive_fields(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    store.save(record)
    evidence = _validation_evidence(record.id)
    _record_external_result(store, record.id, evidence)

    stored = store.append_validation_evidence(evidence)
    reloaded = SessionStore(tmp_path)
    result = reloaded.lookup_validation_evidence(
        record.id,
        action_id=evidence.action_id,
        external_result_digest=evidence.external_result_digest,
        logical_command_digest=evidence.logical_command_digest,
    )

    assert stored == evidence
    assert result.status == SessionEvidenceLookupStatus.FOUND
    assert result.evidence == evidence
    raw = (tmp_path / f"{record.id}.jsonl").read_text(encoding="utf-8")
    assert "provenance_nonce" not in raw
    assert "approval_token" not in raw
    assert "stdout" not in raw


@pytest.mark.parametrize(
    ("validation_status", "provenance_status", "category", "exit_status", "failure_reason"),
    [
        ("passed", "valid", "passed", 0, None),
        ("blocked", "missing", None, None, "artifact_missing"),
        ("validation_nonzero", "invalid", None, None, "logical_command_digest_mismatch"),
    ],
)
def test_validation_evidence_reload_preserves_bounded_status_variants(
    tmp_path: Path,
    validation_status: str,
    provenance_status: str,
    category: Optional[str],
    exit_status: Optional[int],
    failure_reason: Optional[str],
) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    store.save(record)
    evidence = _validation_evidence(
        record.id,
        validation_status=validation_status,
        provenance_status=provenance_status,
        category=category,
        exit_status=exit_status,
        failure_reason=failure_reason,
    )
    _record_external_result(store, record.id, evidence)

    store.append_validation_evidence(evidence)
    result = SessionStore(tmp_path).lookup_validation_evidence(
        record.id,
        action_id=evidence.action_id,
        external_result_digest=evidence.external_result_digest,
        logical_command_digest=evidence.logical_command_digest,
    )

    assert result.status == SessionEvidenceLookupStatus.FOUND
    assert result.evidence is not None
    assert result.evidence.validation_status == validation_status
    assert result.evidence.pytest_provenance_status == provenance_status
    assert result.evidence.pytest_completion_category == category


def test_validation_evidence_exact_duplicate_is_idempotent_and_conflicts_fail_closed(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    store.save(record)
    evidence = _validation_evidence(record.id)
    _record_external_result(store, record.id, evidence)

    first = store.append_validation_evidence(evidence)
    duplicate = store.append_validation_evidence(evidence.model_copy(update={"evidence_message_id": "validation-evidence-duplicate", "completed_at": 3.0}))

    assert duplicate == first
    assert len(store.load(record.id).messages) == 2
    with pytest.raises(SessionValidationEvidenceConflict):
        store.append_validation_evidence(evidence.model_copy(update={"validation_status": "passed"}))
    with pytest.raises(SessionValidationEvidenceConflict):
        store.append_validation_evidence(
            evidence.model_copy(
                update={
                    "external_result_digest": build_session_result_digest({"result": "different", "action_id": evidence.action_id}),
                }
            )
        )


def test_validation_evidence_requires_existing_external_result_identity(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    store.save(record)
    evidence = _validation_evidence(record.id)

    with pytest.raises(SessionValidationEvidenceConflict):
        store.append_validation_evidence(evidence)


def test_validation_evidence_lookup_distinguishes_identity_and_corruption(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    store.save(record)
    evidence = _validation_evidence(record.id)
    _record_external_result(store, record.id, evidence)
    store.append_validation_evidence(evidence)

    command_mismatch = store.lookup_validation_evidence(
        record.id,
        action_id=evidence.action_id,
        external_result_digest=evidence.external_result_digest,
        logical_command_digest="b" * 64,
    )
    action_mismatch = store.lookup_validation_evidence(
        record.id,
        action_id="action-2",
        external_result_digest=evidence.external_result_digest,
        logical_command_digest=evidence.logical_command_digest,
    )

    assert command_mismatch.status == SessionEvidenceLookupStatus.IDENTITY_MISMATCH
    assert action_mismatch.status == SessionEvidenceLookupStatus.IDENTITY_MISMATCH

    corrupt_record = store.load(record.id)
    corrupt_record.messages.append(
        ChatMessage(
            role="tool",
            content=[TextPart(text="bad")],
            metadata={SESSION_VALIDATION_EVIDENCE_KEY: {"schema_version": "bad"}},
            timestamp=4.0,
        )
    )
    store.save(corrupt_record)
    corrupt = store.lookup_validation_evidence(
        record.id,
        action_id="missing-action",
        external_result_digest=build_session_result_digest({"result": "missing"}),
        logical_command_digest=evidence.logical_command_digest,
    )
    assert corrupt.status == SessionEvidenceLookupStatus.SESSION_CORRUPT


def test_validation_evidence_lookup_fails_closed_for_ambiguous_records(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    store.save(record)
    evidence = _validation_evidence(record.id)
    _record_external_result(store, record.id, evidence)
    store.append_validation_evidence(evidence)
    loaded = store.load(record.id)
    duplicate = loaded.messages[-1].model_copy(deep=True)
    loaded = store.sync_branch_state(
        loaded,
        base_head_id=loaded.active_head_id,
        branch_messages=[*store.branch_messages(loaded, loaded.active_head_id), duplicate],
        pending_plan_token=loaded.pending_plan_token,
        pending_tool_calls=loaded.pending_tool_calls,
    )
    store.save(loaded)

    result = store.lookup_validation_evidence(
        record.id,
        action_id=evidence.action_id,
        external_result_digest=evidence.external_result_digest,
        logical_command_digest=evidence.logical_command_digest,
    )

    assert result.status == SessionEvidenceLookupStatus.AMBIGUOUS


def test_model_continuation_completion_lookup_requires_matching_metadata(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    legacy = ChatMessage(role="assistant", content=[TextPart(text="done")], timestamp=1.0)
    correlated = ChatMessage(role="assistant", content=[TextPart(text="done")], timestamp=2.0)
    ensure_session_message_id(correlated)
    correlated.metadata[SESSION_CORRELATION_KEY] = build_model_continuation_completion_correlation(
        continuation_id="cont-1",
        completed_at=2.0,
        turn_id="turn-2",
    )
    record.messages = [legacy, correlated]
    store.save(record)

    found = store.lookup_model_continuation_completion_evidence(record.id, continuation_id="cont-1")
    missing = store.lookup_model_continuation_completion_evidence(record.id, continuation_id="cont-missing")

    assert found.status == SessionEvidenceLookupStatus.FOUND
    assert found.evidence is not None
    assert found.evidence.correlation_id == "cont-1"
    assert missing.status == SessionEvidenceLookupStatus.NOT_FOUND


def test_session_store_save_is_append_only_for_existing_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    store.save(record)
    path = tmp_path / f"{record.id}.jsonl"
    original_lines = path.read_text(encoding="utf-8").splitlines()

    record.messages = [ChatMessage(role="user", content=[TextPart(text="hello")], timestamp=1.0)]
    store.save(record)
    updated_lines = path.read_text(encoding="utf-8").splitlines()

    assert len(updated_lines) > len(original_lines)
    assert updated_lines[: len(original_lines)] == original_lines


def test_session_store_fork_creates_parent_child_link(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    source = store.create("hello", ModelConfig())
    source.metadata.compaction.summary = "summary"
    source.messages = [ChatMessage(role="user", content=[TextPart(text="root question")], timestamp=1.0)]
    store.save(source)

    forked = store.fork(source.id)
    store.save(forked)

    assert forked.parent_id == source.id
    assert forked.id != source.id
    assert forked.compaction.summary == "summary"
    assert len(forked.messages) == 1


def test_session_store_tree_returns_branch_structure_and_previews(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    root = store.create("hello", ModelConfig())
    root.metadata.compaction.summary = "root summary preview"
    root.messages = [
        ChatMessage(role="user", content=[TextPart(text="user asks about planner")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="assistant answers briefly")], timestamp=2.0),
    ]
    store.save(root)
    branch = store.fork(root.id)
    branch.messages.append(ChatMessage(role="user", content=[TextPart(text="branch follow-up")], timestamp=3.0))
    store.save(branch)

    tree = store.tree()
    description = store.describe(root.id)

    assert len(tree) == 2
    assert any(node.id == root.id and node.parent_id is None and node.summary_preview and node.turn_count == 1 for node in tree)
    assert any(node.id == branch.id and node.parent_id == root.id and node.last_user_preview == "branch follow-up" and node.turn_count == 2 for node in tree)
    assert description["current"]["id"] == root.id
    assert description["children"][0]["id"] == branch.id


def test_session_store_rewind_creates_truncated_branch(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    source = store.create("hello", ModelConfig())
    source.metadata.compaction.summary = "summary"
    source.metadata.pending_plan_token = "token-1"
    source.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
        ChatMessage(role="user", content=[TextPart(text="u2")], timestamp=3.0),
    ]
    store.save(source)

    rewound = store.rewind(source.id, 2)
    store.save(rewound)

    assert rewound.parent_id == source.id
    assert len(rewound.messages) == 2
    assert rewound.messages[-1].role == "assistant"
    assert rewound.compaction.summary == ""
    assert rewound.pending_plan_token is None


def test_session_store_rewind_turns_uses_complete_turns(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    source = store.create("hello", ModelConfig())
    source.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
        ChatMessage(role="tool", content=[TextPart(text="t1")], timestamp=3.0),
        ChatMessage(role="user", content=[TextPart(text="u2")], timestamp=4.0),
        ChatMessage(role="assistant", content=[TextPart(text="a2")], timestamp=5.0),
    ]
    store.save(source)

    rewound = store.rewind_turns(source.id, 1)

    assert [message.role for message in rewound.messages] == ["user", "assistant", "tool"]


def test_session_store_list_returns_metadata(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    store.save(record)

    sessions = store.list()

    assert len(sessions) == 1
    assert sessions[0].id == record.id


def test_session_store_children_of_returns_direct_children(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    root = store.create("hello", ModelConfig())
    store.save(root)
    child = store.fork(root.id)
    store.save(child)

    children = store.children_of(root.id)

    assert len(children) == 1
    assert children[0].id == child.id


def test_session_store_load_builds_turn_index_and_active_head(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
        ChatMessage(role="user", content=[TextPart(text="u2")], timestamp=3.0),
        ChatMessage(role="assistant", content=[TextPart(text="a2")], timestamp=4.0),
    ]
    store.save(record)

    loaded = store.load(record.id)

    assert len(loaded.turn_nodes) == 2
    assert loaded.active_head_id == loaded.turn_nodes[-1].id
    assert [message.role for message in store.branch_messages(loaded, loaded.active_head_id)] == ["user", "assistant", "user", "assistant"]


def test_session_store_can_switch_active_head_to_historical_turn(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
        ChatMessage(role="user", content=[TextPart(text="u2")], timestamp=3.0),
        ChatMessage(role="assistant", content=[TextPart(text="a2")], timestamp=4.0),
    ]
    store.save(record)
    loaded = store.load(record.id)

    historical_head = loaded.turn_nodes[0].id
    store.set_active_head(loaded.id, historical_head)
    switched = store.load(loaded.id)

    assert switched.active_head_id == historical_head
    assert [message.role for message in store.branch_messages(switched, switched.active_head_id)] == ["user", "assistant"]


def test_session_store_sync_branch_state_appends_turn_branch_from_historical_head(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
        ChatMessage(role="user", content=[TextPart(text="u2")], timestamp=3.0),
        ChatMessage(role="assistant", content=[TextPart(text="a2")], timestamp=4.0),
    ]
    store.save(record)
    loaded = store.load(record.id)
    historical_head = loaded.turn_nodes[0].id

    new_branch_messages = store.branch_messages(loaded, historical_head) + [
        ChatMessage(role="user", content=[TextPart(text="branch user")], timestamp=5.0),
        ChatMessage(role="assistant", content=[TextPart(text="branch answer")], timestamp=6.0),
    ]
    updated = store.sync_branch_state(
        loaded,
        base_head_id=historical_head,
        branch_messages=new_branch_messages,
        pending_plan_token=None,
        pending_tool_calls=[],
    )
    store.save(updated)
    saved = store.load(record.id)

    assert len(saved.turn_nodes) == 3
    assert saved.active_head_id == saved.turn_nodes[-1].id
    assert saved.turn_nodes[-1].parent_id == historical_head
    assert [message.role for message in store.branch_messages(saved, saved.active_head_id)] == ["user", "assistant", "user", "assistant"]
    assert any(node.parent_id == historical_head and node.id != loaded.turn_nodes[1].id for node in saved.turn_nodes)


def test_session_store_migrates_compaction_metadata_into_turn_tree_entry(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
    ]
    record.metadata.compaction.summary = "old summary"
    record.metadata.compaction.summarized_message_count = 2
    store.save(record)

    loaded = store.load(record.id)
    compaction_nodes = [node for node in loaded.turn_nodes if node.entry_type == "compaction"]

    assert loaded.compaction.summary == "old summary"
    assert loaded.active_head_id == compaction_nodes[-1].id
    assert compaction_nodes[-1].summary == "old summary"
    assert compaction_nodes[-1].summarized_message_count == 2


def test_session_store_turn_entries_include_compaction_entries(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
    ]
    record.metadata.compaction.summary = "summary line"
    record.metadata.compaction.summarized_message_count = 2
    store.save(record)

    entries = store.turn_entries(record.id)

    assert [entry.entry_type for entry in entries] == ["turn", "compaction"]
    assert entries[-1].summary_preview == "summary line"
    assert entries[-1].summarized_message_count == 2


def test_session_store_fork_from_compaction_head_uses_head_branch(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
    ]
    record.metadata.compaction.summary = "summary line"
    record.metadata.compaction.summarized_message_count = 2
    store.save(record)
    saved = store.load(record.id)
    compaction_head = next(node.id for node in saved.turn_nodes if node.entry_type == "compaction")

    forked = store.fork_from_head(saved.id, compaction_head)

    assert forked.compaction.summary == "summary line"
    assert forked.messages == saved.messages
    assert forked.active_head_id is not None


def test_session_store_turn_node_uses_indexed_lookup(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create("hello", ModelConfig())
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
    ]
    store.save(record)
    loaded = store.load(record.id)

    node = store.turn_node(loaded, loaded.active_head_id)

    assert node is not None
    assert loaded._turn_index[loaded.active_head_id].id == node.id


def test_session_store_tree_skips_partial_session_files_without_snapshot(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    good = store.create("hello", ModelConfig())
    store.save(good)
    (tmp_path / "broken-session.jsonl").write_text('{"type":"metadata_created","session_id":"broken"}\n', encoding="utf-8")

    tree = store.tree()

    assert len(tree) == 1
    assert tree[0].id == good.id
