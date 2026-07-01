from __future__ import annotations

import json
from pathlib import Path

from pp_agent.coding import ControlledLoopOptions, ControlledToolLoopResult, prepare_coding_workflow, run_controlled_coding_loop
from pp_agent.observability.timeline import TimelineBlock
from pp_agent.web import coding_service
from pp_agent.web.coding_service import (
    CodingApprovalNotFound,
    CodingApprovalNotSupported,
    CodingTaskNotFound,
    CodingTaskState,
    CodingWorkflowService,
    InMemoryCodingTaskStore,
    coding_task_state_to_dict,
    extract_validation_commands,
    sanitize_pending_approval,
    summarize_timeline_block,
)


class FakeRuntime:
    def __init__(self) -> None:
        self.prompt_calls: list[str] = []
        self.runtime_execution_context = None

    def prompt(self, text: str):
        self.prompt_calls.append(text)
        return []


def _workspace(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "src" / "pp_agent" / "web").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "web").mkdir(parents=True, exist_ok=True)
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")
    return tmp_path


def _controlled_result(tmp_path: Path, *, pending: list[dict] | None = None) -> ControlledToolLoopResult:
    workspace = _workspace(tmp_path)
    result = run_controlled_coding_loop(
        "add web coding service",
        FakeRuntime(),
        workspace=workspace,
        options=ControlledLoopOptions(0, True, True, True, True),
    )
    result.status = "awaiting_approval"
    result.stop_reason = "approval_required"
    result.pending_approvals = pending or []
    result.summary_text = "controlled summary"
    return result


def test_start_task_prepare_only_returns_prepared_state(tmp_path: Path) -> None:
    service = CodingWorkflowService(_workspace(tmp_path))

    state = service.start_task("add web coding service", prepare_only=True)

    assert state.status == "prepared"
    assert state.stop_reason is None
    assert state.workflow_summary
    assert state.timeline_blocks
    assert state.pending_approvals == []
    assert state.runtime_counters == {"tool_calls": 0, "shell_commands": 0, "patch_candidates": 0}
    assert state.validation_commands


def test_start_task_prepare_only_does_not_run_controlled_loop(monkeypatch, tmp_path: Path) -> None:
    def fail_loop(*args, **kwargs):
        raise AssertionError("prepare-only must not run controlled loop")

    monkeypatch.setattr(coding_service, "run_controlled_coding_loop", fail_loop)
    service = CodingWorkflowService(_workspace(tmp_path))

    state = service.start_task("add web coding service", prepare_only=True)

    assert state.status == "prepared"


def test_start_task_controlled_loop_returns_state(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run_loop(task, runtime, workspace=None, options=None):
        captured["task"] = task
        captured["runtime"] = runtime
        captured["workspace"] = workspace
        captured["options"] = options
        return _controlled_result(
            tmp_path,
            pending=[
                {
                    "token": "tok-1",
                    "action_type": "run_shell",
                    "tool_name": "run_shell",
                    "summary": "Run validation",
                    "command": "python -m pytest tests/web -q",
                    "payload": {"secret": "hidden"},
                }
            ],
        )

    runtime = FakeRuntime()
    monkeypatch.setattr(coding_service, "run_controlled_coding_loop", fake_run_loop)
    service = CodingWorkflowService(_workspace(tmp_path), runtime_factory=lambda workspace: runtime)

    state = service.start_task("add web coding service", max_turns=5)

    options = captured["options"]
    assert state.status == "awaiting_approval"
    assert state.stop_reason == "approval_required"
    assert state.pending_approvals[0]["token"] == "tok-1"
    assert state.pending_approvals[0]["command"] == "python -m pytest tests/web -q"
    assert captured["runtime"] is runtime
    assert options.max_model_turns == 5
    assert options.stop_on_approval is True
    assert options.stop_on_guardrail_block is True
    assert options.stop_on_scope_block is True
    assert options.dry_run is False


def test_service_state_is_json_friendly(tmp_path: Path) -> None:
    service = CodingWorkflowService(_workspace(tmp_path))
    state = service.start_task("add web coding service", prepare_only=True)

    payload = coding_task_state_to_dict(state)

    assert payload["task_id"] == state.task_id
    json.dumps(payload)


def test_sanitize_pending_approval_hides_payload() -> None:
    approval = {
        "token": "tok-2",
        "action_type": "apply_patch_candidate",
        "tool_name": "apply_patch_candidate",
        "summary": "Apply patch",
        "changed_files": ["src/pp_agent/web/coding_service.py"],
        "command": None,
        "scope_check": {"allowed": True, "reason": "inside scope", "payload": "hidden"},
        "payload": {"secret": "do-not-print"},
        "details": {"content_text": "file contents must stay hidden"},
    }

    sanitized = sanitize_pending_approval(approval)
    encoded = json.dumps(sanitized)

    assert sanitized["token"] == "tok-2"
    assert sanitized["scope_check"]["reason"] == "inside scope"
    assert "do-not-print" not in encoded
    assert "file contents must stay hidden" not in encoded


def test_timeline_summary_hides_large_details() -> None:
    block = TimelineBlock(
        id="block-1",
        run_id=None,
        type="controlled_tool_loop",
        status="waiting_approval",
        title="Waiting for approval",
        content="x" * 1000,
        details={
            "stop_reason": "approval_required",
            "pending_approvals_count": 1,
            "payload": {"secret": "hidden"},
            "manifest": "large manifest",
            "diff": "large diff",
            "content_text": "file content",
        },
    )

    summary = summarize_timeline_block(block)
    encoded = json.dumps(summary)

    assert summary["type"] == "controlled_tool_loop"
    assert summary["details"] == {"stop_reason": "approval_required", "pending_approvals_count": 1}
    assert len(summary["summary"]) <= 500
    assert "hidden" not in encoded
    assert "large diff" not in encoded
    assert "file content" not in encoded


def test_get_task_returns_stored_state(tmp_path: Path) -> None:
    service = CodingWorkflowService(_workspace(tmp_path))
    state = service.start_task("add web coding service", prepare_only=True)

    assert service.get_task(state.task_id) is state


def test_get_timeline_returns_summary_blocks(tmp_path: Path) -> None:
    service = CodingWorkflowService(_workspace(tmp_path))
    state = service.start_task("add web coding service", prepare_only=True)

    timeline = service.get_timeline(state.task_id)

    assert timeline == state.timeline_blocks
    assert {"type", "title", "status", "summary", "details"} <= set(timeline[0])


def test_get_pending_approvals_returns_sanitized_items(monkeypatch, tmp_path: Path) -> None:
    def fake_run_loop(*args, **kwargs):
        return _controlled_result(
            tmp_path,
            pending=[
                {
                    "token": "tok-3",
                    "action_type": "run_shell",
                    "tool_name": "run_shell",
                    "summary": "Run test",
                    "command": "python -m pytest tests/web -q",
                    "payload": {"secret": "hidden"},
                }
            ],
        )

    monkeypatch.setattr(coding_service, "run_controlled_coding_loop", fake_run_loop)
    service = CodingWorkflowService(_workspace(tmp_path), runtime_factory=lambda workspace: FakeRuntime())
    state = service.start_task("add web coding service")

    approvals = service.get_pending_approvals(state.task_id)

    assert approvals[0]["token"] == "tok-3"
    assert "payload" not in approvals[0]


def test_get_validation_plan_returns_commands(tmp_path: Path) -> None:
    service = CodingWorkflowService(_workspace(tmp_path))
    state = service.start_task("add web coding service", prepare_only=True)

    commands = service.get_validation_plan(state.task_id)

    assert commands
    assert all("command" in command for command in commands)


def test_service_approve_action_calls_existing_approval_path_or_returns_not_supported() -> None:
    calls: list[tuple[Path, str]] = []
    store = InMemoryCodingTaskStore()
    store.create(CodingTaskState(task_id="task-approve", task="approve", status="awaiting_approval", stop_reason="approval_required", pending_approvals=[{"token": "tok-approve", "action_type": "run_shell", "tool_name": "run_shell"}]))

    def approve_handler(workspace: Path, token: str) -> dict:
        calls.append((workspace, token))
        return {"success": True, "result": "approved_and_executed", "resumed": True}

    service = CodingWorkflowService(Path("E:/repo"), store=store, approval_handler=approve_handler)

    updated = service.approve_action("task-approve", "tok-approve")

    assert calls == [(Path("E:/repo"), "tok-approve")]
    assert updated.status == "completed"
    assert updated.pending_approvals == []
    assert updated.timeline_blocks[-1]["details"]["approval_action"] == "approve"


def test_service_approve_action_returns_not_supported() -> None:
    store = InMemoryCodingTaskStore()
    store.create(CodingTaskState(task_id="task-approve", task="approve", status="awaiting_approval", pending_approvals=[{"token": "tok-approve", "action_type": "run_shell"}]))

    def approve_handler(_workspace: Path, _token: str) -> dict:
        raise CodingApprovalNotSupported("approval backend unavailable")

    service = CodingWorkflowService(store=store, approval_handler=approve_handler)

    try:
        service.approve_action("task-approve", "tok-approve")
    except CodingApprovalNotSupported as exc:
        assert "approval backend unavailable" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected not supported")


def test_service_reject_action_removes_or_marks_pending_approval() -> None:
    calls: list[tuple[str, str | None]] = []
    store = InMemoryCodingTaskStore()
    store.create(CodingTaskState(task_id="task-reject", task="reject", status="awaiting_approval", stop_reason="approval_required", pending_approvals=[{"token": "tok-reject", "action_type": "apply_patch_candidate"}]))

    def reject_handler(_workspace: Path, token: str, reason: str | None = None) -> dict:
        calls.append((token, reason))
        return {"success": True, "result": "rejected", "resumed": False}

    service = CodingWorkflowService(store=store, reject_handler=reject_handler)

    updated = service.reject_action("task-reject", "tok-reject", reason="Not needed")

    assert calls == [("tok-reject", "Not needed")]
    assert updated.status == "completed"
    assert updated.pending_approvals == []
    assert updated.timeline_blocks[-1]["details"]["approval_action"] == "reject"


def test_service_approve_action_unknown_task() -> None:
    service = CodingWorkflowService(store=InMemoryCodingTaskStore())

    try:
        service.approve_action("missing", "tok")
    except CodingTaskNotFound as exc:
        assert "coding task not found" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected missing task")


def test_service_approve_action_unknown_token() -> None:
    store = InMemoryCodingTaskStore()
    store.create(CodingTaskState(task_id="task", task="task", status="awaiting_approval", pending_approvals=[]))
    service = CodingWorkflowService(store=store)

    try:
        service.approve_action("task", "missing")
    except CodingApprovalNotFound as exc:
        assert "pending approval not found" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected missing token")


def test_service_reject_action_does_not_execute_action() -> None:
    store = InMemoryCodingTaskStore()
    store.create(CodingTaskState(task_id="task-reject", task="reject", status="awaiting_approval", pending_approvals=[{"token": "tok-reject", "action_type": "run_shell", "command": "danger"}]))

    def reject_handler(_workspace: Path, _token: str, _reason: str | None = None) -> dict:
        raise CodingApprovalNotSupported("reject backend unavailable")

    service = CodingWorkflowService(store=store, reject_handler=reject_handler)

    updated = service.reject_action("task-reject", "tok-reject")

    assert updated.pending_approvals == []
    assert any("service layer" in warning for warning in updated.warnings)


def test_in_memory_store_lists_recent_states() -> None:
    store = InMemoryCodingTaskStore()
    first = store.create(CodingTaskState(task_id="one", task="one", status="prepared"))
    second = store.create(CodingTaskState(task_id="two", task="two", status="prepared"))

    assert store.get("one") is first
    assert store.list_recent() == [second, first]
    assert store.list_recent(limit=1) == [second]


def test_extract_validation_commands_accepts_workflow(tmp_path: Path) -> None:
    workflow = prepare_coding_workflow("add web coding service", workspace=_workspace(tmp_path))

    commands = extract_validation_commands(workflow)

    assert commands
    assert commands[0]["command"]


def test_service_public_models_have_docstrings() -> None:
    assert CodingTaskState.__doc__
    assert InMemoryCodingTaskStore.__doc__
    assert CodingWorkflowService.__doc__
    assert InMemoryCodingTaskStore.create.__doc__
    assert InMemoryCodingTaskStore.get.__doc__
    assert InMemoryCodingTaskStore.update.__doc__
    assert InMemoryCodingTaskStore.list_recent.__doc__
    assert CodingWorkflowService.start_task.__doc__
    assert CodingWorkflowService.get_task.__doc__
    assert CodingWorkflowService.get_timeline.__doc__
    assert CodingWorkflowService.get_pending_approvals.__doc__
    assert CodingWorkflowService.get_validation_plan.__doc__
    assert CodingWorkflowService.approve_action.__doc__
    assert CodingWorkflowService.reject_action.__doc__


def test_service_public_helpers_have_docstrings() -> None:
    assert coding_task_state_to_dict.__doc__
    assert sanitize_pending_approval.__doc__
    assert summarize_timeline_block.__doc__
    assert extract_validation_commands.__doc__
