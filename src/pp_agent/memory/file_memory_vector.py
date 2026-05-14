from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol

from pp_agent.memory.file_memory_chunker import FileMemoryChunk
from pp_agent.memory.types import VectorQueryResult


logger = logging.getLogger(__name__)


class FileMemoryVectorIndexProtocol(Protocol):
    def is_enabled(self) -> bool:
        ...

    def upsert_chunks(
        self,
        chunks: list[FileMemoryChunk],
        *,
        embeddings: list[list[float]],
        embedding_model: str,
    ) -> list[str]:
        ...

    def query(self, *, query_embedding: list[float], limit: int) -> list[VectorQueryResult]:
        ...

    def delete_chunk_ids(self, chunk_ids: list[str]) -> None:
        ...


class NoopFileMemoryVectorIndex:
    def is_enabled(self) -> bool:
        return False

    def upsert_chunks(
        self,
        chunks: list[FileMemoryChunk],
        *,
        embeddings: list[list[float]],
        embedding_model: str,
    ) -> list[str]:
        _ = embeddings, embedding_model
        return [chunk.chunk_id for chunk in chunks]

    def query(self, *, query_embedding: list[float], limit: int) -> list[VectorQueryResult]:
        _ = query_embedding, limit
        return []

    def delete_chunk_ids(self, chunk_ids: list[str]) -> None:
        _ = chunk_ids


class ChromaFileMemoryVectorIndex:
    def __init__(self, *, path: Path, collection_name: str, client_factory=None) -> None:
        self.path = Path(path).expanduser()
        self.path.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self._client_factory = client_factory

    def is_enabled(self) -> bool:
        return True

    def upsert_chunks(
        self,
        chunks: list[FileMemoryChunk],
        *,
        embeddings: list[list[float]],
        embedding_model: str,
    ) -> list[str]:
        if not chunks:
            return []
        collection = self._collection()
        collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            embeddings=embeddings,
            metadatas=[self._metadata(chunk, embedding_model=embedding_model) for chunk in chunks],
        )
        return [chunk.chunk_id for chunk in chunks]

    def query(self, *, query_embedding: list[float], limit: int) -> list[VectorQueryResult]:
        if limit <= 0:
            return []
        collection = self._collection()
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=limit,
            where={"active": True},
        )
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

    def delete_chunk_ids(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        collection = self._collection()
        delete = getattr(collection, "delete", None)
        if delete is None:
            logger.debug("Chroma collection does not support delete; stale file-memory hits will be filtered by SQLite")
            return
        delete(ids=chunk_ids)

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
        settings = Settings(anonymized_telemetry=False)
        settings.chroma_product_telemetry_impl = "pp_agent.memory.chroma_telemetry.NoOpProductTelemetryClient"
        return chromadb.PersistentClient(path=str(self.path), settings=settings)

    @staticmethod
    def _metadata(chunk: FileMemoryChunk, *, embedding_model: str) -> dict[str, Any]:
        return {
            "source_kind": "file_memory",
            "active": True,
            "chunk_id": chunk.chunk_id,
            "path": chunk.path,
            "line_start": chunk.line_start,
            "line_end": chunk.line_end,
            "heading_path": " / ".join(chunk.heading_path),
            "content_hash": chunk.content_hash,
            "file_mtime": chunk.file_mtime,
            "embedding_model": embedding_model,
        }
