from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from agent_core.types import ModelConfig
from pp_agent.cli.commands.approvals import approve_or_execute_pending_action, reject_pending_action
from pp_agent.domain import ChatMessage, TextPart
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.storage.sessions import SessionStore
from pp_agent.tools.registry import ToolRegistry


class NoopLLMClient:
    def __init__(self) -> None:
        self.calls = 0
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        self.calls += 1
        yield {"text": "ok", "tool_calls": [], "finish_reason": "stop", "raw": {}}


def build_agent(tmp_path: Path) -> AgentRuntime:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    agent = AgentRuntime(
        llm_client=NoopLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
        require_plan_approval=False,
    )
    agent.restore_session_record(record)
    return agent


def stage_tool_result(agent: AgentRuntime, tool_name: str, arguments: dict) -> str:
    agent.state.messages.append(ChatMessage(role="user", content=[TextPart(text=f"stage {tool_name}")], timestamp=0.0))
    result = agent.tool_registry.execute(tool_name, arguments)
    result.tool_call_id = "call-1"
    agent._attach_session_to_pending_action(result)
    agent.state.messages.append(result.as_chat_message())
    return str(result.details["token"])


def test_external_approval_result_is_recorded_and_resumed_for_staged_write(tmp_path: Path) -> None:
    agent = build_agent(tmp_path)
    token = stage_tool_result(agent, "write_file", {"path": "a.txt", "content": "hi"})

    assert "approval is still pending" in agent._latest_pending_action_note(agent.state)

    result = approve_or_execute_pending_action(tmp_path, token, render=False, runtime=agent)

    assert result["resumed"] is True
    assert result["session_id"] == agent.session_id
    assert result["event_count"] > 0
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hi"
    assert any(
        message.role == "tool"
        and bool(message.metadata.get("tool_details", {}).get("external_approval_result"))
        for message in agent.state.messages
    )
    assert agent._latest_pending_action_note(agent.state) == ""
    assert agent.llm_client.calls >= 1


def test_shell_failure_details_are_visible_after_external_approval(tmp_path: Path) -> None:
    agent = build_agent(tmp_path)
    token = stage_tool_result(
        agent,
        "run_shell",
        {"command": 'Write-Output "stdout"; Write-Error "stderr"; exit 1'},
    )

    result = approve_or_execute_pending_action(tmp_path, token, render=False, runtime=agent)

    assert result["resumed"] is True
    assert result["success"] is False
    assert result["details"]["command_failed"] is True
    assert result["details"]["exit_code"] == 1
    assert "stdout:" in result["result"]
    assert "stderr:" in result["result"]
    assert any(
        message.role == "tool"
        and bool(message.metadata.get("tool_details", {}).get("external_approval_result"))
        and message.metadata.get("tool_details", {}).get("command_failed") is True
        for message in agent.state.messages
    )


def test_rejected_staged_action_consumes_pending_note(tmp_path: Path) -> None:
    agent = build_agent(tmp_path)
    token = stage_tool_result(agent, "write_file", {"path": "a.txt", "content": "hi"})

    assert "approval is still pending" in agent._latest_pending_action_note(agent.state)

    result = reject_pending_action(tmp_path, token, render=False, runtime=agent)

    assert result["resumed"] is True
    assert result["session_id"] == agent.session_id
    assert any(
        message.role == "tool"
        and message.metadata.get("tool_details", {}).get("approval_status") == "rejected"
        for message in agent.state.messages
    )
    assert agent._latest_pending_action_note(agent.state) == ""
