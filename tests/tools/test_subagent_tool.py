from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.subagents.specs import SubAgentRunResult
from pp_agent.tools.subagent_tool import OrchestrateAgentsTool, SpawnSubagentTool


class StubSessionHost:
    pass


class FakeRegistry:
    def __init__(self) -> None:
        self.current_session_id = "fake-session"


class FakeSessionStore:
    def __init__(self, session_id: str, messages: list[ChatMessage] | None = None) -> None:
        self._session_id = session_id
        self._messages = messages or []

    def load(self, session_id: str):
        assert session_id == self._session_id
        return SimpleNamespace(active_head_id="parent-head-1", messages=list(self._messages))

    def branch_messages(self, record, head_id):
        _ = record, head_id
        return list(self._messages)


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
        def __init__(
            self,
            *,
            workspace,
            session_host,
            parent_registry,
            session_store,
            runtime_factory,
            specs=None,
            event_sink=None,
            cancellation_token=None,
        ) -> None:
            _ = workspace, session_host, parent_registry, session_store, runtime_factory, specs, event_sink, cancellation_token

        def run_sync(self, *, parent_session_id, parent_head_id, spec_name, task, cancellation_token=None):
            _ = parent_head_id, cancellation_token
            calls.append((parent_session_id, spec_name, task))
            return SubAgentRunResult(
                spec_name="repo-researcher",
                session_id="child-session-1",
                active_head_id="child-head-1",
                summary="thin summary",
                findings=["thin summary"],
                recommended_next_action="proceed",
                inspected_paths=["src"],
                confidence="high",
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
    assert result.content.startswith("Subagent success")
    assert "Summary: thin summary" in result.content
    assert result.details["success"] is True
    assert result.details["session_id"] == "child-session-1"
    assert result.details["event_count"] == 3
    assert result.details["tool_calls_used"] == ["read_file"]
    assert result.details["final_text"].startswith("Findings")
    assert "events" not in result.details
    assert "messages" not in result.details
    assert calls == [(session_id, "repo-researcher", "Read the notes and summarize them.")]


def test_spawn_subagent_tool_returns_failure_summary(tmp_path: Path, monkeypatch) -> None:
    tool, session_id = _make_tool(tmp_path)
    calls: list[str] = []

    class FakeManager:
        def __init__(
            self,
            *,
            workspace,
            session_host,
            parent_registry,
            session_store,
            runtime_factory,
            specs=None,
            event_sink=None,
            cancellation_token=None,
        ) -> None:
            _ = workspace, session_host, parent_registry, session_store, runtime_factory, specs, event_sink, cancellation_token

        def run_sync(self, *, parent_session_id, parent_head_id, spec_name, task, cancellation_token=None):
            _ = parent_head_id, task, cancellation_token
            calls.append(parent_session_id)
            return SubAgentRunResult(
                spec_name=spec_name,
                session_id="",
                active_head_id=None,
                summary="Subagent 'missing-spec' is not available.",
                findings=["Subagent run failed: missing spec"],
                recommended_next_action="retry",
                inspected_paths=[],
                confidence="low",
                final_text="Findings\n- Subagent run failed: missing spec\n\nRecommended next action\n- retry\n\nFiles/paths inspected\n- None\n\nConfidence\n- low\n",
                tool_calls_used=[],
                event_count=0,
                success=False,
                error_message="Subagent 'missing-spec' is not available.",
                failure_kind="spec_not_found",
            )

    monkeypatch.setattr("pp_agent.tools.subagent_tool._get_subagent_manager_class", lambda: FakeManager)

    result = tool.execute({"subagent_type": "missing-spec", "task": "anything"})

    assert result.is_error is True
    assert result.content.startswith("Subagent failed")
    assert result.details["success"] is False
    assert result.details["error_message"] == "Subagent 'missing-spec' is not available."
    assert result.details["failure_kind"] == "spec_not_found"
    assert calls == [session_id]


def test_orchestrate_agents_tool_canonicalizes_explicit_edit_contract(tmp_path: Path, monkeypatch) -> None:
    session_id = "parent-session-1"
    latest_user = (
        "\u4e0d\u8981\u76f4\u63a5\u8c03\u7528 edit_file/write_file.\n"
        "\u8bf7\u5fc5\u987b\u4f7f\u7528 orchestrate_agents.\n"
        "workflow=code_change\nallow_edits=true\nmax_agents=6\n\n"
        "\u4efb\u52a1\uff1a\u521b\u5efa docs/worktree-smoke-web.md\uff0c\u5185\u5bb9\u53ea\u5199\u4e00\u884c\uff1a\n"
        "pp-Echo isolated worktree smoke test"
    )
    session_store = FakeSessionStore(
        session_id,
        messages=[ChatMessage(role="user", content=[TextPart(text=latest_user)], timestamp=1.0)],
    )
    captured: dict[str, object] = {}

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            captured["init"] = kwargs

        def run(
            self,
            *,
            goal,
            workflow,
            max_agents,
            allow_edits,
            run_timeout_seconds,
            max_agents_explicit,
        ):
            captured.update(
                {
                    "goal": goal,
                    "workflow": workflow,
                    "max_agents": max_agents,
                    "allow_edits": allow_edits,
                    "run_timeout_seconds": run_timeout_seconds,
                    "max_agents_explicit": max_agents_explicit,
                }
            )
            payload = {
                "success": True,
                "partial_success": False,
                "workflow": workflow,
                "final_summary": "ok",
                "steps": [],
                "recommended_next_action": "done",
            }
            return SimpleNamespace(success=True, partial_success=False, to_dict=lambda: dict(payload))

    monkeypatch.setattr("pp_agent.tools.subagent_tool.SubAgentOrchestrator", FakeOrchestrator)

    tool = OrchestrateAgentsTool(
        tmp_path,
        session_host=StubSessionHost(),  # type: ignore[arg-type]
        session_store=session_store,  # type: ignore[arg-type]
        parent_registry=FakeRegistry(),  # type: ignore[arg-type]
        current_session_id=session_id,
        runtime_factory=None,
    )

    result = tool.execute({"goal": "create the smoke file", "workflow": "research", "allow_edits": False, "max_agents": 2})

    assert result.is_error is False
    assert captured["goal"] == latest_user
    assert captured["workflow"] == "code_change"
    assert captured["allow_edits"] is True
    assert captured["max_agents"] == 6
    assert result.details["orchestrated_edit_contract"]["goal_source"] == "latest_user_message"
    assert result.details["orchestrated_edit_contract"]["original_tool_goal"] == "create the smoke file"


def test_orchestrate_agents_render_mentions_patch_artifact_state(tmp_path: Path, monkeypatch) -> None:
    session_id = "parent-session-1"
    session_store = FakeSessionStore(session_id)

    class FakeOrchestrator:
        def __init__(self, **_kwargs) -> None:
            pass

        def run(
            self,
            *,
            goal,
            workflow,
            max_agents,
            allow_edits,
            run_timeout_seconds,
            max_agents_explicit,
        ):
            _ = goal, max_agents, allow_edits, run_timeout_seconds, max_agents_explicit
            payload = {
                "success": True,
                "partial_success": False,
                "workflow": workflow,
                "final_summary": (
                    "Multi-agent code_change completed. Patch artifact token(s): token-1. "
                    "Pending changed path(s): docs/worktree-smoke-web.md. "
                    "Status: staged only, not applied to the main workspace."
                ),
                "steps": [
                    {
                        "agent": "code-worker",
                        "status": "success",
                        "summary": "Patch artifact ready.",
                        "session_id": "child-session-1",
                        "inspected_paths": ["docs/worktree-smoke-web.md"],
                        "staged_actions": [
                            {
                                "token": "token-1",
                                "action_type": "apply_patch_artifact",
                                "changed_paths": ["docs/worktree-smoke-web.md"],
                            }
                        ],
                    }
                ],
                "recommended_next_action": "Use the Approval panel or approve_pending_action first.",
            }
            return SimpleNamespace(success=True, partial_success=False, to_dict=lambda: dict(payload))

    monkeypatch.setattr("pp_agent.tools.subagent_tool.SubAgentOrchestrator", FakeOrchestrator)

    tool = OrchestrateAgentsTool(
        tmp_path,
        session_host=StubSessionHost(),  # type: ignore[arg-type]
        session_store=session_store,  # type: ignore[arg-type]
        parent_registry=FakeRegistry(),  # type: ignore[arg-type]
        current_session_id=session_id,
        runtime_factory=None,
    )

    result = tool.execute({"goal": "create the smoke file", "workflow": "code_change", "allow_edits": True, "max_agents": 6})

    assert "staged patch artifacts: token-1" in result.content
    assert "pending changed paths: docs/worktree-smoke-web.md" in result.content
    assert "status: staged only, not applied to the main workspace" in result.content
    assert "Approval panel or approve_pending_action" in result.content
