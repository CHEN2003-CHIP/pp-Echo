from collections.abc import Iterator
from pathlib import Path

from agent_core.runtime.hooks import AfterToolCallDecision, BeforeToolCallDecision, RuntimeHooks
from agent_core.runtime.monitor import RuntimeMonitor
from agent_core.runtime.session import AgentSession
from agent_core.types import ChatMessage, ModelConfig, TextPart
from storage.sessions import SessionStore
from storage.timeline import TimelineStore
from tools.pending_actions import PendingActionStore
from tools.registry import ToolRegistry
from pp_agent.runtime.runtime import AgentRuntime


class FakeLLMClient:
    def __init__(self) -> None:
        self.calls = 0
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        self.calls += 1
        if self.calls == 1:
            yield {
                "text": "",
                "tool_calls": [{"id": "call-1", "name": "write_file", "arguments_chunk": '{"path":"a.txt","content":"hi"}'}],
                "finish_reason": "tool_calls",
                "raw": {},
            }
        else:
            yield {"text": "done", "tool_calls": [], "finish_reason": "stop", "raw": {}}


class BrokenLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        yield {"text": "", "tool_calls": [{"id": "call-1", "name": "write_file", "arguments_chunk": '{broken'}], "finish_reason": "tool_calls", "raw": {}}


class NoopLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        yield {"text": "ok", "tool_calls": [], "finish_reason": "stop", "raw": {}}


class EmptyLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        if False:  # pragma: no cover
            yield {"text": "", "tool_calls": [], "finish_reason": "stop", "raw": {}}




class RecordingLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()
        self.seen_user_messages: list[str] = []

    def stream_chat(self, messages, tools=None) -> Iterator[dict]:
        latest_user = next((part.text for message in reversed(messages) if message.role == "user" for part in message.content if isinstance(part, TextPart)), "")
        self.seen_user_messages.append(latest_user)
        yield {"text": f"ack:{latest_user}", "tool_calls": [], "finish_reason": "stop", "raw": {}}

class ToolThenRecordLLMClient:
    def __init__(self) -> None:
        self.calls = 0
        self.model = ModelConfig()
        self.seen_user_messages: list[str] = []
        self.seen_system_messages: list[str] = []

    def stream_chat(self, messages, tools=None) -> Iterator[dict]:
        latest_user = next((part.text for message in reversed(messages) if message.role == "user" for part in message.content if isinstance(part, TextPart)), "")
        system_text = "\n".join(part.text for message in messages if message.role == "system" for part in message.content if isinstance(part, TextPart))
        self.seen_user_messages.append(latest_user)
        self.seen_system_messages.append(system_text)
        self.calls += 1
        if self.calls == 1:
            yield {
                "text": "",
                "tool_calls": [{"id": "call-1", "name": "write_file", "arguments_chunk": '{"path":"a.txt","content":"hi"}'}],
                "finish_reason": "tool_calls",
                "raw": {},
            }
        else:
            yield {"text": f"ack:{latest_user}", "tool_calls": [], "finish_reason": "stop", "raw": {}}


class ToolThenEmptyLLMClient:
    def __init__(self) -> None:
        self.calls = 0
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        self.calls += 1
        if self.calls == 1:
            yield {
                "text": "",
                "tool_calls": [{"id": "call-1", "name": "list_files", "arguments_chunk": '{"path":"src"}'}],
                "finish_reason": "tool_calls",
                "raw": {},
            }
        else:
            if False:  # pragma: no cover
                yield {"text": "", "tool_calls": [], "finish_reason": "stop", "raw": {}}


class FailingToolLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        yield {
            "text": "",
            "tool_calls": [{"id": "call-1", "name": "edit_file", "arguments_chunk": '{"path":"missing.txt","diff":"<<<<<<< SEARCH\\nold\\n=======\\nnew\\n>>>>>>> REPLACE"}'}],
            "finish_reason": "tool_calls",
            "raw": {},
        }


class SelfApproveLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        yield {
            "text": "",
            "tool_calls": [
                {"id": "call-1", "name": "write_file", "arguments_chunk": '{"path":"a.txt","content":"hi"}'},
                {"id": "call-2", "name": "approve_pending_action", "arguments_chunk": '{"token":"fake-token"}'},
            ],
            "finish_reason": "tool_calls",
            "raw": {},
        }


class NetworkMCPToolLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()
        self.calls = 0

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        self.calls += 1
        if self.calls == 1:
            yield {
                "text": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "name": "fetch.fetch_readable",
                        "arguments_chunk": '{"url":"https://example.com/article"}',
                    }
                ],
                "finish_reason": "tool_calls",
                "raw": {},
            }
        else:
            yield {"text": "queued for approval", "tool_calls": [], "finish_reason": "stop", "raw": {}}


def build_agent(tmp_path: Path, llm_client, compact_after_messages: int = 8, require_plan_approval: bool = True) -> AgentSession:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    agent = AgentSession(
        llm_client=llm_client,
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
        compact_after_messages=compact_after_messages,
        require_plan_approval=require_plan_approval,
    )
    agent.restore_session_record(record)
    return agent


def test_agent_session_pauses_high_risk_plan_until_approved(tmp_path: Path) -> None:
    agent = build_agent(tmp_path, FakeLLMClient(), require_plan_approval=True)

    events = agent.prompt("create a file")
    planner_pause = [event for event in events if event.type == "planner_end" and event.details.get("requires_approval")]

    assert planner_pause
    assert agent.state.pending_plan_token is not None
    assert len(agent.state.pending_tool_calls) == 1
    assert (tmp_path / "a.txt").exists() is False

    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list()
    assert pending and pending[0]["action_type"] == "planner_approval"


def test_agent_session_executes_pending_plan_after_approval(tmp_path: Path) -> None:
    agent = build_agent(tmp_path, FakeLLMClient(), require_plan_approval=True)
    agent.prompt("create a file")

    token = agent.state.pending_plan_token
    assert token is not None

    events = agent.approve_pending_plan(token)

    assert any(event.type == "tool_start" for event in events)
    assert (tmp_path / "a.txt").exists() is False
    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list()
    assert any(item["action_type"] == "write_file" and item["target_path"].endswith("a.txt") for item in pending)
    assert any(item["action_type"] == "write_file" and item.get("approval_grant") is None for item in pending)
    assert agent.state.pending_plan_token is None
    assert agent.state.pending_tool_calls == []


def test_agent_runtime_rejects_sensitive_tool_without_host_approval(tmp_path: Path) -> None:
    agent = build_agent(tmp_path, FakeLLMClient(), require_plan_approval=False)

    events = agent.prompt("create a file")

    assert any(event.type == "tool_error" and "host-side approval" in (event.message or "") for event in events)
    assert (tmp_path / "a.txt").exists() is False


def test_agent_runtime_stages_network_mcp_tool_for_host_approval(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    registry = ToolRegistry(tmp_path)
    seen: list[str] = []
    registry.register_function_tool(
        name="fetch.fetch_readable",
        description="Fetch readable webpage content from a URL",
        parameters={"type": "object", "properties": {"url": {"type": "string"}}},
        executor=lambda _workspace, arguments: seen.append(arguments.get("url", "")) or "fetched",
        category="mcp",
        permission_domain="read",
        tool_family="mcp",
        exact_effect_mode="required",
        requests_network_hint=True,
    )
    agent = AgentSession(
        llm_client=NetworkMCPToolLLMClient(),
        tool_registry=registry,
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
        require_plan_approval=False,
    )
    agent.restore_session_record(record)

    events = agent.prompt("fetch this page")

    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list()
    assert seen == []
    assert not any(event.type == "tool_error" for event in events)
    assert any(
        event.type == "tool_result"
        and "Staged mcp call fetch.fetch_readable for host-side approval with token" in (event.message or "")
        for event in events
    )
    assert pending and pending[0]["action_type"] == "run_mcp_tool"
    assert pending[0]["details"]["tool_name"] == "fetch.fetch_readable"

    result = registry.host_execute("approve_pending_action", {"token": pending[0]["token"]})

    assert seen == ["https://example.com/article"]
    assert result.content == "fetched"


def test_runtime_policy_details_include_shared_analysis_fields(tmp_path: Path) -> None:
    agent = build_agent(tmp_path, FakeLLMClient(), require_plan_approval=False)

    events = agent.prompt("create a file")
    tool_error = next(event for event in events if event.type == "tool_error" and event.tool_name == "write_file")

    assert tool_error.details["family"] == "file"
    assert tool_error.details["risk_class"] == "workspace_mutation"
    assert tool_error.details["confidence_band"] == "high"


def test_agent_cannot_self_approve_sensitive_mutation(tmp_path: Path) -> None:
    agent = build_agent(tmp_path, SelfApproveLLMClient(), require_plan_approval=False)

    events = agent.prompt("create and approve a file")

    assert any(event.type == "tool_error" and event.tool_name == "write_file" for event in events)
    assert any(event.type == "tool_error" and event.tool_name == "approve_pending_action" for event in events)
    assert (tmp_path / "a.txt").exists() is False


def test_agent_session_emits_planner_events_before_tool_execution(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "demo.txt").write_text("hello", encoding="utf-8")
    agent = build_agent(tmp_path, ToolThenEmptyLLMClient(), require_plan_approval=False)

    events = agent.prompt("create a file")
    event_types = [event.type for event in events]
    planner_start_index = event_types.index("planner_start")
    first_tool_start_index = event_types.index("tool_start")
    plan_updates = [event for event in events if event.type == "planner_step" and event.plan_step is not None]
    statuses = [event.plan_step.status for event in plan_updates]

    assert planner_start_index < first_tool_start_index
    assert statuses[:3] == ["pending", "in_progress", "completed"]


def test_agent_session_persists_and_resumes_pending_plan(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    agent = AgentSession(
        llm_client=FakeLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
        require_plan_approval=True,
    )
    agent.prompt("create a file")

    restored = store.load(record.id)

    assert restored.pending_plan_token is not None
    assert len(restored.pending_tool_calls) == 1
    assert restored.messages
    assert restored.messages[0].role == "user"


def test_agent_session_emits_error_for_bad_tool_arguments(tmp_path: Path) -> None:
    agent = build_agent(tmp_path, BrokenLLMClient(), require_plan_approval=False)

    events = agent.prompt("create a file")

    assert any(event.type == "error" for event in events)


def test_agent_session_emits_error_for_empty_provider_response(tmp_path: Path) -> None:
    agent = build_agent(tmp_path, EmptyLLMClient(), require_plan_approval=False)

    events = agent.prompt("say something")

    assert any(event.type == "provider_error" for event in events)
    assert any(event.type == "error" and "empty response" in (event.message or "").lower() for event in events)
    assert not any(message.role == "assistant" and not message.content for message in agent.state.messages)


def test_agent_session_falls_back_to_tool_result_when_follow_up_provider_is_empty(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "demo.txt").write_text("hello", encoding="utf-8")
    agent = build_agent(tmp_path, ToolThenEmptyLLMClient(), require_plan_approval=False)

    events = agent.prompt("show me src")

    assert not any(event.type == "error" for event in events)
    assert agent.state.messages[-1].role == "assistant"
    assert "demo.txt" in agent.state.messages[-1].content[0].text


def test_tool_result_fallback_ignores_non_trailing_tool_messages() -> None:
    messages = [
        ChatMessage(role="user", content=[TextPart(text="show me files")], timestamp=1.0),
        ChatMessage(role="tool", content=[TextPart(text="old tool output")], timestamp=2.0),
        ChatMessage(role="assistant", content=[TextPart(text="old summary")], timestamp=3.0),
        ChatMessage(role="user", content=[TextPart(text="who are you")], timestamp=4.0),
    ]

    assert AgentRuntime._tool_result_fallback(messages) == ""


def test_tool_result_fallback_uses_only_trailing_tool_messages() -> None:
    messages = [
        ChatMessage(role="user", content=[TextPart(text="show me src")], timestamp=1.0),
        ChatMessage(role="tool", content=[TextPart(text="demo.txt")], timestamp=2.0),
        ChatMessage(role="tool", content=[TextPart(text="nested/file.txt")], timestamp=3.0),
    ]

    assert AgentRuntime._tool_result_fallback(messages) == "demo.txt\n\nnested/file.txt"


def test_agent_session_marks_plan_step_failed_when_tool_fails(tmp_path: Path) -> None:
    agent = build_agent(tmp_path, FailingToolLLMClient(), require_plan_approval=False)

    events = agent.prompt("edit a missing file")
    failed_steps = [event.plan_step for event in events if event.type == "planner_step" and event.plan_step is not None and event.plan_step.status == "failed"]

    assert failed_steps
    assert any(event.type == "tool_end" and event.is_error for event in events)


def test_agent_session_compacts_old_messages(tmp_path: Path) -> None:
    agent = build_agent(tmp_path, NoopLLMClient(), compact_after_messages=4, require_plan_approval=False)
    agent.state.messages = [
        ChatMessage(role="user", content=[TextPart(text=f"user {index}")], timestamp=float(index))
        for index in range(6)
    ]

    events = agent.prompt("trigger compaction")

    assert any(event.type == "compaction" for event in events)
    assert agent.state.compaction.summary
    assert agent.state.compaction.summarized_message_count > 0


def test_agent_session_applies_transform_context_hook(tmp_path: Path) -> None:
    captured = []

    def transform(_state, messages):
        captured.append(messages[-1].role)
        return messages

    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    agent = AgentSession(
        llm_client=NoopLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
        require_plan_approval=False,
        runtime_hooks=RuntimeHooks(transform_context=[transform]),
    )

    agent.prompt("hello")

    assert captured == ["user"]


def test_agent_session_before_tool_hook_can_reject_tool(tmp_path: Path) -> None:
    def reject_write(_state, call, _registry):
        if call.name == "list_files":
            return BeforeToolCallDecision(action="reject", message="blocked by test hook")
        return BeforeToolCallDecision(action="allow")

    agent = build_agent(
        tmp_path,
        ToolThenEmptyLLMClient(),
        require_plan_approval=False,
    )
    agent.runtime_hooks = RuntimeHooks(before_tool_call=[reject_write])

    events = agent.prompt("show me src")

    assert any(event.type == "tool_end" and event.is_error and event.message == "blocked by test hook" for event in events)


def test_agent_session_after_tool_hook_can_stop_follow_up_loop(tmp_path: Path) -> None:
    def stop_after_write(_state, call, _result):
        if call.name == "list_files":
            return AfterToolCallDecision(continue_loop=False, details={"stopped_by": "test_hook"})
        return AfterToolCallDecision(continue_loop=True)

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "demo.txt").write_text("hello", encoding="utf-8")
    agent = build_agent(tmp_path, ToolThenEmptyLLMClient(), require_plan_approval=False)
    agent.runtime_hooks = RuntimeHooks(after_tool_call=[stop_after_write])

    events = agent.prompt("show me src")

    assert any(event.type == "tool_end" and event.details.get("stopped_by") == "test_hook" for event in events)
    assert not any(event.type == "error" for event in events)


def test_agent_session_processes_queued_messages_with_steering_priority(tmp_path: Path) -> None:
    llm = RecordingLLMClient()
    agent = build_agent(tmp_path, llm, require_plan_approval=False)
    agent.enqueue_message("follow-up later", delivery="follow_up")
    agent.enqueue_message("steer now", delivery="steering")

    events = agent.prompt("start here")

    assert llm.seen_user_messages == ["start here", "steer now", "follow-up later"]
    assert any(event.type == "queue_update" and event.details.get("action") == "dequeued" for event in events)
    assert agent.state.queued_messages == []


def test_agent_session_persists_queued_messages(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    agent = AgentSession(
        llm_client=NoopLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
        require_plan_approval=False,
    )

    queued = agent.enqueue_message("remember this after current work", delivery="follow_up")
    restored = store.load(record.id)

    assert restored.queued_messages[0].id == queued.id
    assert restored.queued_messages[0].text == "remember this after current work"


def test_agent_session_transform_context_mentions_queue_and_planner_state(tmp_path: Path) -> None:
    llm = ToolThenRecordLLMClient()
    agent = build_agent(tmp_path, llm, require_plan_approval=True)
    agent.enqueue_message("steer after approval", delivery="steering")

    agent.prompt("start here")

    assert "Queued steering count: 1" in llm.seen_system_messages[0]
    assert f"Active session id: {agent.session_id}" in llm.seen_system_messages[0]


def test_agent_session_planner_then_steering_then_follow_up_order(tmp_path: Path) -> None:
    llm = ToolThenRecordLLMClient()
    agent = build_agent(tmp_path, llm, require_plan_approval=True)
    agent.enqueue_message("follow-up later", delivery="follow_up")
    agent.enqueue_message("steer now", delivery="steering")

    agent.prompt("start here")
    token = agent.state.pending_plan_token
    assert token is not None

    agent.approve_pending_plan(token)

    assert llm.seen_user_messages == ["start here", "steer now", "follow-up later"]


def test_agent_session_emits_turn_state_machine_phases(tmp_path: Path) -> None:
    llm = ToolThenRecordLLMClient()
    agent = build_agent(tmp_path, llm, require_plan_approval=True)
    agent.enqueue_message("steer now", delivery="steering")

    events = agent.prompt("start here")
    token = agent.state.pending_plan_token
    assert token is not None
    events.extend(agent.approve_pending_plan(token))

    phases = [event.details.get("phase") for event in events if event.type == "turn_state"]

    assert "planning" in phases
    assert "awaiting_approval" in phases
    assert "executing" in phases
    assert "draining_queue" in phases
    assert phases[-1] == "idle"


def test_runtime_monitor_snapshot_matches_turn_state_event(tmp_path: Path) -> None:
    monitor = RuntimeMonitor()
    agent = build_agent(tmp_path, NoopLLMClient(), require_plan_approval=False)

    events = agent.prompt("hello")
    turn_state_event = next(event for event in events if event.type == "turn_state")
    snapshot_from_event = monitor.snapshot_from_event(turn_state_event)
    snapshot_from_state = monitor.snapshot_from_state(agent.state)

    assert snapshot_from_event is not None
    assert snapshot_from_event.turn_id >= 1
    assert snapshot_from_state.phase == "idle"
    assert snapshot_from_event.queue_count >= 0


def test_agent_session_persists_queryable_timeline_entries(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    timeline = TimelineStore(tmp_path / "timelines")
    record = store.create("system", ModelConfig())
    agent = AgentSession(
        llm_client=FakeLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
        require_plan_approval=False,
        timeline_store=timeline,
    )

    agent.prompt("create a file")
    entries = timeline.list_session(record.id, limit=50)
    event_types = [entry.event_type for entry in entries]

    assert "turn_state" in event_types
    assert "planner_start" in event_types
    assert "tool_start" in event_types
    assert "tool_end" in event_types
    assert any(entry.runtime is not None for entry in entries if entry.event_type == "turn_state")


def test_agent_session_timeline_entries_share_runtime_snapshot_contract(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    timeline = TimelineStore(tmp_path / "timelines")
    record = store.create("system", ModelConfig())
    agent = AgentSession(
        llm_client=ToolThenRecordLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
        require_plan_approval=True,
        timeline_store=timeline,
    )
    agent.enqueue_message("steer now", delivery="steering")

    agent.prompt("start here")
    token = agent.state.pending_plan_token
    assert token is not None
    agent.approve_pending_plan(token)

    entries = timeline.list_session(record.id, limit=100)
    persisted = [entry for entry in entries if entry.event_type != "message_delta"]

    assert persisted
    assert all(entry.runtime is not None for entry in persisted)
    assert all(entry.phase == entry.runtime.phase for entry in persisted if entry.runtime is not None)
    assert all(entry.turn_id == entry.runtime.turn_id for entry in persisted if entry.runtime is not None)

    zero_turn_events = {entry.event_type for entry in persisted if entry.turn_id == 0}
    assert zero_turn_events == {"agent_start"}

    expected_event_types = {"agent_start", "turn_start", "planner_start", "planner_step", "planner_end", "tool_start", "tool_end", "turn_end", "queue_update", "compaction", "agent_end", "error", "turn_state"}
    formal_phases = {"idle", "planning", "awaiting_approval", "executing", "draining_queue"}
    checked = [entry for entry in persisted if entry.event_type in expected_event_types]
    assert checked
    assert all(entry.phase in formal_phases for entry in checked)


def test_agent_session_restore_uses_active_head_branch_messages(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    record.messages = [
        ChatMessage(role="user", content=[TextPart(text="u1")], timestamp=1.0),
        ChatMessage(role="assistant", content=[TextPart(text="a1")], timestamp=2.0),
        ChatMessage(role="user", content=[TextPart(text="u2")], timestamp=3.0),
        ChatMessage(role="assistant", content=[TextPart(text="a2")], timestamp=4.0),
    ]
    store.save(record)
    saved = store.load(record.id)
    historical_head = saved.turn_nodes[0].id
    switched = store.set_active_head(saved.id, historical_head)

    agent = AgentSession(
        llm_client=NoopLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=switched.id,
        system_prompt=switched.system_prompt,
        confirm_callback=lambda _name, _args: True,
        require_plan_approval=False,
    )
    agent.restore_session_record(switched)

    assert [message.role for message in agent.state.messages] == ["user", "assistant"]
    assert agent.state.turn.turn_id == 1


def test_agent_session_persists_compaction_as_session_tree_entry(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    agent = AgentSession(
        llm_client=NoopLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
        compact_after_messages=4,
        require_plan_approval=False,
    )
    agent.restore_session_record(record)
    agent.state.messages = [
        ChatMessage(role="user", content=[TextPart(text=f"user {index}")], timestamp=float(index))
        for index in range(6)
    ]

    agent.prompt("trigger compaction")
    saved = store.load(record.id)
    compaction_nodes = [node for node in saved.turn_nodes if node.entry_type == "compaction"]

    assert compaction_nodes
    assert compaction_nodes[-1].summary == saved.compaction.summary
    assert compaction_nodes[-1].summarized_message_count == saved.compaction.summarized_message_count


def test_agent_session_manual_compact_persists_compaction_entry(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    agent = AgentSession(
        llm_client=NoopLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
        compact_after_messages=4,
        require_plan_approval=False,
    )
    agent.restore_session_record(record)
    agent.state.messages = [
        ChatMessage(role="user", content=[TextPart(text=f"user {index}")], timestamp=float(index))
        for index in range(6)
    ]

    events = agent.compact_now()
    saved = store.load(record.id)

    assert any(event.type == "compaction" for event in events)
    assert any(node.entry_type == "compaction" for node in saved.turn_nodes)


def test_agent_session_manual_compact_noops_when_nothing_new_to_compact(tmp_path: Path) -> None:
    agent = build_agent(tmp_path, NoopLLMClient(), compact_after_messages=4, require_plan_approval=False)

    events = agent.compact_now()

    assert events == []


def test_agent_session_does_not_execute_pending_plan_without_explicit_approval(tmp_path: Path) -> None:
    agent = build_agent(tmp_path, FakeLLMClient(), require_plan_approval=True)
    agent.prompt("create a file")

    token = agent.state.pending_plan_token
    assert token is not None

    events = agent.prompt("approve")

    assert any(event.type == "error" and "planner approval" in (event.message or "") for event in events)
    assert agent.state.pending_plan_token == token
    assert len(agent.state.pending_tool_calls) == 1
    assert (tmp_path / "a.txt").exists() is False
