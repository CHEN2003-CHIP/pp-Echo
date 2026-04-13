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


def test_chroma_vector_index_disables_anonymized_telemetry_by_default(tmp_path: Path, monkeypatch) -> None:
    captured = {}

    class _FakeSettings:
        def __init__(self, *, anonymized_telemetry):
            self.anonymized_telemetry = anonymized_telemetry
            self.chroma_product_telemetry_impl = None

    class _FakeChromadb:
        @staticmethod
        def PersistentClient(*, path, settings):
            captured["path"] = path
            captured["settings"] = settings
            return "client"

    import pp_agent.memory.vector_index as vector_index_module

    monkeypatch.setitem(__import__("sys").modules, "chromadb", _FakeChromadb())
    monkeypatch.setitem(__import__("sys").modules, "chromadb.config", type("ConfigModule", (), {"Settings": _FakeSettings})())

    index = ChromaVectorIndex(path=tmp_path / "chroma", collection_name="pp_agent_history")

    client = index._client()

    assert client == "client"
    assert captured["path"] == str(tmp_path / "chroma")
    assert captured["settings"].anonymized_telemetry is False
    assert (
        captured["settings"].chroma_product_telemetry_impl
        == "pp_agent.memory.chroma_telemetry.NoOpProductTelemetryClient"
    )
