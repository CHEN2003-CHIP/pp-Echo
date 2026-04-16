from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pp_agent.subagents.specs import SubAgentRunResult
from pp_agent.tools.subagent_tool import SpawnSubagentTool


class StubSessionHost:
    pass


class FakeRegistry:
    def __init__(self) -> None:
        self.current_session_id = "fake-session"


class FakeSessionStore:
    def __init__(self, session_id: str) -> None:
        self._session_id = session_id

    def load(self, session_id: str):
        assert session_id == self._session_id
        return SimpleNamespace(active_head_id="parent-head-1")


def _make_tool(tmp_path: Path) -> tuple[SpawnSubagentTool, str]:
    session_id = "parent-session-1"
    session_store = FakeSessionStore(session_id)
    registry = FakeRegistry()
    tool = SpawnSubagentTool(
        tmp_path,
        session_host=StubSessionHost(),  # type: ignore[arg-type]
        session_store=session_store,
        parent_registry=registry,  # type: ignore[arg-type]
        current_session_id=session_id,
        runtime_factory=None,
    )
    return tool, session_id


def test_spawn_subagent_tool_returns_summary_only(tmp_path: Path, monkeypatch) -> None:
    tool, session_id = _make_tool(tmp_path)
    calls: list[tuple[str, str, str]] = []

    class FakeManager:
        def __init__(self, *, workspace, session_host, parent_registry, session_store, runtime_factory) -> None:
            _ = workspace, session_host, parent_registry, session_store, runtime_factory

        def run_sync(self, *, parent_session_id, parent_head_id, spec_name, task):
            _ = parent_head_id
            calls.append((parent_session_id, spec_name, task))
            return SubAgentRunResult(
                spec_name="repo-researcher",
                session_id="child-session-1",
                active_head_id="child-head-1",
                final_text="Findings\n- thin summary\n\nRecommended next action\n- proceed\n\nFiles/paths inspected\n- src\n\nConfidence\n- high",
                tool_calls_used=["read_file"],
                event_count=3,
                success=True,
                error_message=None,
            )

    monkeypatch.setattr("pp_agent.tools.subagent_tool._get_subagent_manager_class", lambda: FakeManager)

    result = tool.execute(
        {"subagent_type": "repo-researcher", "task": "Read the notes and summarize them."}
    )

    assert result.is_error is False
    assert result.content.startswith("Findings")
    assert result.content == "Findings\n- thin summary\n\nRecommended next action\n- proceed\n\nFiles/paths inspected\n- src\n\nConfidence\n- high"
    assert result.details["success"] is True
    assert result.details["session_id"] == "child-session-1"
    assert result.details["event_count"] == 3
    assert result.details["tool_calls_used"] == ["read_file"]
    assert "events" not in result.details
    assert "messages" not in result.details
    assert calls == [(session_id, "repo-researcher", "Read the notes and summarize them.")]


def test_spawn_subagent_tool_returns_failure_summary(tmp_path: Path, monkeypatch) -> None:
    tool, session_id = _make_tool(tmp_path)
    calls: list[str] = []

    class FakeManager:
        def __init__(self, *, workspace, session_host, parent_registry, session_store, runtime_factory) -> None:
            _ = workspace, session_host, parent_registry, session_store, runtime_factory

        def run_sync(self, *, parent_session_id, parent_head_id, spec_name, task):
            _ = parent_head_id, task
            calls.append(parent_session_id)
            return SubAgentRunResult(
                spec_name=spec_name,
                session_id="",
                active_head_id=None,
                final_text="Findings\n- Subagent run failed: missing spec\n\nRecommended next action\n- retry\n\nFiles/paths inspected\n- None\n\nConfidence\n- low\n",
                tool_calls_used=[],
                event_count=0,
                success=False,
                error_message="Subagent 'missing-spec' is not available.",
            )

    monkeypatch.setattr("pp_agent.tools.subagent_tool._get_subagent_manager_class", lambda: FakeManager)

    result = tool.execute({"subagent_type": "missing-spec", "task": "anything"})

    assert result.is_error is True
    assert "Subagent run failed" in result.content
    assert result.details["success"] is False
    assert result.details["error_message"] == "Subagent 'missing-spec' is not available."
    assert calls == [session_id]
