from collections.abc import Iterator
from pathlib import Path

from pp_agent.llm import ModelConfig
from pp_agent.domain import ChatMessage, TextPart
from pp_agent.memory import HistoryIndexer
from pp_agent.memory.embedding import NoopEmbeddingProvider
from pp_agent.memory.index_pipeline import MemoryIndexPipeline
from pp_agent.memory.provider import NoopMemoryProvider, SQLiteMemoryProvider
from pp_agent.memory.sqlite_store import SQLiteHistoryStore
from pp_agent.memory.vector_index import NoopVectorIndex
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.storage.sessions import SessionStore
from pp_agent.tools.registry import ToolRegistry


class _NoopLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        yield {"text": "ok", "tool_calls": [], "finish_reason": "stop", "raw": {}}


class _EmbeddingProvider:
    def __init__(self, fail_once: bool = False) -> None:
        self.fail_once = fail_once
        self.calls = 0

    def is_enabled(self) -> bool:
        return True

    def model_name(self) -> str:
        return "multimodal-embedding-v1"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.fail_once and self.calls == 1:
            raise RuntimeError("embedding failed")
        return [[float(index + 1), float(index + 2)] for index, _ in enumerate(texts)]


class _VectorIndex:
    def __init__(self) -> None:
        self.calls = 0
        self.upserted = {}

    def is_enabled(self) -> bool:
        return True

    def upsert_chunks(self, chunks) -> list[str]:
        self.calls += 1
        for chunk in chunks:
            self.upserted[chunk.chunk_id] = chunk
        return [chunk.chunk_id for chunk in chunks]

    def query(self, *, query_embedding, limit, where=None):
        return []


def _seed_pending_chunks(tmp_path: Path, session_id: str = "session-1") -> SQLiteHistoryStore:
    store = SQLiteHistoryStore(tmp_path / "history.db")
    provider = SQLiteMemoryProvider(store=store, indexer=HistoryIndexer(chunk_target_tokens=20, chunk_max_tokens=25))
    provider.on_turn_persisted(
        session_id=session_id,
        turn_id="turn-1",
        new_messages=[
            ChatMessage(
                role="assistant",
                content=[TextPart(text="alpha beta gamma delta " * 20)],
                timestamp=1.0,
            )
        ],
        metadata={"source": "runtime_dual_write", "workspace": str(tmp_path)},
    )
    return store


def test_index_pipeline_marks_chunks_indexed(tmp_path: Path) -> None:
    store = _seed_pending_chunks(tmp_path)
    vector_index = _VectorIndex()
    pipeline = MemoryIndexPipeline(
        store=store,
        embedding_provider=_EmbeddingProvider(),
        vector_index=vector_index,
        embedding_batch_size=8,
        indexing_batch_size=100,
    )

    summary = pipeline.index_pending_chunks(limit=100)
    chunks = store.list_chunks_for_session(session_id="session-1")

    assert summary.scanned >= 1
    assert summary.indexed >= 1
    assert all(chunk.embedding_status == "indexed" for chunk in chunks)
    assert all(chunk.embedding_model == "multimodal-embedding-v1" for chunk in chunks)
    assert vector_index.calls >= 1


def test_index_pipeline_failed_chunks_can_retry(tmp_path: Path) -> None:
    store = _seed_pending_chunks(tmp_path)
    vector_index = _VectorIndex()
    failing_provider = _EmbeddingProvider(fail_once=True)
    pipeline = MemoryIndexPipeline(
        store=store,
        embedding_provider=failing_provider,
        vector_index=vector_index,
        embedding_batch_size=8,
        indexing_batch_size=100,
    )

    failed_summary = pipeline.rebuild_index_for_session("session-1")
    failed_chunks = store.list_chunks_for_session(session_id="session-1")
    assert failed_summary.failed >= 1
    assert any(chunk.embedding_status == "failed" for chunk in failed_chunks)

    retry_summary = pipeline.rebuild_index_for_session("session-1")
    retried_chunks = store.list_chunks_for_session(session_id="session-1")
    assert retry_summary.indexed >= 1
    assert all(chunk.embedding_status == "indexed" for chunk in retried_chunks)


def test_index_pipeline_does_not_break_main_flow_when_disabled(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    agent = AgentRuntime(
        llm_client=_NoopLLMClient(),
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
        require_plan_approval=False,
        memory_provider=NoopMemoryProvider(),
    )
    agent.restore_session_record(record)
    pipeline = MemoryIndexPipeline(
        store=SQLiteHistoryStore(tmp_path / "history.db"),
        embedding_provider=NoopEmbeddingProvider(),
        vector_index=NoopVectorIndex(),
    )

    summary = pipeline.index_pending_chunks(limit=100)
    events = agent.prompt("hello")

    assert summary.scanned == 0
    assert any(event.type == "agent_end" for event in events)


def test_rebuild_index_for_session_reindexes_existing_chunks(tmp_path: Path) -> None:
    store = _seed_pending_chunks(tmp_path, session_id="session-rebuild")
    vector_index = _VectorIndex()
    pipeline = MemoryIndexPipeline(
        store=store,
        embedding_provider=_EmbeddingProvider(),
        vector_index=vector_index,
        embedding_batch_size=8,
        indexing_batch_size=100,
    )

    first = pipeline.rebuild_index_for_session("session-rebuild")
    second = pipeline.rebuild_index_for_session("session-rebuild")
    chunks = store.list_chunks_for_session(session_id="session-rebuild")

    assert first.indexed >= 1
    assert second.indexed >= 1
    assert len(chunks) == len(vector_index.upserted)
    assert all(chunk.embedding_status == "indexed" for chunk in chunks)
