from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pp_agent.coding import (
    ControlledLoopOptions,
    ControlledToolLoopResult,
    collect_pending_approvals,
    controlled_loop_result_to_block,
    controlled_loop_result_to_context_item,
    controlled_loop_result_to_summary,
    default_controlled_loop_options,
    prepare_coding_workflow,
    run_controlled_coding_loop,
    start_coding_execution_session,
)
from pp_agent.runtime.execution_context import RuntimeExecutionContext
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.tools.effects import build_shell_effect
from pp_agent.tools.policy import PermissionDomain
from pp_agent.tools.registry import ToolRegistry


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


class NoStoreRuntime:
    pass


def _workspace(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "src" / "pp_agent" / "coding").mkdir(parents=True)
    (tmp_path / "tests" / "coding").mkdir(parents=True)
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")
    return tmp_path


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
