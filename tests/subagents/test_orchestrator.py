from __future__ import annotations

import threading
import time
from pathlib import Path

from pp_agent.runtime.cancellation import CancellationToken
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.subagents.orchestrator import SubAgentOrchestrator, orchestration_specs, resolve_workflow
from pp_agent.subagents.specs import SubAgentRunResult


class FakeManager:
    def __init__(self, *, delay: float = 0.0, fail_agent: str | None = None, pending_store: PendingActionStore | None = None) -> None:
        self.delay = delay
        self.fail_agent = fail_agent
        self.pending_store = pending_store
        self.calls: list[tuple[str, str]] = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def run_sync(self, *, parent_session_id, parent_head_id, spec_name, task, cancellation_token=None):
        _ = parent_session_id, parent_head_id
        with self.lock:
            self.calls.append((spec_name, task))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                deadline = time.time() + self.delay
                while time.time() < deadline:
                    if cancellation_token is not None and cancellation_token.cancelled:
                        break
                    time.sleep(0.01)
            if cancellation_token is not None and cancellation_token.cancelled:
                return SubAgentRunResult(
                    spec_name=spec_name,
                    session_id=f"child-{spec_name}",
                    active_head_id=None,
                    summary=cancellation_token.reason,
                    findings=[cancellation_token.reason],
                    recommended_next_action="Retry if needed.",
                    inspected_paths=[],
                    confidence="low",
                    tool_calls_used=[],
                    event_count=1,
                    success=False,
                    error_message=cancellation_token.reason,
                    failure_kind="canceled",
                )
            if spec_name == self.fail_agent:
                return SubAgentRunResult(
                    spec_name=spec_name,
                    session_id=f"child-{spec_name}",
                    active_head_id=None,
                    summary="failed",
                    findings=["failed"],
                    recommended_next_action="Inspect failure.",
                    inspected_paths=[],
                    confidence="low",
                    tool_calls_used=[],
                    event_count=1,
                    success=False,
                    error_message="boom",
                    failure_kind="child_runtime_error",
                )
            if spec_name == "code-worker" and self.pending_store is not None:
                self.pending_store.stage(
                    action_type="edit_file",
                    target_path=Path("src/demo.py"),
                    before="old",
                    after="new",
                    details={"diff": "demo"},
                )
            return SubAgentRunResult(
                spec_name=spec_name,
                session_id=f"child-{spec_name}",
                active_head_id=None,
                summary=f"{spec_name} summary",
                findings=[f"{spec_name} finding"],
                recommended_next_action="Continue.",
                inspected_paths=[f"{spec_name}.py"],
                confidence="medium",
                tool_calls_used=["read_file"],
                event_count=2,
                success=True,
                duration_ms=1,
            )
        finally:
            with self.lock:
                self.active -= 1


def test_orchestrator_runs_research_agents_in_parallel(tmp_path: Path) -> None:
    manager = FakeManager(delay=0.05)
    orchestrator = SubAgentOrchestrator(
        workspace=tmp_path,
        manager_factory=lambda _specs: manager,
        parent_session_id="parent",
        parent_head_id="head",
    )

    result = orchestrator.run(goal="Analyze memory architecture", workflow="research", max_agents=3)

    assert result.success is True
    assert result.parallel is True
    assert [step.agent for step in result.steps] == ["memory-scout", "repo-researcher", "api-scout"]
    assert manager.max_active > 1


def test_orchestrator_limits_agents_and_reports_partial_success(tmp_path: Path) -> None:
    manager = FakeManager(fail_agent="test-investigator")
    orchestrator = SubAgentOrchestrator(
        workspace=tmp_path,
        manager_factory=lambda _specs: manager,
        parent_session_id="parent",
        parent_head_id="head",
    )

    result = orchestrator.run(goal="pytest failure", workflow="debug", max_agents=2)

    assert len(result.steps) == 2
    assert result.success is False
    assert result.partial_success is True
    assert any(step.status == "failed" for step in result.steps)


def test_orchestrator_reports_failure_diagnostics_and_safe_fallback(tmp_path: Path) -> None:
    manager = FakeManager(fail_agent="memory-scout")
    orchestrator = SubAgentOrchestrator(
        workspace=tmp_path,
        manager_factory=lambda _specs: manager,
        parent_session_id="parent",
        parent_head_id="head",
    )

    result = orchestrator.run(goal="analyze memory", workflow="research", max_agents=1)

    assert result.success is False
    assert result.partial_success is False
    assert "grep_code or list_files" in result.recommended_next_action
    step = result.steps[0]
    payload = step.to_dict()
    assert payload["session_id"] == "child-memory-scout"
    assert payload["failure_kind"] == "child_runtime_error"
    assert payload["parse_error"] is False


def test_orchestrator_emits_progress_and_observes_cancel(tmp_path: Path) -> None:
    manager = FakeManager(delay=0.2)
    token = CancellationToken()
    events: list[tuple[str, dict[str, object], bool]] = []

    def event_sink(event_type: str, *, details=None, is_error=False, **_kwargs) -> None:
        events.append((event_type, details or {}, is_error))

    orchestrator = SubAgentOrchestrator(
        workspace=tmp_path,
        manager_factory=lambda _specs: manager,
        parent_session_id="parent",
        parent_head_id="head",
        event_sink=event_sink,
        cancellation_token=token,
    )

    def cancel_soon() -> None:
        time.sleep(0.05)
        token.cancel("test_cancel")

    thread = threading.Thread(target=cancel_soon)
    thread.start()
    result = orchestrator.run(goal="analyze memory", workflow="research", max_agents=3, run_timeout_seconds=5)
    thread.join()

    assert result.success is False
    assert any(step.failure_kind == "canceled" for step in result.steps)
    assert any(event_type == "subagent_progress" for event_type, _details, _is_error in events)
    assert any(details.get("status") == "canceled" for _event_type, details, _is_error in events)


def test_orchestrator_collects_staged_edits_when_allowed(tmp_path: Path) -> None:
    store = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits")
    manager = FakeManager(pending_store=store)
    orchestrator = SubAgentOrchestrator(
        workspace=tmp_path,
        manager_factory=lambda _specs: manager,
        parent_session_id="parent",
        parent_head_id="head",
        pending_store=store,
    )

    result = orchestrator.run(goal="implement a demo change", workflow="code_change", max_agents=5, allow_edits=True)

    staged = [action for step in result.steps for action in step.staged_actions]
    assert staged
    assert staged[0]["action_type"] == "edit_file"
    assert "approve selected tokens" in result.recommended_next_action


def test_orchestration_specs_only_grant_edit_tools_when_allowed() -> None:
    readonly = orchestration_specs(allow_edits=False)["code-worker"]
    writable = orchestration_specs(allow_edits=True)["code-worker"]

    assert "edit_file" not in readonly.tool_allowlist
    assert "write_file" not in readonly.tool_allowlist
    assert "edit_file" in writable.tool_allowlist
    assert "write_file" in writable.tool_allowlist
    assert "approve_pending_action" not in writable.tool_allowlist
    assert "spawn_subagent" not in writable.tool_allowlist


def test_resolve_workflow_auto() -> None:
    assert resolve_workflow("fix pytest failure", "auto") == "code_change"
    assert resolve_workflow("why did pytest fail", "auto") == "debug"
    assert resolve_workflow("explain the architecture", "auto") == "research"
