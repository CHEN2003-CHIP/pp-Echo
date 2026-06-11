from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

from pp_agent.bots.manager import BotRuntimeManager
from pp_agent.integrations.qqbot.adapter import QQBotAdapter, extract_reply_text, truncate_reply
from pp_agent.integrations.qqbot.config import QQBotConfig
from pp_agent.integrations.qqbot.dedupe import QQEventDedupeStore
from pp_agent.integrations.qqbot.session_store import QQSessionStore


class FakeClient:
    def __init__(self) -> None:
        self.c2c: list[dict] = []
        self.group: list[dict] = []

    async def send_c2c_text(self, openid, content, **kwargs):
        self.c2c.append({"openid": openid, "content": content, **kwargs})
        return {}

    async def send_group_text(self, group_openid, content, **kwargs):
        self.group.append({"group_openid": group_openid, "content": content, **kwargs})
        return {}


class FakeHandle:
    def __init__(self, reply: str = "answer", *, fail: bool = False, delay: float = 0.0) -> None:
        self.reply = reply
        self.fail = fail
        self.delay = delay
        self.prompts: list[str] = []
        self._worker = SimpleNamespace(join=lambda timeout=None: None)

    def prompt(self, text: str) -> dict:
        self.prompts.append(text)
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("boom")
        return {"queued": False}

    def snapshot(self) -> dict:
        return {"messages": [{"role": "assistant", "content": [{"type": "text", "text": self.reply}]}]}


class FakeSessionManager:
    def __init__(self, handle: FakeHandle) -> None:
        self.handle = handle
        self.created = 0

    def get_handle(self, session_id: str) -> FakeHandle:
        return self.handle

    def create_session(self) -> dict:
        self.created += 1
        return {"session_id": f"session-created-{self.created}"}


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
        session_store="sessions.json",
        dedupe_store="dedupe.json",
    )
    values.update(overrides)
    return QQBotConfig(**values)


def _adapter(tmp_path: Path, *, config: QQBotConfig | None = None, handle: FakeHandle | None = None):
    client = FakeClient()
    adapter = QQBotAdapter(
        workspace=tmp_path,
        session_manager=FakeSessionManager(handle or FakeHandle()),
        config=config or _config(),
        client=client,
        session_store=QQSessionStore(tmp_path / "sessions.json"),
        dedupe_store=QQEventDedupeStore(tmp_path / "dedupe.json"),
    )
    return adapter, client, adapter.session_manager.handle


def _managed_adapter(tmp_path: Path, *, config: QQBotConfig | None = None, handle: FakeHandle | None = None):
    adapter, client, fake_handle = _adapter(tmp_path, config=config, handle=handle)
    adapter.bot_manager = BotRuntimeManager(tmp_path)
    return adapter, client, fake_handle


def _c2c(event_id: str = "event-1") -> dict:
    return {"op": 0, "id": event_id, "t": "C2C_MSG_RECEIVE", "d": {"id": "msg-1", "openid": "user-1", "content": "hello"}}


def _c2c_create(event_id: str = "event-c2c-create") -> dict:
    return {"op": 0, "id": event_id, "t": "C2C_MESSAGE_CREATE", "d": {"id": "msg-c2c", "author": {"user_openid": "user-1"}, "content": "hello"}}


def _group(content: str = "/pp hello") -> dict:
    return {"op": 0, "id": "event-g", "t": "GROUP_MSG_RECEIVE", "d": {"id": "msg-g", "group_openid": "group-1", "content": content}}


def test_adapter_handles_c2c_message(tmp_path: Path) -> None:
    adapter, client, handle = _adapter(tmp_path)

    asyncio.run(adapter.handle_payload(_c2c()))

    assert handle.prompts
    assert client.c2c[0]["openid"] == "user-1"
    assert client.c2c[0]["content"] == "answer"


def test_adapter_uses_session_manager_for_new_mapping(tmp_path: Path) -> None:
    adapter, _client, _handle = _adapter(tmp_path)

    asyncio.run(adapter.handle_payload(_c2c()))

    assert adapter.session_manager.created == 1


def test_adapter_handles_c2c_message_create_alias(tmp_path: Path) -> None:
    adapter, client, handle = _adapter(tmp_path)

    asyncio.run(adapter.handle_payload(_c2c_create()))

    assert handle.prompts
    assert client.c2c[0]["openid"] == "user-1"


def test_adapter_denies_c2c_when_not_allowlisted(tmp_path: Path) -> None:
    adapter, client, handle = _adapter(tmp_path, config=_config(allow_all_c2c=False, allowed_users=("other",)))

    asyncio.run(adapter.handle_payload(_c2c()))

    assert handle.prompts == []
    assert client.c2c == []


def test_adapter_ignores_group_without_trigger(tmp_path: Path) -> None:
    adapter, client, handle = _adapter(tmp_path)

    asyncio.run(adapter.handle_payload(_group("hello")))

    assert handle.prompts == []
    assert client.group == []


def test_adapter_handles_group_with_trigger_and_dedupes(tmp_path: Path) -> None:
    adapter, client, handle = _adapter(tmp_path)

    asyncio.run(adapter.handle_payload(_group("/pp hello")))
    asyncio.run(adapter.handle_payload(_group("/pp hello")))

    assert len(handle.prompts) == 1
    assert client.group[0]["group_openid"] == "group-1"


def test_adapter_sends_short_error_on_agent_failure(tmp_path: Path) -> None:
    adapter, client, _handle = _adapter(tmp_path, handle=FakeHandle(fail=True))

    asyncio.run(adapter.handle_payload(_c2c()))

    assert "RuntimeError" in client.c2c[0]["content"]
    assert "TraceInspect" in client.c2c[0]["content"]


def test_adapter_times_out_run_and_records_event(tmp_path: Path) -> None:
    adapter, client, _handle = _managed_adapter(tmp_path, config=_config(run_timeout_seconds=1), handle=FakeHandle(delay=2.0))

    asyncio.run(adapter.handle_payload(_c2c()))

    events = adapter.bot_manager.event_store.list_events("qq", "qq-main")
    runs = adapter.bot_manager.event_store.list_runs("qq", "qq-main")
    traces = adapter.bot_manager.event_store.list_traces("qq", "qq-main")
    assert client.c2c[0]["content"].startswith("这次处理超时了")
    assert any(event["type"] == "run_timed_out" for event in events)
    assert runs[0]["status"] == "timed_out"
    assert traces[0]["status"] == "timed_out"


def test_adapter_rejects_when_conversation_queue_is_full(tmp_path: Path) -> None:
    adapter, client, _handle = _managed_adapter(tmp_path, config=_config(max_queue_per_conversation=1))
    key = "qq:c2c:user-1"
    lock = adapter._conversation_locks[key]
    adapter._conversation_queued[key] = 1

    async def run_locked() -> None:
        async with lock:
            await adapter.handle_payload(_c2c("event-queue-full"))

    asyncio.run(run_locked())

    events = adapter.bot_manager.event_store.list_events("qq", "qq-main")
    assert client.c2c[0]["content"] == "当前会话正在处理上一条消息，请稍后再试。"
    assert events[-1]["type"] == "message_rejected"
    adapter._conversation_queued.pop(key, None)


def test_adapter_ignores_unsupported_and_malformed_events(tmp_path: Path) -> None:
    adapter, client, handle = _adapter(tmp_path)

    asyncio.run(adapter.handle_payload({"op": 0, "id": "e", "t": "OTHER", "d": {}}))
    asyncio.run(adapter.handle_payload({"op": 0, "id": "e", "t": "C2C_MSG_RECEIVE", "d": {}}))

    assert handle.prompts == []
    assert client.c2c == []


def test_extract_reply_text_and_truncate() -> None:
    assert extract_reply_text({"events": [{"type": "message_delta", "delta": "ok"}]}) == "ok"
    assert "已截断" in truncate_reply("x" * 200, 60)
