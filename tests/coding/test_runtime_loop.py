from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pp_agent.coding import (
    ControlledLoopOptions,
    ControlledToolLoopResult,
    ValidationCommand,
    ValidationPlan,
    collect_pending_approvals,
    controlled_loop_result_to_block,
    controlled_loop_result_to_context_item,
    controlled_loop_result_to_summary,
    default_controlled_loop_options,
    prepare_coding_workflow,
    run_controlled_coding_loop,
    start_coding_execution_session,
)
from pp_agent.coding.scope import TaskScope
from pp_agent.coding.orchestrator import CodingWorkflow, prepare_coding_workflow
from pp_agent.coding.workflow_checkpoint import CodingWorkflowPhase, PendingActionRole
from pp_agent.coding.workflow_checkpoint_store import CodingWorkflowCheckpointStore
from pp_agent.coding.workflow_recovery import CodingWorkflowDecision, inspect_coding_workflow
from pp_agent.domain import ChatMessage, TextPart, ToolCall
from pp_agent.llm import ModelConfig
from pp_agent.runtime.runtime import AgentRuntime, ExecutePersistedActionStatus
from pp_agent.runtime.execution_context import RuntimeExecutionContext
from pp_agent.runtime.hooks import RuntimeHooks
from pp_agent.sandbox.base import SandboxRunRequest, SandboxRunResult
from pp_agent.storage.sessions import SessionStore
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.tools.effects import build_shell_effect
from pp_agent.tools.policy import PermissionDomain
from pp_agent.tools.registry import ToolRegistry
from pp_agent.tools.base import ToolExecutionResult


class FakeRuntime:
    def __init__(self, workspace: Path, events: list | None = None, *, raise_error: bool = False) -> None:
        self.tool_registry = ToolRegistry(workspace)
        self.events = events or []
        self.raise_error = raise_error
        self.prompts: list[str] = []
        self.continues = 0
        self.runtime_execution_context = None

    def prompt(self, text: str):
        self.prompts.append(text)
        if self.raise_error:
            raise RuntimeError("boom")
        return list(self.events)

    def continue_(self):
        self.continues += 1
        return list(self.events)


class ReadObservingRuntime(FakeRuntime):
    def __init__(self, workspace: Path, read_path: Path) -> None:
        super().__init__(workspace)
        self.runtime_hooks = RuntimeHooks()
        self.read_path = read_path

    def prompt(self, text: str):
        self.prompts.append(text)
        call = ToolCall(id="call-read", name="read_file", arguments={"path": str(self.read_path)})
        result = ToolExecutionResult(
            tool_call_id="call-read",
            tool_name="read_file",
            content="ok",
            details={"path": str(self.read_path)},
        )
        self.runtime_hooks.after_tool_call(None, call, result)
        return []


class NoStoreRuntime:
    pass


class ScopedContextRecordingLLMClient:
    def __init__(self, *, read_path: str | None = None) -> None:
        self.model = ModelConfig()
        self.read_path = read_path
        self.calls = 0
        self.seen_messages: list[list[ChatMessage]] = []

    def stream_chat(self, messages, tools=None):
        self.calls += 1
        self.seen_messages.append(list(messages))
        if self.read_path is not None and self.calls == 1:
            yield {
                "text": "",
                "tool_calls": [{"id": "call-read", "name": "read_file", "arguments_chunk": f'{{"path":"{self.read_path}"}}'}],
                "finish_reason": "tool_calls",
                "raw": {},
            }
            return
        yield {"text": "done", "tool_calls": [], "finish_reason": "stop", "raw": {}}


class ProvenanceWritingSandboxExecutor:
    def __init__(self, workspace: Path, *, returncode: int = 0) -> None:
        self.workspace = workspace
        self.returncode = returncode
        self.requests: list[SandboxRunRequest] = []

    def run(self, request: SandboxRunRequest) -> SandboxRunResult:
        from pp_agent.coding.pytest_provenance import write_pytest_provenance_attestation

        self.requests.append(request)
        parts = request.command.split()
        artifact = parts[parts.index("--pp-echo-pytest-provenance-file") + 1]
        nonce = parts[parts.index("--pp-echo-pytest-provenance-nonce") + 1]
        digest = parts[parts.index("--pp-echo-pytest-logical-command-digest") + 1]
        write_pytest_provenance_attestation(
            artifact_path=self.workspace / artifact,
            nonce=nonce,
            logical_command_digest=digest,
            pytest_exit_status=self.returncode,
        )
        return SandboxRunResult(
            stdout="ok\n" if self.returncode == 0 else "FAILED\n",
            stderr="",
            returncode=self.returncode,
            timed_out=False,
            backend="fake",
            sandbox_mode="test",
            network_access=False,
            writable_roots=[str(self.workspace)],
        )


def _workspace(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "src" / "pp_agent" / "coding").mkdir(parents=True)
    (tmp_path / "tests" / "coding").mkdir(parents=True)
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")
    return tmp_path


def _real_runtime(workspace: Path, llm_client: ScopedContextRecordingLLMClient, *, sandbox_executor=None) -> AgentRuntime:
    store = SessionStore(workspace / "sessions")
    record = store.create("system", ModelConfig())
    runtime = AgentRuntime(
        llm_client=llm_client,
        tool_registry=ToolRegistry(workspace, sandbox_executor=sandbox_executor),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        require_plan_approval=False,
    )
    runtime.restore_session_record(record)
    runtime.config_snapshot.settings.context_pipeline.context_pipeline_mode = "on"
    runtime.context_pipeline_mode = "on"
    return runtime


def _provider_text(messages: list[ChatMessage]) -> str:
    return "\n".join(part.text for message in messages for part in message.content if isinstance(part, TextPart))


def _event(**details):
    return SimpleNamespace(details=details)


def _stage_shell_pending(runtime: FakeRuntime) -> str:
    store = PendingActionStore(runtime.tool_registry.workspace / ".pp-agent" / "pending-edits")
    effect = build_shell_effect(
        tool_name="run_shell",
        permission_domain=PermissionDomain.BASH,
        command="Write-Output ok",
        timeout_seconds=5,
        workspace=runtime.tool_registry.workspace,
    )
    return store.stage(
        action_type="run_shell",
        command="Write-Output ok",
        details={"timeout_seconds": 5},
        effect=effect,
    )["token"]


def test_default_controlled_loop_options() -> None:
    options = default_controlled_loop_options()

    assert options.max_model_turns == 3
    assert options.stop_on_approval is True
    assert options.stop_on_guardrail_block is True
    assert options.stop_on_scope_block is True
    assert options.dry_run is False


def test_controlled_tool_loop_result_summary_is_stable(tmp_path: Path) -> None:
    result = run_controlled_coding_loop("update coding docs", FakeRuntime(_workspace(tmp_path)), options=ControlledLoopOptions(0, True, True, True, True))

    summary = controlled_loop_result_to_summary(result)

    assert summary.startswith("Controlled Tool Loop:")
    assert "- Stop reason: completed" in summary


def test_controlled_loop_result_to_context_item(tmp_path: Path) -> None:
    result = run_controlled_coding_loop("update coding docs", FakeRuntime(_workspace(tmp_path)), options=ControlledLoopOptions(0, True, True, True, True))

    item = controlled_loop_result_to_context_item(result)

    assert item["title"] == "Controlled tool loop"
    assert item["metadata"]["controlled_tool_loop"]["status"] == "prepared"


def test_controlled_loop_public_models_have_docstrings() -> None:
    assert ControlledLoopOptions.__doc__
    assert ControlledToolLoopResult.__doc__


def test_controlled_loop_public_helpers_have_docstrings() -> None:
    assert default_controlled_loop_options.__doc__
    assert run_controlled_coding_loop.__doc__
    assert collect_pending_approvals.__doc__
    assert controlled_loop_result_to_context_item.__doc__
    assert controlled_loop_result_to_summary.__doc__
    assert controlled_loop_result_to_block.__doc__


def test_run_controlled_coding_loop_builds_workflow_when_missing(tmp_path: Path) -> None:
    result = run_controlled_coding_loop("extend runtime loop", FakeRuntime(_workspace(tmp_path)), options=ControlledLoopOptions(0, True, True, True, True))

    assert result.session.workflow.task == "extend runtime loop"
    assert result.validation_plan is not None


def test_run_controlled_coding_loop_uses_passed_workflow(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    workflow = prepare_coding_workflow("passed workflow", workspace=workspace)

    result = run_controlled_coding_loop("ignored task", FakeRuntime(workspace), workflow=workflow, options=ControlledLoopOptions(0, True, True, True, True))

    assert result.session.workflow is workflow
    assert result.task == "ignored task"


def test_run_controlled_coding_loop_uses_passed_session(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    workflow = prepare_coding_workflow("passed session", workspace=workspace)
    session = start_coding_execution_session(workflow, session_id="exec-fixed")

    result = run_controlled_coding_loop("passed session", FakeRuntime(workspace), workflow=workflow, session=session, options=ControlledLoopOptions(0, True, True, True, True))

    assert result.session is session
    assert result.runtime_execution_context.session_id == "exec-fixed"


def test_run_controlled_coding_loop_creates_runtime_execution_context(tmp_path: Path) -> None:
    result = run_controlled_coding_loop("make context", FakeRuntime(_workspace(tmp_path)), options=ControlledLoopOptions(0, True, True, True, True))

    assert isinstance(result.runtime_execution_context, RuntimeExecutionContext)


def test_run_controlled_coding_loop_passes_runtime_execution_context_to_runtime(tmp_path: Path) -> None:
    runtime = FakeRuntime(_workspace(tmp_path))

    result = run_controlled_coding_loop("attach context", runtime, options=ControlledLoopOptions(0, True, True, True, True))

    assert runtime.runtime_execution_context == result.runtime_execution_context
    assert runtime.tool_registry.runtime_execution_context() == result.runtime_execution_context


def test_controlled_loop_seeds_scoped_instructions_from_task_scope(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "src" / "pp_agent" / "coding" / "AGENTS.md").write_text("coding scoped rules", encoding="utf-8")
    workflow = prepare_coding_workflow("seed scoped", workspace=workspace)
    workflow.task_scope = TaskScope(task="seed scoped", allowed_paths=["src/pp_agent/coding/runtime_loop.py"])

    result = run_controlled_coding_loop("seed scoped", FakeRuntime(workspace), workflow=workflow, options=ControlledLoopOptions(0, True, True, True, True))

    state = result.scoped_instruction_activation_state
    assert state is not None
    assert [item.source_path for item in state.active_instructions()] == ["src/pp_agent/coding/AGENTS.md"]


def test_controlled_loop_observes_successful_read_file_without_context_injection(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "src" / "pp_agent" / "coding" / "AGENTS.md").write_text("lazy scoped rules", encoding="utf-8")
    target = workspace / "src" / "pp_agent" / "coding" / "runtime_loop.py"
    target.write_text("code", encoding="utf-8")
    workflow = prepare_coding_workflow("lazy read", workspace=workspace)
    workflow.task_scope = TaskScope(task="lazy read", allowed_paths=[])

    result = run_controlled_coding_loop("lazy read", ReadObservingRuntime(workspace, target), workflow=workflow, options=ControlledLoopOptions(1, False, False, False, False))

    state = result.scoped_instruction_activation_state
    assert state is not None
    assert [item.source_path for item in state.active_instructions()] == ["src/pp_agent/coding/AGENTS.md"]
    assert result.timeline_blocks


def test_controlled_loop_task_scope_seed_reaches_first_provider_context(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    sentinel = "TASK_SCOPE_SEEDED_SCOPED_RULE"
    (workspace / "src" / "pp_agent" / "coding" / "AGENTS.md").write_text(sentinel, encoding="utf-8")
    workflow = prepare_coding_workflow("seed scoped", workspace=workspace)
    workflow.task_scope = TaskScope(task="seed scoped", allowed_paths=["src/pp_agent/coding/runtime_loop.py"])
    llm = ScopedContextRecordingLLMClient()
    runtime = _real_runtime(workspace, llm)

    result = run_controlled_coding_loop("seed scoped", runtime, workflow=workflow, options=ControlledLoopOptions(1, False, False, False, False))

    assert result.scoped_instruction_activation_state is not None
    assert sentinel in _provider_text(llm.seen_messages[0])
    assert "scoped-instruction:src/pp_agent/coding/AGENTS.md" in [
        str(message.metadata.get("context_item_id")) for message in llm.seen_messages[0]
    ]
    assert runtime.scoped_instruction_context_provider is None


def test_controlled_loop_read_trigger_reaches_next_provider_context(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    sentinel = "READ_TRIGGERED_SCOPED_RULE"
    (workspace / "src" / "pp_agent" / "coding" / "AGENTS.md").write_text(sentinel, encoding="utf-8")
    target = workspace / "src" / "pp_agent" / "coding" / "runtime_loop.py"
    target.write_text("code", encoding="utf-8")
    workflow = prepare_coding_workflow("lazy read", workspace=workspace)
    workflow.task_scope = TaskScope(task="lazy read", allowed_paths=[])
    llm = ScopedContextRecordingLLMClient(read_path="src/pp_agent/coding/runtime_loop.py")
    runtime = _real_runtime(workspace, llm)

    result = run_controlled_coding_loop("lazy read", runtime, workflow=workflow, options=ControlledLoopOptions(1, False, False, False, False))

    assert result.scoped_instruction_activation_state is not None
    assert len(llm.seen_messages) >= 2
    assert sentinel not in _provider_text(llm.seen_messages[0])
    assert sentinel in _provider_text(llm.seen_messages[1])
    assert _provider_text(llm.seen_messages[1]).count(sentinel) == 1


def test_controlled_loop_failed_read_does_not_activate_scoped_context(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    sentinel = "FAILED_READ_SCOPED_RULE"
    (workspace / "src" / "pp_agent" / "coding" / "AGENTS.md").write_text(sentinel, encoding="utf-8")
    workflow = prepare_coding_workflow("failed read", workspace=workspace)
    workflow.task_scope = TaskScope(task="failed read", allowed_paths=[])
    llm = ScopedContextRecordingLLMClient(read_path="src/pp_agent/coding/missing.py")
    runtime = _real_runtime(workspace, llm)

    result = run_controlled_coding_loop("failed read", runtime, workflow=workflow, options=ControlledLoopOptions(1, False, False, False, False))

    assert result.scoped_instruction_activation_state is not None
    assert not result.scoped_instruction_activation_state.active_instructions()
    assert all(sentinel not in _provider_text(messages) for messages in llm.seen_messages)


def test_run_controlled_coding_loop_stops_on_approval(tmp_path: Path) -> None:
    runtime = FakeRuntime(_workspace(tmp_path))
    _stage_shell_pending(runtime)

    result = run_controlled_coding_loop("needs approval", runtime, options=ControlledLoopOptions(1, True, True, True, False))

    assert result.status == "awaiting_approval"
    assert result.stop_reason == "approval_required"
    assert len(result.pending_approvals) == 1


def test_run_controlled_coding_loop_stops_on_guardrail_block(tmp_path: Path) -> None:
    runtime = FakeRuntime(_workspace(tmp_path), events=[_event(runtime_guardrail_blocked=True)])

    result = run_controlled_coding_loop("guardrail", runtime, options=ControlledLoopOptions(1, True, True, True, False))

    assert result.status == "guardrail_blocked"
    assert result.stop_reason == "guardrail_limit"


def test_run_controlled_coding_loop_stops_on_scope_block(tmp_path: Path) -> None:
    runtime = FakeRuntime(_workspace(tmp_path), events=[_event(scope_blocked=True)])

    result = run_controlled_coding_loop("scope", runtime, options=ControlledLoopOptions(1, True, True, True, False))

    assert result.status == "scope_blocked"
    assert result.stop_reason == "scope_blocked"


def test_run_controlled_coding_loop_handles_runtime_error(tmp_path: Path) -> None:
    result = run_controlled_coding_loop("explode", FakeRuntime(_workspace(tmp_path), raise_error=True), options=ControlledLoopOptions(1, True, True, True, False))

    assert result.status == "failed"
    assert result.stop_reason == "runtime_error"


def test_run_controlled_coding_loop_respects_max_model_turns_if_supported(tmp_path: Path) -> None:
    runtime = FakeRuntime(_workspace(tmp_path))

    result = run_controlled_coding_loop("turns", runtime, options=ControlledLoopOptions(2, False, False, False, False))

    assert runtime.prompts == ["turns"]
    assert runtime.continues == 1
    assert result.stop_reason == "max_turns"


def test_collect_pending_approvals_returns_json_friendly_summaries(tmp_path: Path) -> None:
    runtime = FakeRuntime(_workspace(tmp_path))
    token = _stage_shell_pending(runtime)

    approvals = collect_pending_approvals(runtime)

    assert approvals == [
        {
            "token": token,
            "action_type": "run_shell",
            "tool_name": "run_shell",
            "title": "Modify workspace with Write-Output ok",
            "summary": "Modify workspace with Write-Output ok",
            "changed_files": [],
            "command": "Write-Output ok",
            "scope_check": None,
        }
    ]


def test_collect_pending_approvals_handles_unavailable_store() -> None:
    assert collect_pending_approvals(NoStoreRuntime()) == []


def test_controlled_loop_patch_candidate_includes_write_scope(tmp_path: Path) -> None:
    result = run_controlled_coding_loop("edit coding runtime", FakeRuntime(_workspace(tmp_path)), options=ControlledLoopOptions(0, True, True, True, True))

    assert result.runtime_execution_context.write_scope is not None
    assert result.runtime_execution_context.write_scope.source == "task_scope"


def test_controlled_loop_scope_block_surfaces_in_result(tmp_path: Path) -> None:
    runtime = FakeRuntime(_workspace(tmp_path), events=[_event(patch_candidate={"scope_blocked": True})])

    result = run_controlled_coding_loop("scope nested", runtime, options=ControlledLoopOptions(1, True, True, True, False))

    assert result.status == "scope_blocked"


def test_controlled_loop_result_to_block(tmp_path: Path) -> None:
    result = run_controlled_coding_loop("block", FakeRuntime(_workspace(tmp_path)), options=ControlledLoopOptions(0, True, True, True, True))

    block = controlled_loop_result_to_block(result)

    assert block.type == "controlled_tool_loop"
    assert block.details["stop_reason"] == "completed"


def test_controlled_loop_completion_stages_initial_validation_checkpoint(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    llm = ScopedContextRecordingLLMClient()
    runtime = _real_runtime(workspace, llm)
    workflow = prepare_coding_workflow("stage initial validation", workspace=workspace)
    workflow.validation_plan = ValidationPlan(commands=[ValidationCommand(command="python -m pytest tests/coding -q")])
    store = CodingWorkflowCheckpointStore(workspace)

    result = run_controlled_coding_loop(
        "stage initial validation",
        runtime,
        workspace=workspace,
        workflow=workflow,
        options=ControlledLoopOptions(1, True, True, True, False),
        checkpoint_store=store,
    )
    checkpoint = store.load_checkpoint(result.session.id)

    assert result.status == "awaiting_approval"
    assert result.stop_reason == "validation_approval_required"
    assert result.validation_staging is not None
    assert result.validation_staging.status == "staged"
    assert result.validation_staging.pending_action_ref is not None
    assert result.validation_staging.pending_action_ref.role == PendingActionRole.VALIDATION
    assert result.validation_staging.pending_action_ref.action_type == "run_shell"
    assert len(result.pending_approvals) == 1
    assert checkpoint.phase == CodingWorkflowPhase.AWAITING_VALIDATION_APPROVAL
    assert checkpoint.validation_execution_count == 0
    assert checkpoint.repair_attempted is False
    assert checkpoint.revalidation_attempted is False
    assert checkpoint.final_outcome_summary is None
    assert checkpoint.terminal_outcome is None
    assert llm.calls == 1


def test_controlled_loop_does_not_stage_validation_when_ordinary_approval_pending(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    runtime = FakeRuntime(workspace)
    _stage_shell_pending(runtime)
    store = CodingWorkflowCheckpointStore(workspace)

    result = run_controlled_coding_loop(
        "needs approval first",
        runtime,
        workspace=workspace,
        options=ControlledLoopOptions(1, True, True, True, False),
        checkpoint_store=store,
    )

    assert result.status == "awaiting_approval"
    assert result.validation_staging is None
    assert store.checkpoint_exists(result.session.id) is False
    assert len(_store := PendingActionStore(workspace / ".pp-agent" / "pending-edits").list()) == 1
    assert _store[0]["action_type"] == "run_shell"


def test_controlled_loop_no_validation_command_blocks_without_pending_action(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    llm = ScopedContextRecordingLLMClient()
    runtime = _real_runtime(workspace, llm)
    workflow = prepare_coding_workflow("no pytest", workspace=workspace)
    workflow.validation_plan = ValidationPlan(commands=[ValidationCommand(command="cd web && npm test")])
    store = CodingWorkflowCheckpointStore(workspace)

    result = run_controlled_coding_loop(
        "no pytest",
        runtime,
        workspace=workspace,
        workflow=workflow,
        options=ControlledLoopOptions(1, True, True, True, False),
        checkpoint_store=store,
    )

    assert result.status == "validation_staging_blocked"
    assert result.stop_reason == "blocked_no_command"
    assert result.validation_staging is not None
    assert result.validation_staging.status == "blocked_no_command"
    assert PendingActionStore(workspace / ".pp-agent" / "pending-edits").list() == []
    assert store.checkpoint_exists(result.session.id) is False


def test_controlled_loop_staged_validation_is_visible_to_batch_3b_inspect(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    runtime = _real_runtime(workspace, ScopedContextRecordingLLMClient())
    workflow = prepare_coding_workflow("inspect staged validation", workspace=workspace)
    workflow.validation_plan = ValidationPlan(commands=[ValidationCommand(command="python -m pytest tests/coding -q")])
    store = CodingWorkflowCheckpointStore(workspace)
    result = run_controlled_coding_loop(
        "inspect staged validation",
        runtime,
        workspace=workspace,
        workflow=workflow,
        options=ControlledLoopOptions(1, True, True, True, False),
        checkpoint_store=store,
    )

    inspection = inspect_coding_workflow(
        workspace=workspace,
        workflow_id=result.session.id,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )

    assert inspection.decision == CodingWorkflowDecision.AWAITING_VALIDATION_APPROVAL
    assert inspection.action_id == result.validation_staging.approval_token  # type: ignore[union-attr]


def test_controlled_loop_consumed_validation_result_is_ready_for_batch_3b_resume(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    sandbox = ProvenanceWritingSandboxExecutor(workspace)
    runtime = _real_runtime(workspace, ScopedContextRecordingLLMClient(), sandbox_executor=sandbox)
    workflow = prepare_coding_workflow("consume staged validation", workspace=workspace)
    workflow.validation_plan = ValidationPlan(commands=[ValidationCommand(command="python -m pytest tests/coding -q")])
    store = CodingWorkflowCheckpointStore(workspace)
    result = run_controlled_coding_loop(
        "consume staged validation",
        runtime,
        workspace=workspace,
        workflow=workflow,
        options=ControlledLoopOptions(1, True, True, True, False),
        checkpoint_store=store,
    )
    assert result.validation_staging is not None

    persisted = runtime.execute_and_persist_approved_action(
        session_id=runtime.session_id,
        approval_token=result.validation_staging.approval_token or "",
        expected_action_id=result.validation_staging.approval_token,
    )
    inspection = inspect_coding_workflow(
        workspace=workspace,
        workflow_id=result.session.id,
        session_store=runtime.session_store,
        checkpoint_store=store,
    )

    assert persisted.status == ExecutePersistedActionStatus.PERSISTED
    assert len(sandbox.requests) == 1
    assert inspection.decision == CodingWorkflowDecision.VALIDATION_RESULT_READY
    assert inspection.action_id == result.validation_staging.approval_token
