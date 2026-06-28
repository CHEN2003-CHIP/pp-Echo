from __future__ import annotations

import asyncio
from pathlib import Path

from pp_agent.observability.store import TraceStore

from tests.contracts.helpers.fake_channel_adapter import FakeChannelAdapter, RecordingRuntime
from tests.integrations.test_qqbot_runtime_boundary import BotLLMClient, _adapter, _c2c


def test_channel_adapter_is_not_runtime_and_has_no_execution_surface() -> None:
    adapter = FakeChannelAdapter(RecordingRuntime())

    assert not hasattr(adapter, "stream_chat")
    assert not hasattr(adapter, "execute")
    assert not hasattr(adapter, "evaluate_call")
    assert not hasattr(adapter, "build_context")


def test_channel_adapter_calls_agent_runtime_as_single_execution_boundary() -> None:
    runtime = RecordingRuntime()
    adapter = FakeChannelAdapter(runtime)

    result = adapter.handle(
        {
            "text": "hello",
            "profile_id": "default",
            "session_id": "s1",
            "channel_id": "c1",
            "user_id": "u1",
            "source_ref": "fake:m1",
        }
    )

    assert result.text == "runtime-ok"
    assert len(runtime.calls) == 1
    assert runtime.calls[0].text == "hello"
    assert adapter.deliveries[0]["parent_id"] == result.runtime_trace_run_id


def test_qq_channel_delivers_trace_linked_to_runtime_run(tmp_path: Path) -> None:
    llm = BotLLMClient()
    adapter, client, session_manager, manager = _adapter(tmp_path, llm)

    asyncio.run(adapter.handle_payload(_c2c()))

    assert client.c2c[0]["content"] == "bot-runtime-ok"
    assert llm.calls == 1
    bot_trace = manager.event_store.list_traces("qq", "qq-main")[0]
    runtime_run = TraceStore(tmp_path / ".pp-agent" / "traces").find_latest_run(session_id=session_manager.list_active()[0]["session_id"])
    assert runtime_run is not None
    assert bot_trace["runtime_trace_run_id"] == runtime_run.run_id
    assert bot_trace["parent_id"] == runtime_run.run_id
