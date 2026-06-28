from __future__ import annotations

import asyncio

import pytest

from tests.contracts.helpers.fake_channel_adapter import FakeChannelAdapter, RecordingRuntime
from tests.integrations.test_qqbot_runtime_boundary import BotLLMClient, _adapter, _c2c


def _message() -> dict[str, str]:
    return {
        "text": "contract turn",
        "profile_id": "default",
        "session_id": "session-a",
        "channel_id": "channel-a",
        "user_id": "user-a",
        "source_ref": "fake:event-a",
    }


def test_external_message_normalizes_to_runtime_input_and_preserves_identity() -> None:
    adapter = FakeChannelAdapter(RecordingRuntime())

    runtime_input = adapter.normalize(_message())

    assert runtime_input.text == "contract turn"
    assert runtime_input.profile_id == "default"
    assert runtime_input.session_id == "session-a"
    assert runtime_input.channel_id == "channel-a"
    assert runtime_input.user_id == "user-a"
    assert runtime_input.source_ref == "fake:event-a"


def test_adapter_calls_runtime_once_and_cannot_emit_without_result() -> None:
    runtime = RecordingRuntime()
    adapter = FakeChannelAdapter(runtime)

    adapter.handle(_message())

    assert len(runtime.calls) == 1
    with pytest.raises(RuntimeError):
        adapter.deliver(None, runtime.calls[0])


def test_adapter_cannot_execute_tools_directly() -> None:
    adapter = FakeChannelAdapter(RecordingRuntime())

    assert not hasattr(adapter, "tool_registry")
    assert not hasattr(adapter, "execute_tool")
    assert not hasattr(adapter, "execute")


def test_adapter_delivery_trace_records_runtime_parent_linkage() -> None:
    adapter = FakeChannelAdapter(RecordingRuntime())

    result = adapter.handle(_message())
    delivery = adapter.deliveries[0]

    assert delivery["runtime_trace_run_id"] == result.runtime_trace_run_id
    assert delivery["parent_id"] == result.runtime_trace_run_id


def test_qq_adapter_preserves_channel_user_session_and_uses_runtime_once(tmp_path) -> None:
    llm = BotLLMClient()
    adapter, client, session_manager, manager = _adapter(tmp_path, llm)

    asyncio.run(adapter.handle_payload(_c2c(event_id="event-contract", message_id="msg-contract", user="user-contract")))

    assert client.c2c
    assert llm.calls == 1
    run = manager.event_store.list_runs("qq", "qq-main")[0]
    trace = manager.event_store.list_traces("qq", "qq-main")[0]
    assert run["session_id"] == session_manager.list_active()[0]["session_id"]
    assert trace["session_id"] == run["session_id"]
    assert trace["channel_id"] == "user-contract"
    assert trace["platform_user_id"] == "user-contract"
    assert trace["platform_event_id"] == "event-contract"
