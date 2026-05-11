from collections.abc import Iterator
from pathlib import Path

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.learning.models import LearningCandidate
from pp_agent.llm.models import ModelConfig
from pp_agent.runtime.lifecycle import LEARNING_CANDIDATES_CREATED, LEARNING_EXTRACTION_FAILED
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.storage.sessions import SessionStore
from pp_agent.tools.registry import ToolRegistry


class OkLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()

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
