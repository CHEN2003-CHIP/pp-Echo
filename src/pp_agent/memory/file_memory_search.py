from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from pp_agent.memory.embedding import EmbeddingProvider
from pp_agent.memory.file_memory_bm25 import FileMemoryBM25Index
from pp_agent.memory.file_memory_chunker import FileMemoryChunk, MarkdownFileChunker
from pp_agent.memory.file_memory_store import FileMemoryIndexStore
from pp_agent.memory.file_memory_vector import FileMemoryVectorIndexProtocol


logger = logging.getLogger(__name__)

SearchMode = Literal["auto", "hybrid", "bm25", "vector"]
MemoryScope = Literal["auto", "workspace", "global", "all"]


@dataclass(frozen=True)
class FileMemorySearchRequest:
    query: str
    top_k: int = 5
    mode: SearchMode = "auto"
    scope: MemoryScope = "auto"
    include_debug: bool = False


@dataclass(frozen=True)
class FileMemorySearchHit:
    path: str
    source_scope: str
    line_start: int
    line_end: int
    score: float
    vector_score: float
    bm25_score: float
    sources: list[str]
    heading_path: list[str]
    snippet: str
    final_score: float = 0.0
    recency_score: float | None = None
    path_boost: float | None = None

    def to_dict(self, *, include_debug: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "path": self.path,
            "source_scope": self.source_scope,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "score": round(self.score, 6),
            "vector_score": round(self.vector_score, 6),
            "bm25_score": round(self.bm25_score, 6),
            "sources": list(self.sources),
            "heading_path": list(self.heading_path),
            "snippet": self.snippet,
        }
        if include_debug:
            payload.update(
                {
                    "final_score": round(self.final_score, 6),
                    "recency_score": self.recency_score,
                    "path_boost": self.path_boost,
                }
            )
        return payload


@dataclass(frozen=True)
class FileMemorySearchResult:
    query: str
    mode: str
    semantic_available: bool
    bm25_available: bool
    results: list[FileMemorySearchHit] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self, *, include_debug: bool = False) -> dict[str, object]:
        return {
            "query": self.query,
            "mode": self.mode,
            "semantic_available": self.semantic_available,
            "bm25_available": self.bm25_available,
            "results": [hit.to_dict(include_debug=include_debug) for hit in self.results],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class FileMemorySyncSummary:
    scanned: int = 0
    indexed_files: int = 0
    indexed_chunks: int = 0
    embedded_chunks: int = 0
    deleted_files: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "scanned": self.scanned,
            "indexed_files": self.indexed_files,
            "indexed_chunks": self.indexed_chunks,
            "embedded_chunks": self.embedded_chunks,
            "deleted_files": self.deleted_files,
            "warnings": list(self.warnings),
        }


class FileMemorySearchEngine:
    def __init__(
        self,
        *,
        store: FileMemoryIndexStore,
        chunker: MarkdownFileChunker,
        embedding_provider: EmbeddingProvider,
        vector_index: FileMemoryVectorIndexProtocol,
        vector_weight: float = 0.7,
        bm25_weight: float = 0.3,
        candidate_multiplier: int = 4,
        max_per_file: int = 3,
        snippet_chars: int = 700,
        sync_on_search: bool = True,
        allow_remote_embedding: bool = True,
    ) -> None:
        self.store = store
        self.chunker = chunker
        self.embedding_provider = embedding_provider
        self.vector_index = vector_index
        self.vector_weight = float(vector_weight)
        self.bm25_weight = float(bm25_weight)
        self.candidate_multiplier = max(1, int(candidate_multiplier))
        self.max_per_file = max(1, int(max_per_file))
        self.snippet_chars = max(80, int(snippet_chars))
        self.sync_on_search = bool(sync_on_search)
        self.allow_remote_embedding = bool(allow_remote_embedding)

    def sync(self, *, embed: bool = True) -> FileMemorySyncSummary:
        warnings: list[str] = []
        files = self.store.scan_memory_files()
        indexed = self.store.indexed_files()
        indexed_files = 0
        indexed_chunks = 0
        active_paths = {file.path for file in files}
        stale_chunk_ids = [
            chunk.chunk_id
            for chunk in self.store.list_chunks(active_only=True)
            if chunk.path not in active_paths
        ]
        missing_paths = self.store.deactivate_missing_files(active_paths)
        if stale_chunk_ids:
            try:
                self.vector_index.delete_chunk_ids(stale_chunk_ids)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Vector delete failed for removed memory files: {exc}")
        for file in files:
            previous = indexed.get(file.path)
            if previous and previous.content_hash == file.content_hash:
                if previous.mtime != file.mtime or previous.size != file.size:
                    self.store.mark_file_seen(file)
                continue
            try:
                text = file.absolute_path.read_text(encoding="utf-8-sig")
                chunks = self.chunker.chunk_text(path=file.path, text=text, file_mtime=file.mtime)
                self.store.sync_file(file, chunks)
                indexed_files += 1
                indexed_chunks += len(chunks)
            except Exception as exc:  # noqa: BLE001
                logger.warning("File memory indexing failed for %s: %s", file.path, exc)
                warnings.append(f"Failed to index {file.path}: {exc}")
        embedded = self._embed_pending_chunks(warnings) if embed else 0
        return FileMemorySyncSummary(
            scanned=len(files),
            indexed_files=indexed_files,
            indexed_chunks=indexed_chunks,
            embedded_chunks=embedded,
            deleted_files=len(missing_paths),
            warnings=warnings,
        )

    def search(self, request: FileMemorySearchRequest) -> FileMemorySearchResult:
        query = request.query.strip()
        warnings: list[str] = []
        if not query:
            return FileMemorySearchResult(query=request.query, mode="bm25", semantic_available=False, bm25_available=False)
        if self.sync_on_search:
            summary = self.sync(embed=request.mode != "bm25")
            warnings.extend(summary.warnings)
        chunks = self.store.list_chunks(active_only=True)
        chunks = [chunk for chunk in chunks if self._scope_allows(chunk.path, scope=request.scope, query=query)]
        semantic_available = self._semantic_available()
        bm25_available = bool(chunks)
        mode = self._resolve_mode(request.mode, semantic_available=semantic_available, bm25_available=bm25_available)
        candidate_limit = max(1, int(request.top_k)) * self.candidate_multiplier
        candidates: dict[str, dict[str, object]] = {}
        chunk_map = {chunk.chunk_id: chunk for chunk in chunks}

        if mode in {"hybrid", "bm25"}:
            try:
                bm25_hits = FileMemoryBM25Index(chunks).search(query, limit=candidate_limit)
                for hit in bm25_hits:
                    bucket = candidates.setdefault(hit.chunk_id, {"vector_score": 0.0, "bm25_score": 0.0, "sources": set()})
                    bucket["bm25_score"] = max(float(bucket["bm25_score"]), hit.score)
                    bucket["sources"].add("bm25")
            except Exception as exc:  # noqa: BLE001
                bm25_available = False
                warnings.append(f"BM25 search failed; falling back when possible: {exc}")

        if mode in {"hybrid", "vector"} and semantic_available:
            try:
                query_embedding = self.embedding_provider.embed_texts([query])[0]
                vector_hits = self.vector_index.query(query_embedding=query_embedding, limit=candidate_limit)
                for hit in vector_hits:
                    if hit.chunk_id not in chunk_map:
                        continue
                    bucket = candidates.setdefault(hit.chunk_id, {"vector_score": 0.0, "bm25_score": 0.0, "sources": set()})
                    bucket["vector_score"] = max(float(bucket["vector_score"]), self._vector_score(hit.score, metadata=hit.metadata))
                    bucket["sources"].add("vector")
            except Exception as exc:  # noqa: BLE001
                semantic_available = False
                warnings.append(f"Vector search failed; falling back when possible: {exc}")

        if not candidates:
            fallback_mode = "bm25" if not semantic_available else mode
            return FileMemorySearchResult(
                query=query,
                mode=fallback_mode,
                semantic_available=semantic_available,
                bm25_available=bm25_available,
                results=[],
                warnings=warnings,
            )

        weighted = self._weights(mode=mode, semantic_available=semantic_available, bm25_available=bm25_available)
        ranked = []
        for chunk_id, scores in candidates.items():
            chunk = chunk_map.get(chunk_id)
            if chunk is None:
                continue
            vector_score = float(scores.get("vector_score") or 0.0)
            bm25_score = float(scores.get("bm25_score") or 0.0)
            final_score = weighted[0] * vector_score + weighted[1] * bm25_score
            ranked.append((final_score, chunk, vector_score, bm25_score, sorted(scores.get("sources") or [])))
        ranked.sort(key=lambda item: (-item[0], item[1].path, item[1].line_start, item[1].chunk_id))
        selected = self._diversify(ranked, top_k=max(1, int(request.top_k)))
        return FileMemorySearchResult(
            query=query,
            mode=mode,
            semantic_available=semantic_available,
            bm25_available=bm25_available,
            results=selected,
            warnings=warnings,
        )

    def _embed_pending_chunks(self, warnings: list[str]) -> int:
        if not self._semantic_available():
            return 0
        embedding_model = self.embedding_provider.model_name()
        pending = self.store.chunks_needing_embedding(embedding_model=embedding_model)
        if not pending:
            return 0
        try:
            embeddings = self.embedding_provider.embed_texts([chunk.text for chunk in pending])
            upserted = self.vector_index.upsert_chunks(pending, embeddings=embeddings, embedding_model=embedding_model)
            self.store.mark_chunks_vector_indexed(upserted, embedding_model=embedding_model)
            return len(upserted)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"File memory embedding failed; BM25-only search remains available: {exc}")
            logger.warning("File memory embedding failed: %s", exc)
            return 0

    def _semantic_available(self) -> bool:
        return (
            self.allow_remote_embedding
            and self.embedding_provider.is_enabled()
            and self.vector_index.is_enabled()
        )

    @staticmethod
    def _resolve_mode(mode: SearchMode, *, semantic_available: bool, bm25_available: bool) -> str:
        if mode == "bm25":
            return "bm25"
        if mode == "vector":
            return "vector" if semantic_available else "bm25"
        if mode == "hybrid":
            if semantic_available and bm25_available:
                return "hybrid"
            return "vector" if semantic_available else "bm25"
        if semantic_available and bm25_available:
            return "hybrid"
        return "vector" if semantic_available else "bm25"

    def _weights(self, *, mode: str, semantic_available: bool, bm25_available: bool) -> tuple[float, float]:
        if mode == "vector" or not bm25_available:
            return 1.0, 0.0
        if mode == "bm25" or not semantic_available:
            return 0.0, 1.0
        total = max(0.000001, self.vector_weight + self.bm25_weight)
        return self.vector_weight / total, self.bm25_weight / total

    @staticmethod
    def _vector_score(raw_score: float, *, metadata: dict[str, object]) -> float:
        score_kind = str(metadata.get("score_kind") or metadata.get("metric") or "").lower()
        if score_kind in {"cosine", "similarity", "cosine_similarity"}:
            return max(0.0, min(1.0, (float(raw_score) + 1.0) / 2.0))
        if raw_score < 0:
            return 0.0
        return 1.0 / (1.0 + float(raw_score))

    def _diversify(self, ranked: list[tuple[float, FileMemoryChunk, float, float, list[str]]], *, top_k: int) -> list[FileMemorySearchHit]:
        selected: list[FileMemorySearchHit] = []
        per_file: dict[str, int] = {}
        for final_score, chunk, vector_score, bm25_score, sources in ranked:
            if per_file.get(chunk.path, 0) >= self.max_per_file:
                continue
            selected.append(
                FileMemorySearchHit(
                    path=chunk.path,
                    source_scope=self._source_scope(chunk.path),
                    line_start=chunk.line_start,
                    line_end=chunk.line_end,
                    score=final_score,
                    vector_score=vector_score,
                    bm25_score=bm25_score,
                    sources=sources,
                    heading_path=list(chunk.heading_path),
                    snippet=self._snippet(chunk.text),
                    final_score=final_score,
                    recency_score=None,
                    path_boost=None,
                )
            )
            per_file[chunk.path] = per_file.get(chunk.path, 0) + 1
            if len(selected) >= top_k:
                break
        return selected

    def _snippet(self, text: str) -> str:
        compact = " ".join(text.split())
        if len(compact) <= self.snippet_chars:
            return compact
        return compact[: max(0, self.snippet_chars - 3)].rstrip() + "..."

    @staticmethod
    def _source_scope(path: str) -> str:
        normalized = path.replace("\\", "/")
        if normalized == "global/MEMORY.md":
            return "global_bootstrap"
        if normalized == "MEMORY.md":
            return "workspace_bootstrap"
        if normalized.startswith("memory/daily/"):
            return "journal"
        return "detailed"

    def _scope_allows(self, path: str, *, scope: MemoryScope, query: str) -> bool:
        source_scope = self._source_scope(path)
        if scope == "all":
            return True
        if scope == "global":
            return source_scope == "global_bootstrap"
        if scope == "workspace":
            return source_scope != "global_bootstrap"
        if source_scope != "global_bootstrap":
            return True
        lowered = query.lower()
        global_signals = ("preference", "user always", "always", "never", "default", "偏好", "默认", "记住")
        return any(signal in lowered for signal in global_signals)
