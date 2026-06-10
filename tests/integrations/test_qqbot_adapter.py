from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

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
    def __init__(self, reply: str = "answer", *, fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.prompts: list[str] = []
        self._worker = SimpleNamespace(join=lambda timeout=None: None)

    def prompt(self, text: str) -> dict:
        self.prompts.append(text)
        if self.fail:
            raise RuntimeError("boom")
        return {"queued": False}

    def snapshot(self) -> dict:
        return {"messages": [{"role": "assistant", "content": [{"type": "text", "text": self.reply}]}]}


class FakeSessionManager:
    def __init__(self, handle: FakeHandle) -> None:
        self.handle = handle

    def get_handle(self, session_id: str) -> FakeHandle:
        return self.handle


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


def _c2c(event_id: str = "event-1") -> dict:
    return {"op": 0, "id": event_id, "t": "C2C_MSG_RECEIVE", "d": {"id": "msg-1", "openid": "user-1", "content": "hello"}}


def _group(content: str = "/pp hello") -> dict:
    return {"op": 0, "id": "event-g", "t": "GROUP_MSG_RECEIVE", "d": {"id": "msg-g", "group_openid": "group-1", "content": content}}


def test_adapter_handles_c2c_message(tmp_path: Path) -> None:
    adapter, client, handle = _adapter(tmp_path)

    asyncio.run(adapter.handle_payload(_c2c()))

    assert handle.prompts
    assert client.c2c[0]["openid"] == "user-1"
    assert client.c2c[0]["content"] == "answer"


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


def test_adapter_ignores_unsupported_and_malformed_events(tmp_path: Path) -> None:
    adapter, client, handle = _adapter(tmp_path)

    asyncio.run(adapter.handle_payload({"op": 0, "id": "e", "t": "OTHER", "d": {}}))
    asyncio.run(adapter.handle_payload({"op": 0, "id": "e", "t": "C2C_MSG_RECEIVE", "d": {}}))

    assert handle.prompts == []
    assert client.c2c == []


def test_extract_reply_text_and_truncate() -> None:
    assert extract_reply_text({"events": [{"type": "message_delta", "delta": "ok"}]}) == "ok"
    assert "已截断" in truncate_reply("x" * 200, 60)
