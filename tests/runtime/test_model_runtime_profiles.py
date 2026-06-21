from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from pp_agent.llm.model_profile import ModelCapabilityProfile
from pp_agent.llm.models import ModelConfig
from pp_agent.llm.registry import infer_model_profile
from pp_agent.observability.recorder import TraceRecorder
from pp_agent.observability.store import TraceStore
from pp_agent.runtime.resolver import resolve_model_profile
from pp_agent.runtime.registry import RuntimeRegistry
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.storage.sessions import SessionStore
from pp_agent.tools.registry import ToolRegistry


class ProfileTraceLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig(provider="deepseek", model="deepseek-chat")

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        yield {"text": "ok", "tool_calls": [], "finish_reason": "stop", "raw": {}}


def test_default_runtime_profile() -> None:
    profile = RuntimeRegistry().get_default()

    assert profile.id == "pp_echo_native"
    assert profile.supports.approval is True
    assert profile.supports.checkpoint is True
    assert profile.supports.tool_calling is True


def test_model_profile_serialization() -> None:
    profile = ModelCapabilityProfile(provider_id="deepseek", model_id="deepseek-chat")

    payload = profile.model_dump_json()

    assert "deepseek-chat" in payload
    assert "api_key" not in payload.lower()
    assert "secret" not in payload.lower()
    with pytest.raises(ValueError):
        ModelCapabilityProfile(metadata={"api_key": "do-not-store"})


def test_resolve_model_profile_from_current_model_config() -> None:
    profile = resolve_model_profile(ProfileTraceLLMClient())

    assert profile.provider_id == "deepseek"
    assert profile.model_id == "deepseek-chat"
    assert profile.capabilities.tool_calling is True


def test_provider_registry_infer_unknown_model() -> None:
    profile = infer_model_profile("unknown-provider", "unknown-model")

    assert profile.provider_id == "unknown-provider"
    assert profile.model_id == "unknown-model"
    assert profile.capabilities.tool_calling is False
    assert profile.metadata["source"] == "inferred"


def test_runtime_registry_get_default() -> None:
    registry = RuntimeRegistry()

    assert registry.get_default().id == "pp_echo_native"
    assert registry.get("pp_echo_native").kind == "native"


def test_trace_contains_model_runtime_metadata(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig(provider="deepseek", model="deepseek-chat"))
    trace_store = TraceStore(tmp_path / "traces")
    recorder = TraceRecorder(trace_store, workspace=tmp_path)
    agent = AgentRuntime(
        llm_client=ProfileTraceLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        require_plan_approval=False,
        observability=recorder,
    )
    agent.restore_session_record(record)

    events = agent.prompt("hello")
    run_id = trace_store.list_runs()[0].run_id
    detail = trace_store.read_run(run_id)
    selected = next(event for event in detail.events if event.name == "model_runtime_selected")

    assert any(event.type == "model_runtime_selected" for event in events)
    assert selected.payload["details"]["provider_id"] == "deepseek"
    assert selected.payload["details"]["model_id"] == "deepseek-chat"
    assert selected.payload["details"]["runtime_id"] == "pp_echo_native"
