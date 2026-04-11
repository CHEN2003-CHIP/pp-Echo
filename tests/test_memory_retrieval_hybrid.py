from __future__ import annotations

from pathlib import Path

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.memory import HistoryIndexer, SQLiteHistoryStore, SQLiteMemoryProvider
from pp_agent.memory.retrieval import HistoryRetriever
from pp_agent.memory.types import VectorQueryResult


class _EmbeddingProvider:
    def is_enabled(self) -> bool:
        return True

    def model_name(self) -> str:
        return "multimodal-embedding-v1"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2] for _ in texts]


class _VectorIndex:
    def __init__(self, results: list[VectorQueryResult]) -> None:
        self.results = results

    def is_enabled(self) -> bool:
        return True

    def upsert_chunks(self, chunks):
        return [chunk.chunk_id for chunk in chunks]

    def query(self, *, query_embedding, limit, where=None):
        return self.results[:limit]


class _FailingKeywordStore(SQLiteHistoryStore):
    def search_chunks_by_text(self, query_text: str, *, limit: int, session_id: str | None = None):
        raise RuntimeError("keyword search unavailable")


def _seed_message(
    store: SQLiteHistoryStore,
    *,
    session_id: str,
    role: str,
    text: str,
    turn_id: str = "turn-1",
) -> str:
    provider = SQLiteMemoryProvider(store=store, indexer=HistoryIndexer(chunk_target_tokens=20, chunk_max_tokens=25))
    provider.on_turn_persisted(
        session_id=session_id,
        turn_id=turn_id,
        new_messages=[ChatMessage(role=role, content=[TextPart(text=text)], timestamp=1.0)],
        metadata={"source": "runtime_dual_write", "workspace": "test"},
    )
    return store.list_chunks_for_session(session_id=session_id)[-1].id


def test_hybrid_retrieval_merges_keyword_and_vector_results(tmp_path: Path) -> None:
    store = SQLiteHistoryStore(tmp_path / "history.db")
    hybrid_chunk_id = _seed_message(store, session_id="session-1", role="assistant", text="pytest remains the preferred test runner")
    vector_only_chunk_id = _seed_message(store, session_id="session-2", role="assistant", text="runtime context lives in src/pp_agent/runtime/runtime.py")
    retriever = HistoryRetriever(
        store=store,
        embedding_provider=_EmbeddingProvider(),
        vector_index=_VectorIndex(
            [
                VectorQueryResult(chunk_id=hybrid_chunk_id, score=0.1, text="pytest remains the preferred test runner"),
                VectorQueryResult(chunk_id=vector_only_chunk_id, score=0.2, text="runtime context lives in src/pp_agent/runtime/runtime.py"),
            ]
        ),
        hybrid_enable=True,
    )

    results = retriever.retrieve(query_text="pytest", session_id="session-1", limit=6)

    assert [item.chunk_id for item in results] == [hybrid_chunk_id, vector_only_chunk_id]
    assert results[0].retrieval_sources == ("keyword", "vector")
    assert len({item.chunk_id for item in results}) == 2


def test_hybrid_retrieval_prefers_same_session_hits(tmp_path: Path) -> None:
    store = SQLiteHistoryStore(tmp_path / "history.db")
    same_chunk_id = _seed_message(store, session_id="session-a", role="assistant", text="pytest remains the preferred test runner")
    other_chunk_id = _seed_message(store, session_id="session-b", role="assistant", text="pytest remains the preferred test runner")
    retriever = HistoryRetriever(
        store=store,
        embedding_provider=_EmbeddingProvider(),
        vector_index=_VectorIndex(
            [
                VectorQueryResult(chunk_id=other_chunk_id, score=0.1, text="pytest remains the preferred test runner"),
                VectorQueryResult(chunk_id=same_chunk_id, score=0.1, text="pytest remains the preferred test runner"),
            ]
        ),
        same_session_bias=1.0,
        hybrid_enable=True,
    )

    results = retriever.retrieve(query_text="pytest", session_id="session-a", limit=6)

    assert results[0].chunk_id == same_chunk_id
    assert results[0].same_session_bonus > results[1].same_session_bonus


def test_hybrid_retrieval_applies_keyword_and_semantic_scoring(tmp_path: Path) -> None:
    store = SQLiteHistoryStore(tmp_path / "history.db")
    strong_keyword_chunk_id = _seed_message(
        store,
        session_id="session-1",
        role="assistant",
        text="pytest concise pytest concise guidance for future replies",
    )
    weak_keyword_chunk_id = _seed_message(
        store,
        session_id="session-1",
        role="assistant",
        text="pytest guidance for future replies",
        turn_id="turn-2",
    )
    retriever = HistoryRetriever(
        store=store,
        embedding_provider=_EmbeddingProvider(),
        vector_index=_VectorIndex(
            [
                VectorQueryResult(chunk_id=weak_keyword_chunk_id, score=0.1, text="pytest guidance for future replies"),
                VectorQueryResult(chunk_id=strong_keyword_chunk_id, score=0.1, text="pytest concise pytest concise guidance for future replies"),
            ]
        ),
        hybrid_enable=True,
    )

    results = retriever.retrieve(query_text="pytest concise", session_id="session-1", limit=6)

    assert results[0].chunk_id == strong_keyword_chunk_id
    assert results[0].keyword_score > results[1].keyword_score
    assert results[0].semantic_score == results[1].semantic_score


def test_hybrid_search_failure_degrades_to_existing_behavior(tmp_path: Path) -> None:
    store = _FailingKeywordStore(tmp_path / "history.db")
    chunk_id = _seed_message(store, session_id="session-1", role="assistant", text="pytest remains the preferred test runner")
    retriever = HistoryRetriever(
        store=store,
        embedding_provider=_EmbeddingProvider(),
        vector_index=_VectorIndex([VectorQueryResult(chunk_id=chunk_id, score=0.1, text="pytest remains the preferred test runner")]),
        hybrid_enable=True,
    )

    results = retriever.retrieve(query_text="pytest", session_id="session-1", limit=6)

    assert len(results) == 1
    assert results[0].chunk_id == chunk_id
    assert results[0].retrieval_sources == ("vector",)
