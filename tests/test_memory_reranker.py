from __future__ import annotations

from pathlib import Path

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.memory import HistoryIndexer, SQLiteHistoryStore, SQLiteMemoryProvider
from pp_agent.memory.retrieval import HistoryRetriever
from pp_agent.memory.reranker import LightweightReranker
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


class _FailingReranker:
    def is_enabled(self) -> bool:
        return True

    def rerank(self, *, query_text, candidates, limit):
        raise RuntimeError("reranker boom")


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


def test_reranker_reorders_hydrated_candidates(tmp_path: Path) -> None:
    store = SQLiteHistoryStore(tmp_path / "history.db")
    path_chunk_id = _seed_message(store, session_id="session-1", role="assistant", text="Run pytest tests/test_runtime.py after changing src/pp_agent/runtime/runtime.py.")
    generic_chunk_id = _seed_message(store, session_id="session-1", role="assistant", text="We discussed general implementation details.", turn_id="turn-2")
    retriever = HistoryRetriever(
        store=store,
        embedding_provider=_EmbeddingProvider(),
        vector_index=_VectorIndex(
            [
                VectorQueryResult(chunk_id=generic_chunk_id, score=0.1, text="We discussed general implementation details."),
                VectorQueryResult(chunk_id=path_chunk_id, score=0.1, text="Run pytest tests/test_runtime.py after changing src/pp_agent/runtime/runtime.py."),
            ]
        ),
        reranker=LightweightReranker(enabled=True, max_candidates=8, path_weight_boost=1.2),
    )

    results = retriever.retrieve(query_text="which file and command matter", session_id="session-1", limit=6)

    assert results[0].chunk_id == path_chunk_id
    assert results[0].rerank_details is not None
    assert results[0].rerank_details["file_path_weight"] > results[1].rerank_details["file_path_weight"]


def test_reranker_disabled_keeps_existing_behavior(tmp_path: Path) -> None:
    store = SQLiteHistoryStore(tmp_path / "history.db")
    first_chunk_id = _seed_message(store, session_id="session-1", role="assistant", text="general note")
    second_chunk_id = _seed_message(store, session_id="session-1", role="assistant", text="path note src/pp_agent/runtime/runtime.py", turn_id="turn-2")
    baseline_retriever = HistoryRetriever(
        store=store,
        embedding_provider=_EmbeddingProvider(),
        vector_index=_VectorIndex(
            [
                VectorQueryResult(chunk_id=first_chunk_id, score=0.1, text="general note"),
                VectorQueryResult(chunk_id=second_chunk_id, score=0.1, text="path note src/pp_agent/runtime/runtime.py"),
            ]
        ),
    )
    retriever = HistoryRetriever(
        store=store,
        embedding_provider=_EmbeddingProvider(),
        vector_index=_VectorIndex(
            [
                VectorQueryResult(chunk_id=first_chunk_id, score=0.1, text="general note"),
                VectorQueryResult(chunk_id=second_chunk_id, score=0.1, text="path note src/pp_agent/runtime/runtime.py"),
            ]
        ),
        reranker=LightweightReranker(enabled=False),
    )

    baseline = baseline_retriever.retrieve(query_text="note", session_id="session-1", limit=6)
    results = retriever.retrieve(query_text="note", session_id="session-1", limit=6)

    assert [item.chunk_id for item in results] == [item.chunk_id for item in baseline]
    assert all(item.rerank_details is None for item in results)


def test_reranker_failure_falls_back_to_existing_ranking(tmp_path: Path) -> None:
    store = SQLiteHistoryStore(tmp_path / "history.db")
    first_chunk_id = _seed_message(store, session_id="session-1", role="assistant", text="general note")
    second_chunk_id = _seed_message(store, session_id="session-1", role="assistant", text="path note src/pp_agent/runtime/runtime.py", turn_id="turn-2")
    baseline_retriever = HistoryRetriever(
        store=store,
        embedding_provider=_EmbeddingProvider(),
        vector_index=_VectorIndex(
            [
                VectorQueryResult(chunk_id=first_chunk_id, score=0.1, text="general note"),
                VectorQueryResult(chunk_id=second_chunk_id, score=0.1, text="path note src/pp_agent/runtime/runtime.py"),
            ]
        ),
    )
    retriever = HistoryRetriever(
        store=store,
        embedding_provider=_EmbeddingProvider(),
        vector_index=_VectorIndex(
            [
                VectorQueryResult(chunk_id=first_chunk_id, score=0.1, text="general note"),
                VectorQueryResult(chunk_id=second_chunk_id, score=0.1, text="path note src/pp_agent/runtime/runtime.py"),
            ]
        ),
        reranker=_FailingReranker(),
    )

    baseline = baseline_retriever.retrieve(query_text="note", session_id="session-1", limit=6)
    results = retriever.retrieve(query_text="note", session_id="session-1", limit=6)

    assert [item.chunk_id for item in results] == [item.chunk_id for item in baseline]
    assert all(item.rerank_details is None for item in results)
