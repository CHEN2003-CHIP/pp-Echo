from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pp_agent.runtime.session_host import SessionHost
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.storage.checkpoints import CheckpointStore
from pp_agent.storage.models import StoredModelConfig
from pp_agent.storage.sessions import SessionStore
from pp_agent.subagents.manager import SubAgentManager
from pp_agent.subagents.specs import SubAgentSpec
from pp_agent.tools.registry import ToolRegistry


class MinimalRuntime:
    def __init__(self, session_store: SessionStore, session_id: str) -> None:
        self.session_store = session_store
        self.session_id = session_id
        self.state = SimpleNamespace(system_prompt="system", messages=[], model=SimpleNamespace(), turn=SimpleNamespace(turn_id=0))
        self.require_plan_approval = False
        self.tool_registry = ToolRegistry(session_store.root.parent, current_session_id=session_id)

    def restore_session_record(self, record, *, emit_event: bool = True) -> None:
        _ = record, emit_event

    def _event(self, event_type: str, **kwargs):
        return SimpleNamespace(type=event_type, **kwargs)

    def _queue_lifecycle_event(self, event) -> None:
        _ = event

    def _emit(self, event):
        return [event]

    def prompt(self, prompt_text: str):
        _ = prompt_text
        self.state.messages = []
        return []


def _host(tmp_path: Path) -> SessionHost:
    session_store = SessionStore(tmp_path / "sessions")

    def runtime_factory(workspace: Path, record, lifecycle_subscribers=None):
        _ = workspace, lifecycle_subscribers
        return MinimalRuntime(session_store, record.id)

    return SessionHost(
        runtime_factory=runtime_factory,
        session_store_factory=lambda _workspace: session_store,
        pending_action_store_factory=lambda workspace: PendingActionStore(workspace / "pending"),
        session_defaults_factory=lambda _workspace: {"system_prompt": "parent system", "model": StoredModelConfig()},
        checkpoint_store_factory=lambda workspace: CheckpointStore(workspace / "checkpoints"),
    )


def test_subagent_manager_reports_missing_spec(tmp_path: Path) -> None:
    host = _host(tmp_path)
    parent_runtime = host.create_session(tmp_path)
    session_store = SessionStore(tmp_path / "sessions")
    manager = SubAgentManager(
        workspace=tmp_path,
        session_host=host,
        parent_registry=ToolRegistry(tmp_path, current_session_id=parent_runtime.session_id),
        session_store=session_store,
        runtime_factory=host._runtime_factory,
    )

    result = manager.run_sync(
        parent_session_id=parent_runtime.session_id,
        parent_head_id=None,
        spec_name="missing-spec",
        task="Inspect repo",
    )

    assert result.success is False
    assert result.failure_kind == "spec_not_found"


def test_subagent_manager_rejects_unknown_allowlist_tool(tmp_path: Path) -> None:
    host = _host(tmp_path)
    parent_runtime = host.create_session(tmp_path)
    session_store = SessionStore(tmp_path / "sessions")
    manager = SubAgentManager(
        workspace=tmp_path,
        session_host=host,
        parent_registry=ToolRegistry(tmp_path, current_session_id=parent_runtime.session_id),
        session_store=session_store,
        runtime_factory=host._runtime_factory,
        specs={
            "broken": SubAgentSpec(
                name="broken",
                description="Broken tool allowlist",
                system_prompt="Do nothing",
                tool_allowlist=["missing_tool"],
            )
        },
    )

    result = manager.run_sync(
        parent_session_id=parent_runtime.session_id,
        parent_head_id=None,
        spec_name="broken",
        task="Inspect repo",
    )

    assert result.success is False
    assert result.failure_kind == "tool_validation_failed"


def test_subagent_manager_rejects_tool_result_fallback_as_unreliable_summary(tmp_path: Path) -> None:
    host = _host(tmp_path)
    parent_runtime = host.create_session(tmp_path)
    session_store = SessionStore(tmp_path / "sessions")

    class FallbackRuntime(MinimalRuntime):
        def prompt(self, prompt_text: str):
            _ = prompt_text
            self.state.messages = [
                SimpleNamespace(
                    role="assistant",
                    content=[SimpleNamespace(text="# README\n\nRaw file content, not a summary.")],
                )
            ]
            return [
                SimpleNamespace(type="tool_call", tool_name="read_file", details={}),
                SimpleNamespace(type="provider_response", tool_name=None, details={"fallback": "tool_results"}),
            ]

    def runtime_factory(workspace: Path, record, lifecycle_subscribers=None):
        _ = workspace, lifecycle_subscribers
        return FallbackRuntime(session_store, record.id)

    manager = SubAgentManager(
        workspace=tmp_path,
        session_host=host,
        parent_registry=ToolRegistry(tmp_path, current_session_id=parent_runtime.session_id),
        session_store=session_store,
        runtime_factory=runtime_factory,
    )

    result = manager.run_sync(
        parent_session_id=parent_runtime.session_id,
        parent_head_id=None,
        spec_name="repo-researcher",
        task="Summarize README.md",
    )

    assert result.success is False
    assert result.failure_kind == "invalid_summary"
    assert "empty response after tool results" in (result.error_message or "")


def test_subagent_manager_rejects_overlong_or_missing_sections_as_invalid_summary(tmp_path: Path) -> None:
    host = _host(tmp_path)
    parent_runtime = host.create_session(tmp_path)
    session_store = SessionStore(tmp_path / "sessions")
    parent_events: list[dict] = []

    class InvalidSummaryRuntime(MinimalRuntime):
        def prompt(self, prompt_text: str):
            _ = prompt_text
            self.state.messages = [
                SimpleNamespace(
                    role="assistant",
                    content=[SimpleNamespace(text="Summary\n- " + ("raw content " * 400))],
                )
            ]
            return [SimpleNamespace(type="tool_call", tool_name="read_file", details={})]

    def runtime_factory(workspace: Path, record, lifecycle_subscribers=None):
        _ = workspace, lifecycle_subscribers
        return InvalidSummaryRuntime(session_store, record.id)

    manager = SubAgentManager(
        workspace=tmp_path,
        session_host=host,
        parent_registry=ToolRegistry(tmp_path, current_session_id=parent_runtime.session_id),
        session_store=session_store,
        runtime_factory=runtime_factory,
        event_sink=lambda event_type, **payload: parent_events.append({"type": event_type, **payload}),
    )

    result = manager.run_sync(
        parent_session_id=parent_runtime.session_id,
        parent_head_id=None,
        spec_name="repo-researcher",
        task="Summarize README.md",
    )

    assert result.success is False
    assert result.failure_kind == "invalid_summary"
    assert parent_events
    assert parent_events[-1]["type"] == "subagent_fail"
    assert parent_events[-1]["is_error"] is False


def test_subagent_manager_accepts_markdown_heading_summary(tmp_path: Path) -> None:
    host = _host(tmp_path)
    parent_runtime = host.create_session(tmp_path)
    session_store = SessionStore(tmp_path / "sessions")

    class MarkdownSummaryRuntime(MinimalRuntime):
        def prompt(self, prompt_text: str):
            _ = prompt_text
            self.state.messages = [
                SimpleNamespace(
                    role="assistant",
                    content=[
                        SimpleNamespace(
                            text=(
                                "### 0. Summary\n"
                                "- Quick repo scan\n\n"
                                "### 1. Findings\n"
                                "- Found runtime hook path\n\n"
                                "### 2. Recommended next action\n"
                                "- Continue with the parent report\n\n"
                                "### 3. Files/paths inspected\n"
                                "- src/pp_agent/runtime/runtime.py\n\n"
                                "### 4. Confidence\n"
                                "- high\n"
                            )
                        )
                    ],
                )
            ]
            return [SimpleNamespace(type="tool_call", tool_name="read_file", details={})]

    def runtime_factory(workspace: Path, record, lifecycle_subscribers=None):
        _ = workspace, lifecycle_subscribers
        return MarkdownSummaryRuntime(session_store, record.id)

    manager = SubAgentManager(
        workspace=tmp_path,
        session_host=host,
        parent_registry=ToolRegistry(tmp_path, current_session_id=parent_runtime.session_id),
        session_store=session_store,
        runtime_factory=runtime_factory,
    )

    result = manager.run_sync(
        parent_session_id=parent_runtime.session_id,
        parent_head_id=None,
        spec_name="repo-researcher",
        task="Summarize README.md",
    )

    assert result.success is True
    assert result.failure_kind is None
    assert result.summary == "Quick repo scan"
    assert result.findings == ["Found runtime hook path"]
