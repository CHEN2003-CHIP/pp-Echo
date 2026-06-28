from __future__ import annotations

from pathlib import Path

import pytest

from pp_agent.observability.recorder import TraceRecorder
from pp_agent.observability.store import TraceStore
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.storage.settings import ToolPolicyConfig
from pp_agent.tools.registry import ToolRegistry


def _registry(tmp_path: Path, *, mode: str = "workspace-write") -> tuple[ToolRegistry, TraceStore, TraceRecorder]:
    trace_store = TraceStore(tmp_path)
    recorder = TraceRecorder(trace_store, workspace=tmp_path)
    registry = ToolRegistry(tmp_path, policy=ToolPolicyConfig(permission_mode=mode), observability=recorder)
    return registry, trace_store, recorder


def test_every_tool_execution_attempt_has_policy_decision_before_execution(tmp_path: Path) -> None:
    registry, trace_store, recorder = _registry(tmp_path)
    run_id = recorder.start_run(session_id="s1", user_goal_preview="list")

    registry.execute("list_files", {"path": "."}, tool_call_id="call-list")
    recorder.end_run()
    detail = trace_store.read_run(run_id)

    policy = next(span for span in detail.spans if span.name == "policy.decision")
    tool = next(span for span in detail.spans if span.name == "tool.call")
    assert policy.started_at <= tool.started_at
    assert policy.attributes["policy_action"] == "allow"
    assert policy.attributes["allowed"] is True
    assert policy.attributes["budget_cost"] == 1
    assert policy.attributes["risk_level"] in {"low", "medium", "high"}
    assert policy.attributes["approval_scope"]["session_id"] == "s1"


def test_read_only_mode_blocks_write_and_traces_blocked_attempt(tmp_path: Path) -> None:
    registry, trace_store, recorder = _registry(tmp_path, mode="read-only")
    run_id = recorder.start_run(session_id="s1", user_goal_preview="blocked")

    with pytest.raises(PermissionError):
        registry.execute("write_file", {"path": "blocked.txt", "content": "nope"}, tool_call_id="call-write")
    recorder.end_run(status="blocked")
    detail = trace_store.read_run(run_id)

    assert not (tmp_path / "blocked.txt").exists()
    blocked = next(span for span in detail.spans if span.name == "policy.decision" and span.status == "blocked")
    assert blocked.attributes["read_only"] is True
    assert blocked.attributes["allowed"] is False
    assert blocked.attributes["blocked_reason"]
    assert any(event.name == "tool_policy_denied" for event in detail.events)


def test_approval_required_tool_stages_without_direct_execution(tmp_path: Path) -> None:
    registry, _trace_store, _recorder = _registry(tmp_path)

    result = registry.execute("write_file", {"path": "needs-approval.txt", "content": "pending"}, tool_call_id="call-approval")

    assert result.details["token"]
    assert result.details["policy_decision"] == "ask"
    assert not (tmp_path / "needs-approval.txt").exists()


def test_tool_errors_are_traced(tmp_path: Path) -> None:
    registry, trace_store, recorder = _registry(tmp_path)
    run_id = recorder.start_run(session_id="s1", user_goal_preview="bad read")

    with pytest.raises(FileNotFoundError):
        registry.execute("read_file", {"path": "missing.txt"}, tool_call_id="call-missing")
    recorder.end_run(status="error")
    detail = trace_store.read_run(run_id)

    assert any(span.name == "tool.call" and span.status == "error" for span in detail.spans)


def test_tool_execution_shares_run_scoped_budget_metadata(tmp_path: Path) -> None:
    registry, trace_store, recorder = _registry(tmp_path)
    run_id = recorder.start_run(session_id="s-budget", user_goal_preview="budget")

    registry.execute("list_files", {"path": "."}, tool_call_id="call-budget")
    recorder.end_run(attributes={"budget_scope": "run", "context_used": 1, "context_total_budget": 10})
    detail = trace_store.read_run(run_id)

    assert detail.run is not None
    assert detail.run.attributes["budget_scope"] == "run"
    assert detail.run.attributes["context_used"] <= detail.run.attributes["context_total_budget"]


def test_approval_tokens_are_session_scoped_and_not_reused_across_sessions(tmp_path: Path) -> None:
    registry, _trace_store, _recorder = _registry(tmp_path)
    registry.current_session_id = "session-a"
    first = registry.execute("write_file", {"path": "scoped.txt", "content": "one"}, tool_call_id="call-a")
    token = first.details["token"]

    registry.current_session_id = "session-b"
    second = registry.execute("write_file", {"path": "scoped.txt", "content": "one"}, tool_call_id="call-b")

    assert second.details["token"] != token
    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    assert pending.load(token)["session_id"] == "session-a"
    assert pending.load(second.details["token"])["session_id"] == "session-b"
