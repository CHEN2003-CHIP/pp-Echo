from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.config import ConfigManager
from pp_agent.learning import LearningRuntime
from pp_agent.learning.models import LearningCandidate, LearningSettings
from pp_agent.learning.store import LearningStore
from pp_agent.llm.models import ModelConfig
from pp_agent.llm.provider.base import LLMClientError
from pp_agent.runtime.lifecycle import LEARNING_CANDIDATES_CREATED, LEARNING_EXTRACTION_FAILED
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.storage.sessions import SessionStore
from pp_agent.tools.registry import ToolRegistry


class OkLLMClient:
    def __init__(self, model: str | None = None) -> None:
        self.model = ModelConfig(model=model or "test-model")

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        yield {"text": "remembered", "tool_calls": [], "finish_reason": "stop", "raw": {}}


class FakeLearningRuntime:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, list[ChatMessage]]] = []

    def on_turn_persisted(self, *, session_id: str, turn_id: str, new_messages: list[ChatMessage]):
        self.calls.append((turn_id, new_messages))
        if self.fail:
            raise ValueError("boom")
        return [LearningCandidate(id="learn-1", title="Run tests", content="Run focused tests.")]


class QuotaExhaustedExtractor:
    def __init__(self) -> None:
        self.calls = 0

    def extract(self, *, session_id: str, turn_id: str, messages: list[ChatMessage]):
        self.calls += 1
        raise LLMClientError(
            'LLM request failed with status 403: {"error":{"message":"The free tier of the model has been exhausted. '
            'If you wish to continue access the model on a paid basis, please disable the "use free tier only" mode '
            'in the management console.","type":"AllocationQuota.FreeTierOnly","param":null,"code":"AllocationQuota.FreeTierOnly"}}'
        )


class InvalidJsonExtractor:
    def __init__(self) -> None:
        self.calls = 0

    def extract(self, *, session_id: str, turn_id: str, messages: list[ChatMessage]):
        self.calls += 1
        raise ValueError("Learning extractor expected a JSON array")


class ExtractorWithClient:
    def __init__(self, llm_client) -> None:
        self.llm_client = llm_client

    def extract(self, *, session_id: str, turn_id: str, messages: list[ChatMessage]):
        return []


class RefreshRecordingLearningRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object]] = []

    def refresh_llm_client(self, llm_client, *, settings=None) -> None:
        self.calls.append((llm_client, settings))

    def on_turn_persisted(self, *, session_id: str, turn_id: str, new_messages: list[ChatMessage]):
        return []


def _runtime(tmp_path: Path, learning_runtime) -> AgentRuntime:
    store = SessionStore(tmp_path / ".pp-agent" / "sessions")
    record = store.create("system", ModelConfig())
    return AgentRuntime(
        llm_client=OkLLMClient(),
        tool_registry=ToolRegistry(tmp_path, current_session_id=record.id),
        session_store=store,
        session_id=record.id,
        system_prompt="system",
        require_plan_approval=False,
        learning_runtime=learning_runtime,
    )


def test_runtime_emits_learning_candidates_after_turn_persist(tmp_path: Path) -> None:
    learning = FakeLearningRuntime()
    runtime = _runtime(tmp_path, learning)

    events = runtime.prompt("remember this workflow")

    assert learning.calls
    assert any(event.type == LEARNING_CANDIDATES_CREATED for event in events)


def test_runtime_learning_failure_does_not_abort_turn(tmp_path: Path) -> None:
    learning = FakeLearningRuntime(fail=True)
    runtime = _runtime(tmp_path, learning)

    events = runtime.prompt("remember this workflow")

    assert any(event.type == LEARNING_EXTRACTION_FAILED for event in events)
    assert runtime.state.messages[-1].role == "assistant"


def test_runtime_learning_quota_exhaustion_is_suppressed(tmp_path: Path) -> None:
    extractor = QuotaExhaustedExtractor()
    learning = LearningRuntime(
        workspace=tmp_path,
        llm_client=None,
        settings=LearningSettings(),
        store=LearningStore(tmp_path / ".pp-agent" / "learning"),
        extractor=extractor,
    )
    runtime = _runtime(tmp_path, learning)

    first_events = runtime.prompt("remember this workflow")
    second_events = runtime.continue_()

    assert extractor.calls == 1
    assert learning._extraction_disabled is True
    assert not any(event.type == LEARNING_EXTRACTION_FAILED for event in first_events)
    assert not any(event.type == LEARNING_EXTRACTION_FAILED for event in second_events)
    assert runtime.state.messages[-1].role == "assistant"


def test_runtime_learning_parse_failure_is_suppressed(tmp_path: Path) -> None:
    extractor = InvalidJsonExtractor()
    learning = LearningRuntime(
        workspace=tmp_path,
        llm_client=None,
        settings=LearningSettings(),
        store=LearningStore(tmp_path / ".pp-agent" / "learning"),
        extractor=extractor,
    )
    runtime = _runtime(tmp_path, learning)

    events = runtime.prompt("remember this workflow")

    assert extractor.calls == 1
    assert not any(event.type == LEARNING_EXTRACTION_FAILED for event in events)
    assert runtime.state.messages[-1].role == "assistant"


def test_learning_runtime_refreshes_llm_client_and_reenables_after_quota(tmp_path: Path) -> None:
    old_client = object()
    new_client = object()
    extractor = ExtractorWithClient(old_client)
    learning = LearningRuntime(
        workspace=tmp_path,
        llm_client=old_client,
        settings=LearningSettings(),
        store=LearningStore(tmp_path / ".pp-agent" / "learning"),
        extractor=extractor,
    )
    learning._extraction_disabled = True
    learning._extraction_disabled_reason = "AllocationQuota.FreeTierOnly"

    learning.refresh_llm_client(new_client, settings=LearningSettings(auto_extract=False))

    assert extractor.llm_client is new_client
    assert learning.settings.auto_extract is False
    assert learning._extraction_disabled is False
    assert learning._extraction_disabled_reason is None


def test_runtime_config_refresh_syncs_learning_llm_client(tmp_path: Path) -> None:
    manager = ConfigManager(tmp_path)
    store = SessionStore(tmp_path / ".pp-agent" / "sessions")
    record = store.create("system", ModelConfig(model="old-model"))
    learning = RefreshRecordingLearningRuntime()
    runtime = AgentRuntime(
        llm_client=OkLLMClient("old-model"),
        tool_registry=ToolRegistry(tmp_path, current_session_id=record.id),
        session_store=store,
        session_id=record.id,
        system_prompt="system",
        require_plan_approval=False,
        learning_runtime=learning,
        config_manager=manager,
        config_snapshot=manager.get_effective_snapshot(session_id=record.id),
    )
    manager.set_session_model(record.id, "new-model")

    list(runtime._refresh_config_for_turn())

    assert runtime.llm_client.model.model == "new-model"
    assert learning.calls
    assert learning.calls[-1][0] is runtime.llm_client
