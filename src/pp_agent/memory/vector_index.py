from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pp_agent.memory.types import IndexedChunk, VectorQueryResult


class VectorIndex(Protocol):
    def is_enabled(self) -> bool:
        ...

    def upsert_chunks(self, chunks: list[IndexedChunk]) -> list[str]:
        ...

    def query(
        self,
        *,
        query_embedding: list[float],
        limit: int,
        where: dict[str, Any] | None = None,
    ) -> list[VectorQueryResult]:
        ...


class NoopVectorIndex:
    def is_enabled(self) -> bool:
        return False

    def upsert_chunks(self, chunks: list[IndexedChunk]) -> list[str]:
        return [chunk.chunk_id for chunk in chunks]

    def query(
        self,
        *,
        query_embedding: list[float],
        limit: int,
        where: dict[str, Any] | None = None,
    ) -> list[VectorQueryResult]:
        return []


class ChromaVectorIndex:
    def __init__(
        self,
        *,
        path: Path,
        collection_name: str,
        client_factory=None,
    ) -> None:
        self.path = Path(path).expanduser()
        self.path.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self._client_factory = client_factory

    def is_enabled(self) -> bool:
        return True

    def upsert_chunks(self, chunks: list[IndexedChunk]) -> list[str]:
        if not chunks:
            return []
        collection = self._collection()
        collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            embeddings=[chunk.embedding for chunk in chunks],
            metadatas=[self._metadata(chunk) for chunk in chunks],
        )
        return [chunk.chunk_id for chunk in chunks]

    def query(
        self,
        *,
        query_embedding: list[float],
        limit: int,
        where: dict[str, Any] | None = None,
    ) -> list[VectorQueryResult]:
        collection = self._collection()
        result = collection.query(query_embeddings=[query_embedding], n_results=limit, where=where)
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        return [
            VectorQueryResult(
                chunk_id=chunk_id,
                text=document,
                metadata=metadata or {},
                score=float(distance if distance is not None else 0.0),
            )
            for chunk_id, document, metadata, distance in zip(ids, documents, metadatas, distances)
        ]

    def _collection(self):
        client = self._client()
        return client.get_or_create_collection(name=self.collection_name)

    def _client(self):
        if self._client_factory is not None:
            return self._client_factory(self.path)
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("chromadb is not installed") from exc
        # Disable anonymized telemetry to avoid noisy posthog-related warnings in local CLI runs.
        settings = Settings(anonymized_telemetry=False)
        settings.chroma_product_telemetry_impl = "pp_agent.memory.chroma_telemetry.NoOpProductTelemetryClient"
        return chromadb.PersistentClient(
            path=str(self.path),
            settings=settings,
        )

    @staticmethod
    def _metadata(chunk: IndexedChunk) -> dict[str, Any]:
        metadata = {
            "session_id": chunk.session_id,
            "turn_id": chunk.turn_id,
            "message_id": chunk.message_id,
            "chunk_id": chunk.chunk_id,
            "role": chunk.role,
            "source_kind": chunk.source_kind,
            "created_at": chunk.created_at,
            "embedding_model": chunk.embedding_model,
            **dict(chunk.metadata),
        }
        return {key: value for key, value in metadata.items() if value is not None}
