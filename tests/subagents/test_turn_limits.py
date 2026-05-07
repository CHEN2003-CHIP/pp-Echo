from __future__ import annotations

from pathlib import Path

from pp_agent.llm.models import ModelConfig
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.storage.sessions import SessionStore
from pp_agent.subagents.manager import SubAgentManager
from pp_agent.subagents.specs import SubAgentSpec
from pp_agent.tools.registry import ToolRegistry


class TwoTurnLLMClient:
    def __init__(self) -> None:
        self.calls = 0
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None):
        _ = tools
        self.calls += 1
        if self.calls == 1:
            yield {
                "text": "",
                "tool_calls": [{"id": "call-1", "name": "read_file", "arguments_chunk": '{"path":"README.md"}'}],
                "finish_reason": "tool_calls",
                "raw": {},
            }
        else:
            yield {"text": "done", "tool_calls": [], "finish_reason": "stop", "raw": {}}


def test_subagent_manager_enforces_max_turns(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    session_store = SessionStore(tmp_path / "sessions")
    parent_record = session_store.create("system", ModelConfig())
    registry = ToolRegistry(tmp_path, current_session_id=parent_record.id)
    runtime = AgentRuntime(
        llm_client=TwoTurnLLMClient(),
        tool_registry=registry,
        session_store=session_store,
        session_id=parent_record.id,
        system_prompt="system",
        confirm_callback=lambda _name, _args: True,
        require_plan_approval=False,
    )
    runtime.restore_session_record(parent_record)

    class HostStub:
        def fork_session(self, workspace: Path, session_id: str, *, head_id=None, lifecycle_subscribers=None):
            _ = workspace, session_id, head_id, lifecycle_subscribers
            child = session_store.create("child system", ModelConfig())
            session_store.save(child)
            return type("ForkResult", (), {"session_id": child.id, "active_head_id": child.active_head_id})()

    def runtime_factory(workspace: Path, record, lifecycle_subscribers=None):
        _ = workspace, lifecycle_subscribers
        child_runtime = AgentRuntime(
            llm_client=TwoTurnLLMClient(),
            tool_registry=ToolRegistry(tmp_path, current_session_id=record.id),
            session_store=session_store,
            session_id=record.id,
            system_prompt=record.system_prompt,
            confirm_callback=lambda _name, _args: True,
            require_plan_approval=False,
        )
        child_runtime.restore_session_record(record)
        return child_runtime

    manager = SubAgentManager(
        workspace=tmp_path,
        session_host=HostStub(),  # type: ignore[arg-type]
        parent_registry=registry,
        session_store=session_store,
        runtime_factory=runtime_factory,
        specs={
            "limited": SubAgentSpec(
                name="limited",
                description="Limit test",
                system_prompt="Limit test prompt",
                tool_allowlist=["read_file"],
                max_turns=1,
            )
        },
    )

    result = manager.run_sync(
        parent_session_id=parent_record.id,
        parent_head_id=parent_record.active_head_id,
        spec_name="limited",
        task="Read README.md",
    )

    assert result.success is False
    assert result.failure_kind == "turn_limit_reached"


def test_subagent_turn_limit_wrapper_does_not_mutate_shared_client(tmp_path: Path) -> None:
    shared_client = TwoTurnLLMClient()
    session_store = SessionStore(tmp_path / "sessions")
    record = session_store.create("system", ModelConfig())
    runtime = AgentRuntime(
        llm_client=shared_client,
        tool_registry=ToolRegistry(tmp_path, current_session_id=record.id),
        session_store=session_store,
        session_id=record.id,
        system_prompt="system",
        confirm_callback=lambda _name, _args: True,
        require_plan_approval=False,
    )
    runtime.restore_session_record(record)

    from pp_agent.subagents.runtime_adapter import SubAgentRuntimeAdapter

    original_stream_chat = shared_client.stream_chat.__func__
    adapter = SubAgentRuntimeAdapter(runtime)

    try:
        adapter.prompt("Read README.md", max_turns=1)
    except Exception:
        pass

    assert runtime.llm_client is shared_client
    assert shared_client.stream_chat.__func__ is original_stream_chat
