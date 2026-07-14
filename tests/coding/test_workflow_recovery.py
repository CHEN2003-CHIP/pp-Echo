from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from pp_agent.coding.workflow_checkpoint import (
    CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V2,
    CodingWorkflowCheckpoint,
    CodingWorkflowKind,
    CodingWorkflowPhase,
    PendingActionReference,
    PendingActionRole,
)
from pp_agent.coding.workflow_checkpoint_store import CodingWorkflowCheckpointStore, CheckpointStaleRevision
from pp_agent.coding.workflow_recovery import (
    CodingWorkflowDecision,
    inspect_coding_workflow,
    resume_coding_workflow,
)
from pp_agent.domain import ChatMessage
from pp_agent.llm import ModelConfig
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.storage.sessions import SessionStore, build_session_result_digest
from pp_agent.tools.registry import ToolRegistry


class ScriptedLLMClient:
    def __init__(self, calls: list[dict[str, object]]) -> None:
        self.model = ModelConfig()
        self.calls = list(calls)
        self.call_count = 0
        self.seen_messages: list[list[ChatMessage]] = []

    def stream_chat(self, messages, tools=None) -> Iterator[dict[str, object]]:
        self.call_count += 1
        self.seen_messages.append(list(messages))
        if self.calls:
            yield self.calls.pop(0)
            return
        yield {"text": "done", "tool_calls": [], "finish_reason": "stop", "raw": {}}


def _runtime(tmp_path: Path, llm: ScriptedLLMClient) -> AgentRuntime:
    session_store = SessionStore(tmp_path / "sessions")
    record = session_store.create("system", ModelConfig())
    runtime = AgentRuntime(
        llm_client=llm,
        tool_registry=ToolRegistry(tmp_path),
        session_store=session_store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        require_plan_approval=False,
    )
    runtime.restore_session_record(record)
    return runtime


def _checkpoint(
    *,
    workflow_id: str,
    session_id: str,
    ref: PendingActionReference | None = None,
    phase: CodingWorkflowPhase = CodingWorkflowPhase.TOOL_COMPLETED,
) -> CodingWorkflowCheckpoint:
    now = datetime.now(timezone.utc)
    return CodingWorkflowCheckpoint(
        schema_version=CODING_WORKFLOW_CHECKPOINT_SCHEMA_VERSION_V2,
        workflow_id=workflow_id,
        session_id=session_id,
        workflow_kind=CodingWorkflowKind.CONTROLLED_CODING,
        revision=0,
        phase=phase,
        validation_execution_count=0,
        repair_attempted=False,
        revalidation_attempted=False,
        pending_action_ref=ref if phase == CodingWorkflowPhase.AWAITING_TOOL_APPROVAL else None,
        last_completed_action_ref=ref if phase == CodingWorkflowPhase.TOOL_COMPLETED else None,
        created_at=now,
        updated_at=now,
    )


def _consumed_action_with_evidence(tmp_path: Path, runtime: AgentRuntime) -> PendingActionReference:
    digest = build_session_result_digest(
        {
            "result": "ok",
            "details": {"safe": True},
            "success": True,
            "approval_action": "approve",
            "action_type": "write_file",
            "source_tool_name": "approve_pending_action",
        }
    )
    checkpoint_digest = digest.removeprefix("sha256:")
    pending_store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    staged = pending_store.stage(
        action_type="write_file",
        details={"session_id": runtime.session_id},
        effect={"effect_id": "effect-1", "payload_digest": checkpoint_digest, "tool_name": "write_file", "analysis": {}},
        session_id=runtime.session_id,
    )
    pending_store.set_lifecycle(staged["token"], "grant_consumed")
    runtime.record_external_approval_result(
        {
            "session_id": runtime.session_id,
            "token": staged["token"],
            "action_type": "write_file",
            "source_tool_name": "approve_pending_action",
            "tool_call_id": "call-write",
            "success": True,
            "approval_action": "approve",
            "approved": True,
            "result": "ok",
            "details": {"safe": True},
        }
    )
    return PendingActionReference(
        action_id=staged["token"],
        role=PendingActionRole.TOOL,
        action_digest=checkpoint_digest,
        action_type="write_file",
    )


def test_inspect_exact_consumed_result_is_read_only_and_ready(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, ScriptedLLMClient([]))
    ref = _consumed_action_with_evidence(tmp_path, runtime)
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(_checkpoint(workflow_id="workflow-1", session_id=runtime.session_id, ref=ref))

    before = store.load_checkpoint("workflow-1")
    inspection = inspect_coding_workflow(workspace=tmp_path, workflow_id="workflow-1", session_store=runtime.session_store)
    after = store.load_checkpoint("workflow-1")

    assert inspection.decision == CodingWorkflowDecision.READY_FOR_CONTINUATION_INTENT
    assert before == after
    assert runtime.llm_client.call_count == 0


def test_resume_commits_intent_before_single_model_continuation(tmp_path: Path) -> None:
    llm = ScriptedLLMClient([{"text": "ordinary completion", "tool_calls": [], "finish_reason": "stop", "raw": {}}])
    runtime = _runtime(tmp_path, llm)
    ref = _consumed_action_with_evidence(tmp_path, runtime)
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(_checkpoint(workflow_id="workflow-1", session_id=runtime.session_id, ref=ref))

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-1",
        expected_revision=0,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    checkpoint = store.load_checkpoint("workflow-1")

    assert result.model_continuation_attempted is True
    assert result.external_effect_count == 1
    assert llm.call_count == 1
    assert checkpoint.revision == 2
    assert checkpoint.model_continuation_intent is not None
    assert checkpoint.model_continuation_intent.state == "session_committed"
    assert result.inspection.decision == CodingWorkflowDecision.CONTINUATION_COMPLETED_IN_SESSION

    repeated = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-1",
        expected_revision=2,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    assert repeated.model_continuation_attempted is False
    assert llm.call_count == 1


def test_concurrent_same_revision_only_one_runtime_attempt(tmp_path: Path) -> None:
    llm = ScriptedLLMClient([{"text": "done", "tool_calls": [], "finish_reason": "stop", "raw": {}}])
    runtime = _runtime(tmp_path, llm)
    ref = _consumed_action_with_evidence(tmp_path, runtime)
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(_checkpoint(workflow_id="workflow-1", session_id=runtime.session_id, ref=ref))

    first = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-1",
        expected_revision=0,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )
    second = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-1",
        expected_revision=0,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )

    assert first.model_continuation_attempted is True
    assert second.inspection.decision == CodingWorkflowDecision.STALE_REVISION
    assert llm.call_count == 1


def test_boundary_continuation_stages_tool_without_execution(tmp_path: Path) -> None:
    llm = ScriptedLLMClient(
        [
            {
                "text": "",
                "tool_calls": [{"id": "call-write", "name": "write_file", "arguments_chunk": '{"path":"notes.txt","content":"alpha"}'}],
                "finish_reason": "tool_calls",
                "raw": {},
            }
        ]
    )
    runtime = _runtime(tmp_path, llm)

    runtime.continue_(continuation_id="cont-1", stop_after_model_boundary=True)
    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list()

    assert llm.call_count == 1
    assert pending and pending[0]["action_type"] == "planner_approval"
    assert runtime.state.pending_tool_calls[0].id == "call-write"
    assert not (tmp_path / "notes.txt").exists()
    assert runtime.session_store.lookup_model_continuation_completion_evidence(runtime.session_id, continuation_id="cont-1").status == "found"


def test_post_call_cas_failure_does_not_retry_model(tmp_path: Path) -> None:
    llm = ScriptedLLMClient([{"text": "done", "tool_calls": [], "finish_reason": "stop", "raw": {}}])
    runtime = _runtime(tmp_path, llm)
    ref = _consumed_action_with_evidence(tmp_path, runtime)
    store = CodingWorkflowCheckpointStore(tmp_path)
    store.create_checkpoint(_checkpoint(workflow_id="workflow-1", session_id=runtime.session_id, ref=ref))
    original_replace = store.replace_checkpoint
    calls = {"count": 0}

    def flaky_replace(checkpoint: CodingWorkflowCheckpoint, *, expected_revision: int) -> CodingWorkflowCheckpoint:
        calls["count"] += 1
        if calls["count"] == 2:
            raise CheckpointStaleRevision("forced stale")
        return original_replace(checkpoint, expected_revision=expected_revision)

    store.replace_checkpoint = flaky_replace  # type: ignore[method-assign]

    result = resume_coding_workflow(
        workspace=tmp_path,
        workflow_id="workflow-1",
        expected_revision=0,
        runtime=runtime,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )

    assert result.model_continuation_attempted is True
    assert result.inspection.decision == CodingWorkflowDecision.BLOCKED_UNCERTAIN
    assert llm.call_count == 1
