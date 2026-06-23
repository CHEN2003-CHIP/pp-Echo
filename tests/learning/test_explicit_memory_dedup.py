from __future__ import annotations

from pathlib import Path

from pp_agent.domain import ChatMessage
from pp_agent.learning.models import LearningCandidate, LearningSettings
from pp_agent.learning.runtime import LearningRuntime
from pp_agent.learning.store import LearningStore
from pp_agent.llm.models import ModelConfig
from pp_agent.memory.core_service import service_for_workspace
from pp_agent.memory.file_memory_tools import memory_search_executor
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.storage.sessions import SessionStore
from pp_agent.storage.settings import Settings
from pp_agent.tools.registry import ToolRegistry


class OkLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig(model="test-model")

    def stream_chat(self, _messages, tools=None):
        yield {"text": "ok", "tool_calls": [], "finish_reason": "stop", "raw": {}}


class DuplicatePreferenceExtractor:
    def __init__(self) -> None:
        self.calls = 0

    def extract(self, *, session_id: str, turn_id: str, messages: list[ChatMessage]) -> list[LearningCandidate]:
        self.calls += 1
        return [
            LearningCandidate(
                id="learn-duplicate",
                kind="user_preference",
                title="Concise answers",
                content="以后回答高效简洁。",
                confidence="high",
                suggested_target="global_bootstrap",
                source_session_id=session_id,
                source_turn_id=turn_id,
            )
        ]


def _runtime_with_learning(tmp_path: Path, monkeypatch) -> tuple[AgentRuntime, LearningStore, DuplicatePreferenceExtractor]:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / ".global"))
    settings = Settings.load(tmp_path)
    store = SessionStore(tmp_path / ".pp-agent" / "sessions")
    record = store.create("system", ModelConfig())
    learning_store = LearningStore(tmp_path / ".pp-agent" / "learning")
    extractor = DuplicatePreferenceExtractor()
    learning = LearningRuntime(
        workspace=tmp_path,
        llm_client=None,
        settings=LearningSettings(detailed_memory_sync_index_after_write=False),
        store=learning_store,
        extractor=extractor,
    )
    runtime = AgentRuntime(
        llm_client=OkLLMClient(),
        tool_registry=ToolRegistry(tmp_path, current_session_id=record.id, policy=settings.tool_policy),
        session_store=store,
        session_id=record.id,
        system_prompt="system",
        require_plan_approval=False,
        learning_runtime=learning,
        core_memory_service=service_for_workspace(tmp_path, settings),
    )
    return runtime, learning_store, extractor


def test_explicit_remember_creates_core_candidate_not_learning_duplicate(tmp_path: Path, monkeypatch) -> None:
    runtime, learning_store, extractor = _runtime_with_learning(tmp_path, monkeypatch)

    runtime.prompt("记住：以后回答高效简洁。")

    pending = runtime.core_memory_service.store.list_pending(workspace_id=runtime.core_memory_service.workspace_id)
    assert len(pending) == 1
    assert pending[0].metadata["explicit_user_memory"] is True
    assert extractor.calls == 0
    assert learning_store.list_candidates() == []
    assert not (runtime.core_memory_service.settings.global_dir / "MEMORY.md").exists()


def test_explicit_memory_not_auto_applied_twice_to_memory_md(tmp_path: Path, monkeypatch) -> None:
    runtime, learning_store, extractor = _runtime_with_learning(tmp_path, monkeypatch)

    runtime.prompt("记住：以后回答高效简洁。")
    pending = runtime.core_memory_service.store.list_pending(workspace_id=runtime.core_memory_service.workspace_id)
    approved = runtime.core_memory_service.approve(pending[0].id, actor="test")
    content = (runtime.core_memory_service.settings.global_dir / "MEMORY.md").read_text(encoding="utf-8")
    search = memory_search_executor(
        tmp_path,
        {"query": "以后回答高效简洁", "scope": "global", "top_k": 5},
        settings=runtime.core_memory_service.settings,
    )

    assert approved.immediate_effect is True
    assert extractor.calls == 0
    assert learning_store.list_candidates() == []
    assert content.count("回答高效简洁") == 1
    result_texts = [result["snippet"] for result in search.details["results"]]
    assert sum("回答高效简洁" in text for text in result_texts) == 1
