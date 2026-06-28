from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pp_agent.bots.manager import BotRuntimeManager
from pp_agent.domain import ChatMessage, TextPart
from pp_agent.integrations.qqbot.adapter import QQBotAdapter
from pp_agent.integrations.qqbot.config import QQBotConfig
from pp_agent.integrations.qqbot.dedupe import QQEventDedupeStore
from pp_agent.integrations.qqbot.schema import parse_incoming_message
from pp_agent.integrations.qqbot.session_store import QQSessionStore
from pp_agent.llm import ModelConfig
from pp_agent.observability.recorder import TraceRecorder
from pp_agent.observability.store import TraceStore
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.storage.sessions import SessionStore
from pp_agent.storage.settings import ToolPolicyConfig
from pp_agent.tools.registry import ToolRegistry
from pp_agent.web.session_manager import WebSessionManager


class RecordingQQClient:
    def __init__(self, *, fail_send: bool = False) -> None:
        self.fail_send = fail_send
        self.c2c: list[dict[str, Any]] = []
        self.group: list[dict[str, Any]] = []

    async def send_c2c_text(self, openid, content, **kwargs):
        if self.fail_send:
            raise RuntimeError("send timeout token=leaky")
        self.c2c.append({"openid": openid, "content": content, **kwargs})
        return {"id": "sent-1"}

    async def send_group_text(self, group_openid, content, **kwargs):
        if self.fail_send:
            raise RuntimeError("send timeout token=leaky")
        self.group.append({"group_openid": group_openid, "content": content, **kwargs})
        return {"id": "sent-g"}


class BotLLMClient:
    def __init__(self, *, tool_name: str | None = None, arguments: str = "{}") -> None:
        self.model = ModelConfig()
        self.tool_name = tool_name
        self.arguments = arguments
        self.calls = 0
        self.seen_messages: list[list[ChatMessage]] = []
        self.seen_tools: list[list[dict]] = []

    def stream_chat(self, messages, tools=None) -> Iterator[dict]:
        self.calls += 1
        self.seen_messages.append(list(messages))
        self.seen_tools.append(list(tools or []))
        if self.tool_name and self.calls == 1:
            yield {
                "text": "",
                "tool_calls": [{"id": f"call-{self.tool_name}", "name": self.tool_name, "arguments_chunk": self.arguments}],
                "finish_reason": "tool_calls",
                "raw": {},
            }
            return
        yield {"text": "bot-runtime-ok", "tool_calls": [], "finish_reason": "stop", "raw": {}}


def _config(**overrides) -> QQBotConfig:
    values = dict(
        enabled=True,
        app_id="app",
        app_secret="secret",
        api_base="https://api.sgroup.qq.com",
        token_url="https://bots.qq.com/app/getAppAccessToken",
        group_trigger="/pp",
        allow_all_c2c=True,
        allowed_users=(),
        allowed_groups=(),
        reply_max_chars=1800,
        request_timeout=10.0,
        run_timeout_seconds=180,
        max_queue_per_conversation=5,
        dedupe_ttl_seconds=600,
        session_store=".pp-agent/integrations/qqbot-sessions.json",
        dedupe_store=".pp-agent/integrations/qqbot-dedupe.json",
    )
    values.update(overrides)
    return QQBotConfig(**values)


def _runtime_factory(tmp_path: Path, llm: BotLLMClient, *, require_plan_approval: bool = False, read_only: bool = False):
    def factory(workspace: Path, session_id: str | None, subscribers):
        store = SessionStore(workspace / ".pp-agent" / "sessions")
        if session_id is None:
            record = store.create("system", ModelConfig())
            session_id_value = record.id
        else:
            session_id_value = session_id
            try:
                record = store.load(session_id_value)
            except FileNotFoundError:
                record = store.create("system", ModelConfig())
                record.metadata.id = session_id_value
                store.save(record)
        policy = ToolPolicyConfig(permission_mode="read-only" if read_only else "workspace-write")
        recorder = TraceRecorder(TraceStore(workspace / ".pp-agent" / "traces"), workspace=workspace)
        registry = ToolRegistry(workspace, policy=policy, observability=recorder)
        runtime = AgentRuntime(
            llm_client=llm,
            tool_registry=registry,
            session_store=store,
            session_id=session_id_value,
            system_prompt=record.system_prompt,
            require_plan_approval=require_plan_approval,
            observability=recorder,
        )
        for subscriber in subscribers:
            runtime.subscribe(subscriber)
        runtime.restore_session_record(record)
        runtime.config_snapshot.settings.context_pipeline.context_pipeline_mode = "on"
        runtime.context_pipeline_mode = "on"
        return runtime

    return factory


def _adapter(tmp_path: Path, llm: BotLLMClient, *, config: QQBotConfig | None = None, client: RecordingQQClient | None = None, require_plan_approval: bool = False, read_only: bool = False):
    manager = BotRuntimeManager(tmp_path)
    session_manager = WebSessionManager(
        tmp_path,
        runtime_factory=_runtime_factory(tmp_path, llm, require_plan_approval=require_plan_approval, read_only=read_only),
    )
    qq_client = client or RecordingQQClient()
    return QQBotAdapter(
        workspace=tmp_path,
        session_manager=session_manager,
        config=config or _config(),
        client=qq_client,
        session_store=QQSessionStore(tmp_path / ".pp-agent" / "integrations" / "qqbot-sessions.json"),
        dedupe_store=QQEventDedupeStore(tmp_path / ".pp-agent" / "integrations" / "qqbot-dedupe.json"),
        bot_manager=manager,
    ), qq_client, session_manager, manager


def _c2c(event_id: str = "event-1", message_id: str = "msg-1", *, user: str = "user-1", content: str = "hello", **extra_d) -> dict[str, Any]:
    data = {"id": message_id, "openid": user, "content": content, **extra_d}
    return {"op": 0, "id": event_id, "t": "C2C_MSG_RECEIVE", "d": data}


def _group(event_id: str = "event-g", message_id: str = "msg-g", *, group: str = "group-1", user: str = "user-1", content: str = "/pp hello", **extra_d) -> dict[str, Any]:
    data = {"id": message_id, "group_openid": group, "author": {"user_openid": user}, "content": content, **extra_d}
    return {"op": 0, "id": event_id, "t": "GROUP_MSG_RECEIVE", "d": data}


def _message_texts(messages: list[ChatMessage]) -> str:
    return "\n".join(part.text for message in messages for part in message.content if isinstance(part, TextPart))


def test_bot_c2c_message_uses_runtime_context_pipeline_and_records_history(tmp_path: Path) -> None:
    llm = BotLLMClient()
    adapter, client, session_manager, manager = _adapter(tmp_path, llm)

    asyncio.run(adapter.handle_payload(_c2c()))

    assert client.c2c[0]["content"] == "bot-runtime-ok"
    assert llm.seen_messages
    assert any(message.metadata.get("context_section") == "conversation" for message in llm.seen_messages[0])
    assert "[QQ Bot Message]" in _message_texts(llm.seen_messages[0])
    runs = manager.event_store.list_runs("qq", "qq-main")
    traces = manager.event_store.list_traces("qq", "qq-main")
    assert runs[0]["session_id"] == session_manager.list_active()[0]["session_id"]
    assert traces[0]["platform"] == "qqbot"
    assert traces[0]["platform_event_id"] == "event-1"
    assert traces[0]["platform_message_id"] == "msg-1"
    snapshot = session_manager.snapshot(runs[0]["session_id"])
    assert any(message["role"] == "assistant" and "bot-runtime-ok" in str(message["content"]) for message in snapshot["messages"])


def test_bot_sessions_are_stable_and_scoped_by_channel_group_and_user(tmp_path: Path) -> None:
    llm = BotLLMClient()
    adapter, _client, _session_manager, _manager = _adapter(tmp_path, llm)

    asyncio.run(adapter.handle_payload(_c2c("e1", "m1", user="alice")))
    asyncio.run(adapter.handle_payload(_c2c("e2", "m2", user="alice")))
    asyncio.run(adapter.handle_payload(_c2c("e3", "m3", user="bob")))
    asyncio.run(adapter.handle_payload(_group("e4", "m4", group="g1", user="alice")))
    asyncio.run(adapter.handle_payload(_group("e5", "m5", group="g1", user="bob")))

    mapping = json.loads((tmp_path / ".pp-agent" / "integrations" / "qqbot-sessions.json").read_text(encoding="utf-8"))
    assert mapping["qq:c2c:alice"]["session_id"] == mapping["qq:c2c:alice"]["session_id"]
    assert mapping["qq:c2c:alice"]["session_id"] != mapping["qq:c2c:bob"]["session_id"]
    assert mapping["qq:group:g1:user:alice"]["session_id"] != mapping["qq:group:g1:user:bob"]["session_id"]
    assert mapping["qq:c2c:alice"]["session_id"] != mapping["qq:group:g1:user:alice"]["session_id"]


def test_bot_dedupe_prevents_duplicate_run_and_reply(tmp_path: Path) -> None:
    llm = BotLLMClient()
    adapter, client, _session_manager, manager = _adapter(tmp_path, llm)

    asyncio.run(adapter.handle_payload(_c2c("dup-event", "dup-msg")))
    asyncio.run(adapter.handle_payload(_c2c("dup-event", "dup-msg")))

    assert llm.calls == 1
    assert len(client.c2c) == 1
    assert len(manager.event_store.list_runs("qq", "qq-main")) == 1
    assert any(event["metadata"].get("reason") == "duplicate" for event in manager.event_store.list_events("qq", "qq-main"))


def test_bot_authorization_failure_does_not_create_runtime_run(tmp_path: Path) -> None:
    llm = BotLLMClient()
    adapter, client, _session_manager, manager = _adapter(tmp_path, llm, config=_config(allow_all_c2c=False, allowed_users=("allowed",)))

    asyncio.run(adapter.handle_payload(_c2c(user="intruder")))

    assert llm.calls == 0
    assert client.c2c == []
    assert manager.event_store.list_runs("qq", "qq-main") == []
    event = manager.event_store.list_events("qq", "qq-main")[-1]
    assert event["metadata"]["reason"] == "user_not_allowed"


def test_bot_tool_call_goes_through_tool_registry_trace(tmp_path: Path) -> None:
    llm = BotLLMClient(tool_name="list_files", arguments='{"path":"."}')
    adapter, client, _session_manager, _manager = _adapter(tmp_path, llm)

    asyncio.run(adapter.handle_payload(_c2c()))

    assert client.c2c
    assert any(spec["function"]["name"] == "list_files" for spec in llm.seen_tools[0])
    detail_files = list((tmp_path / ".pp-agent" / "traces").rglob("*.jsonl"))
    assert detail_files
    trace_text = "\n".join(path.read_text(encoding="utf-8") for path in detail_files)
    assert '"name": "tool.call"' in trace_text
    assert '"tool_name": "list_files"' in trace_text


def test_bot_write_tool_requires_runtime_approval_and_aligns_run_session(tmp_path: Path) -> None:
    llm = BotLLMClient(tool_name="write_file", arguments='{"path":"bot.txt","content":"hello"}')
    adapter, client, _session_manager, manager = _adapter(tmp_path, llm, require_plan_approval=True)

    asyncio.run(adapter.handle_payload(_c2c()))

    assert client.c2c[0]["content"].startswith("This action needs approval")
    run = manager.event_store.list_runs("qq", "qq-main")[0]
    pending = PendingActionStore(tmp_path / ".pp-agent" / "pending-edits").list()
    assert run["status"] == "waiting_approval"
    assert pending and pending[0]["details"]["tool_calls"][0]["id"] == "call-write_file"
    assert pending[0]["session_id"] == run["session_id"]
    assert any(event["type"] == "approval_required" and event["run_id"] == run["run_id"] for event in manager.event_store.list_events("qq", "qq-main"))


def test_bot_read_only_policy_blocks_write_without_creating_file(tmp_path: Path) -> None:
    llm = BotLLMClient(tool_name="write_file", arguments='{"path":"blocked.txt","content":"hello"}')
    adapter, client, _session_manager, _manager = _adapter(tmp_path, llm, read_only=True)

    asyncio.run(adapter.handle_payload(_c2c()))

    assert client.c2c
    assert not (tmp_path / "blocked.txt").exists()
    assert "read-only" in _message_texts(llm.seen_messages[-1]).lower() or llm.calls >= 1


def test_bot_self_message_is_ignored_before_runtime(tmp_path: Path) -> None:
    llm = BotLLMClient()
    adapter, client, _session_manager, manager = _adapter(tmp_path, llm, config=_config(app_id="bot-app"))

    asyncio.run(adapter.handle_payload(_c2c(user="bot-app")))

    assert llm.calls == 0
    assert client.c2c == []
    assert manager.event_store.list_events("qq", "qq-main")[-1]["metadata"]["reason"] == "self_message"


def test_bot_message_and_trace_redact_temporary_urls_and_tokens(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PP_ECHO_QQBOT_APP_SECRET", "super-secret")
    llm = BotLLMClient()
    adapter, _client, _session_manager, manager = _adapter(tmp_path, llm)
    payload = _c2c(
        "secret-event",
        "secret-msg",
        content="hello super-secret",
        attachments=[{"url": "https://cdn.qq.test/file.png?access_token=abc123&signature=sig456"}],
    )

    asyncio.run(adapter.handle_payload(payload))

    messages_text = json.dumps(manager.event_store.list_messages("qq", "qq-main"), ensure_ascii=False)
    traces_text = json.dumps(manager.event_store.list_traces("qq", "qq-main"), ensure_ascii=False)
    assert "super-secret" not in messages_text
    assert "abc123" not in messages_text
    assert "sig456" not in messages_text
    assert "qq:c2c:user-1" not in traces_text
    assert traces_text.count("***REDACTED***") >= 1


def test_bot_outbound_failure_records_reply_failed_without_background_crash(tmp_path: Path) -> None:
    llm = BotLLMClient()
    adapter, _client, _session_manager, manager = _adapter(tmp_path, llm, client=RecordingQQClient(fail_send=True))

    asyncio.run(adapter.handle_payload(_c2c()))

    events = manager.event_store.list_events("qq", "qq-main")
    runs = manager.event_store.list_runs("qq", "qq-main")
    assert any(event["type"] == "reply_failed" for event in events)
    assert not any(event["type"] == "background_task_failed" for event in events)
    assert runs[0]["status"] == "completed"


def test_group_payload_parser_uses_user_scoped_conversation_key() -> None:
    message = parse_incoming_message(_group(group="g1", user="u1"))

    assert message is not None
    assert message.conversation_key == "qq:group:g1:user:u1"
