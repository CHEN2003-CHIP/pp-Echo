from pathlib import Path

from pp_agent.memory.types import IndexedChunk
from pp_agent.memory.vector_index import ChromaVectorIndex


class _FakeCollection:
    def __init__(self) -> None:
        self.upserts = []

    def upsert(self, *, ids, documents, embeddings, metadatas):
        self.upserts.append(
            {
                "ids": ids,
                "documents": documents,
                "embeddings": embeddings,
                "metadatas": metadatas,
            }
        )

    def query(self, *, query_embeddings, n_results, where=None):
        upsert = self.upserts[-1]
        return {
            "ids": [upsert["ids"][:n_results]],
            "documents": [upsert["documents"][:n_results]],
            "metadatas": [upsert["metadatas"][:n_results]],
            "distances": [[0.01 for _ in upsert["ids"][:n_results]]],
        }


class _FakeClient:
    def __init__(self) -> None:
        self.collection = _FakeCollection()

    def get_or_create_collection(self, *, name):
        return self.collection


def test_chroma_vector_index_upserts_chunks(tmp_path: Path) -> None:
    client = _FakeClient()
    index = ChromaVectorIndex(
        path=tmp_path / "chroma",
        collection_name="pp_agent_history",
        client_factory=lambda _path: client,
    )
    chunk = IndexedChunk(
        chunk_id="chunk-1",
        message_id="message-1",
        session_id="session-1",
        turn_id="turn-1",
        role="assistant",
        source_kind="assistant",
        text="chunk text",
        created_at=1.0,
        embedding=[0.1, 0.2],
        embedding_model="multimodal-embedding-v1",
        metadata={"extra": "value"},
    )

    ids = index.upsert_chunks([chunk])
    results = index.query(query_embedding=[0.1, 0.2], limit=1, where={"session_id": "session-1"})

    assert ids == ["chunk-1"]
    assert client.collection.upserts[0]["ids"] == ["chunk-1"]
    assert client.collection.upserts[0]["documents"] == ["chunk text"]
    assert client.collection.upserts[0]["metadatas"][0]["session_id"] == "session-1"
    assert client.collection.upserts[0]["metadatas"][0]["source_kind"] == "assistant"
    assert client.collection.upserts[0]["metadatas"][0]["embedding_model"] == "multimodal-embedding-v1"
    assert results[0].chunk_id == "chunk-1"
    assert results[0].text == "chunk text"
