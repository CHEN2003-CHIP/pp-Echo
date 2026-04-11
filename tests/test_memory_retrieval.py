import sqlite3
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
        self.queries = []

    def is_enabled(self) -> bool:
        return True

    def upsert_chunks(self, chunks):
        return [chunk.chunk_id for chunk in chunks]

    def query(self, *, query_embedding, limit, where=None):
        self.queries.append({"query_embedding": query_embedding, "limit": limit, "where": where})
        return self.results[:limit]


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


def test_retriever_queries_chroma_and_hydrates_sqlite(tmp_path: Path) -> None:
    store = SQLiteHistoryStore(tmp_path / "history.db")
    chunk_id = _seed_message(store, session_id="session-1", role="user", text="remember my preference for pytest")
    vector_index = _VectorIndex([VectorQueryResult(chunk_id=chunk_id, score=0.1, text="remember my preference for pytest")])
    retriever = HistoryRetriever(store=store, embedding_provider=_EmbeddingProvider(), vector_index=vector_index)

    results = retriever.retrieve(query_text="what is my preference", session_id="session-1", limit=6)

    assert len(vector_index.queries) == 1
    assert len(results) == 1
    assert results[0].chunk_id == chunk_id
    assert results[0].message.role == "user"
    assert results[0].session_id == "session-1"
    assert results[0].embedding_model is None or isinstance(results[0].embedding_model, str)


def test_retriever_filters_recent_chunks(tmp_path: Path) -> None:
    store = SQLiteHistoryStore(tmp_path / "history.db")
    chunk_id = _seed_message(store, session_id="session-1", role="assistant", text="the project uses pytest")
    vector_index = _VectorIndex([VectorQueryResult(chunk_id=chunk_id, score=0.1, text="the project uses pytest")])
    retriever = HistoryRetriever(store=store, embedding_provider=_EmbeddingProvider(), vector_index=vector_index)

    results = retriever.retrieve(query_text="pytest", session_id="session-1", recent_chunk_ids={chunk_id}, limit=6)

    assert results == []


def test_retriever_prefers_same_session_hits(tmp_path: Path) -> None:
    store = SQLiteHistoryStore(tmp_path / "history.db")
    same_chunk_id = _seed_message(store, session_id="session-a", role="assistant", text="same session answer")
    other_chunk_id = _seed_message(store, session_id="session-b", role="assistant", text="cross session answer")
    vector_index = _VectorIndex(
        [
            VectorQueryResult(chunk_id=other_chunk_id, score=0.1, text="cross session answer"),
            VectorQueryResult(chunk_id=same_chunk_id, score=0.1, text="same session answer"),
        ]
    )
    retriever = HistoryRetriever(store=store, embedding_provider=_EmbeddingProvider(), vector_index=vector_index, same_session_bias=1.0)

    results = retriever.retrieve(query_text="answer", session_id="session-a", limit=6)

    assert len(results) == 2
    assert results[0].session_id == "session-a"
    assert results[0].same_session_bonus > results[1].same_session_bonus


def test_retriever_applies_recency_and_source_kind_ranking(tmp_path: Path) -> None:
    store = SQLiteHistoryStore(tmp_path / "history.db")
    old_tool_chunk_id = _seed_message(store, session_id="session-1", role="tool", text="old tool output path failed", turn_id="turn-1")
    new_user_chunk_id = _seed_message(store, session_id="session-1", role="user", text="prefer short answers and clear constraints", turn_id="turn-2")
    with sqlite3.connect(tmp_path / "history.db") as connection:
        connection.execute("UPDATE history_chunks SET created_at = 10, updated_at = 10 WHERE id = ?", (old_tool_chunk_id,))
        connection.execute("UPDATE history_chunks SET created_at = 100, updated_at = 100 WHERE id = ?", (new_user_chunk_id,))
        connection.execute("UPDATE history_messages SET created_at = 10 WHERE id = (SELECT message_id FROM history_chunks WHERE id = ?)", (old_tool_chunk_id,))
        connection.execute("UPDATE history_messages SET created_at = 100 WHERE id = (SELECT message_id FROM history_chunks WHERE id = ?)", (new_user_chunk_id,))
    vector_index = _VectorIndex(
        [
            VectorQueryResult(chunk_id=old_tool_chunk_id, score=0.05, text="old tool output path failed"),
            VectorQueryResult(chunk_id=new_user_chunk_id, score=0.20, text="prefer short answers and clear constraints"),
        ]
    )
    retriever = HistoryRetriever(store=store, embedding_provider=_EmbeddingProvider(), vector_index=vector_index)

    results = retriever.retrieve(query_text="constraints", session_id="session-1", limit=6)

    assert len(results) == 2
    assert results[0].chunk_id == new_user_chunk_id
    assert results[0].recency_score >= results[1].recency_score
    assert results[0].source_kind_weight >= results[1].source_kind_weight
