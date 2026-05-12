from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field

from pp_agent.memory.embedding import EmbeddingProvider
from pp_agent.memory.reranker import NoopReranker, Reranker
from pp_agent.memory.sqlite_store import SQLiteHistoryStore
from pp_agent.memory.types import HistoryChunkRecord, HistoryMessageRecord, SourceKind
from pp_agent.memory.vector_index import VectorIndex


logger = logging.getLogger(__name__)

SOURCE_KIND_PRIORITIES: dict[SourceKind, float] = {
    "user": 1.0,
    "assistant": 0.8,
    "tool": 0.7,
    "system": 0.5,
    "summary": 0.3,
}


@dataclass(frozen=True)
class RetrievedMessage:
    message_id: str
    session_id: str
    turn_id: str
    role: str
    text: str
    created_at: float
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    message_id: str
    session_id: str
    turn_id: str
    role: str
    source_kind: SourceKind
    text: str
    created_at: float
    embedding_model: str | None
    semantic_score: float
    keyword_score: float
    recency_score: float
    same_session_bonus: float
    source_kind_weight: float
    final_score: float
    retrieval_sources: tuple[str, ...]
    message: RetrievedMessage
    metadata: dict[str, object] = field(default_factory=dict)
    rerank_details: dict[str, float] | None = None


@dataclass(frozen=True)
class RetrievalRequest:
    query_text: str
    session_id: str | None
    recent_chunk_ids: set[str] = field(default_factory=set)
    limit: int = 6


@dataclass(frozen=True)
class RetrievalResult:
    request: RetrievalRequest
    chunks: list[RetrievedChunk]


@dataclass(frozen=True)
class RetrievalScoringConfig:
    semantic_weight: float = 0.40
    keyword_weight: float = 0.20
    recency_weight: float = 0.15
    same_session_weight: float = 0.15
    source_kind_weight: float = 0.10


class HistoryRetriever:
    def __init__(
        self,
        *,
        store: SQLiteHistoryStore,
        embedding_provider: EmbeddingProvider,
        vector_index: VectorIndex,
        same_session_bias: float = 1.0,
        scoring: RetrievalScoringConfig | None = None,
        hybrid_enable: bool = False,
        hybrid_keyword_limit: int = 12,
        hybrid_vector_limit: int = 12,
        reranker: Reranker | None = None,
        max_per_session: int = 2,
    ) -> None:
        self.store = store
        self.embedding_provider = embedding_provider
        self.vector_index = vector_index
        self.same_session_bias = same_session_bias
        self.scoring = scoring or RetrievalScoringConfig()
        self.hybrid_enable = hybrid_enable
        self.hybrid_keyword_limit = max(1, hybrid_keyword_limit)
        self.hybrid_vector_limit = max(1, hybrid_vector_limit)
        self.reranker = reranker or NoopReranker()
        self.max_per_session = max(1, max_per_session)

    def retrieve(
        self,
        *,
        query_text: str,
        session_id: str | None,
        recent_chunk_ids: set[str] | None = None,
        limit: int = 6,
        recent_fallback_keys: set[str] | None = None,
    ) -> list[RetrievedChunk]:
        clean_query = query_text.strip()
        if not clean_query or not self.embedding_provider.is_enabled() or not self.vector_index.is_enabled():
            return []
        request = RetrievalRequest(
            query_text=clean_query,
            session_id=session_id,
            recent_chunk_ids=set(recent_chunk_ids or set()),
            limit=limit,
        )
        candidate_scores = self._collect_candidates(request=request)
        if not candidate_scores:
            return []
        hydrated_chunks = self.store.get_chunks_by_ids(list(candidate_scores))
        if not hydrated_chunks:
            return []
        messages = {
            message.id: message
            for message in self.store.get_messages_by_ids([chunk.message_id for chunk in hydrated_chunks])
        }
        fallback_keys = set(recent_fallback_keys or set())
        deduped_chunks = [
            chunk
            for chunk in hydrated_chunks
            if chunk.id not in request.recent_chunk_ids
            and self._chunk_recent_key(chunk, messages.get(chunk.message_id)) not in fallback_keys
        ]
        if not deduped_chunks:
            return []
        recency_bounds = self._recency_bounds(deduped_chunks)
        results: list[RetrievedChunk] = []
        for chunk in deduped_chunks:
            message = messages.get(chunk.message_id)
            if message is None:
                continue
            scores = candidate_scores.get(chunk.id)
            if scores is None:
                continue
            semantic_score = scores.get("semantic_score", 0.0)
            keyword_score = scores.get("keyword_score", 0.0)
            recency_score = self._recency_score(chunk.created_at, recency_bounds)
            same_session_bonus = self.same_session_bias if session_id and chunk.session_id == session_id else 0.0
            source_kind_weight = SOURCE_KIND_PRIORITIES.get(chunk.source_kind, 0.0)
            final_score = (
                self.scoring.semantic_weight * semantic_score
                + self.scoring.keyword_weight * keyword_score
                + self.scoring.recency_weight * recency_score
                + self.scoring.same_session_weight * same_session_bonus
                + self.scoring.source_kind_weight * source_kind_weight
            )
            results.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    message_id=chunk.message_id,
                    session_id=chunk.session_id,
                    turn_id=chunk.turn_id,
                    role=message.role,
                    source_kind=chunk.source_kind,
                    text=chunk.text,
                    created_at=chunk.created_at,
                    embedding_model=chunk.embedding_model,
                    semantic_score=semantic_score,
                    keyword_score=keyword_score,
                    recency_score=recency_score,
                    same_session_bonus=same_session_bonus,
                    source_kind_weight=source_kind_weight,
                    final_score=final_score,
                    retrieval_sources=tuple(sorted(scores.get("sources", set()))),
                    message=RetrievedMessage(
                        message_id=message.id,
                        session_id=message.session_id,
                        turn_id=message.turn_id,
                        role=message.role,
                        text=message.text,
                        created_at=message.created_at,
                        metadata=dict(message.metadata or {}),
                    ),
                    metadata=dict(chunk.metadata or {}),
                )
            )
        ranked = sorted(
            results,
            key=lambda item: (
                -item.final_score,
                -item.same_session_bonus,
                -item.keyword_score,
                -item.semantic_score,
                -item.recency_score,
                item.chunk_id,
            ),
        )
        if not self.reranker.is_enabled():
            return self._diversify_by_session(ranked, limit=limit)
        try:
            rerank_limit = max(limit, limit * self.max_per_session)
            reranked = self.reranker.rerank(query_text=clean_query, candidates=ranked, limit=rerank_limit)
            return self._diversify_by_session(reranked, limit=limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Retrieval reranker failed; falling back to base ranking: %s", exc)
            return self._diversify_by_session(ranked, limit=limit)

    def _collect_candidates(self, *, request: RetrievalRequest) -> dict[str, dict[str, object]]:
        candidates: dict[str, dict[str, object]] = {}
        if self.hybrid_enable:
            try:
                keyword_hits = self.store.search_chunks_by_text(
                    request.query_text,
                    limit=max(request.limit, self.hybrid_keyword_limit),
                    session_id=None,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Keyword retrieval failed; falling back to vector-only retrieval: %s", exc)
                keyword_hits = []
        else:
            keyword_hits = []
        for chunk in keyword_hits:
            if chunk.id in request.recent_chunk_ids:
                continue
            bucket = candidates.setdefault(chunk.id, {"semantic_score": 0.0, "keyword_score": 0.0, "sources": set()})
            bucket["keyword_score"] = max(float(bucket["keyword_score"]), self._keyword_score(request.query_text, chunk.text))
            bucket["sources"].add("keyword")
        query_embedding = self.embedding_provider.embed_texts([request.query_text])[0]
        candidate_limit = request.limit * self.max_per_session
        vector_limit = max(request.limit, candidate_limit, self.hybrid_vector_limit if self.hybrid_enable else request.limit)
        raw_hits = self.vector_index.query(query_embedding=query_embedding, limit=vector_limit, where=None)
        for hit in raw_hits:
            if hit.chunk_id in request.recent_chunk_ids:
                continue
            bucket = candidates.setdefault(hit.chunk_id, {"semantic_score": 0.0, "keyword_score": 0.0, "sources": set()})
            bucket["semantic_score"] = max(float(bucket["semantic_score"]), self._semantic_score(hit.score))
            bucket["sources"].add("vector")
        return candidates

    @staticmethod
    def _semantic_score(raw_score: float) -> float:
        if raw_score < 0:
            return 0.0
        return 1.0 / (1.0 + float(raw_score))

    @staticmethod
    def _keyword_score(query_text: str, text: str) -> float:
        query_terms = HistoryRetriever._tokenize(query_text)
        if not query_terms:
            return 0.0
        haystack = HistoryRetriever._tokenize(text)
        if not haystack:
            return 0.0
        overlap = sum(1 for term in query_terms if term in haystack)
        return overlap / len(query_terms)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [part.lower() for part in re.findall(r"[A-Za-z0-9_./:-]+", text)]

    @staticmethod
    def _recency_bounds(chunks: list[HistoryChunkRecord]) -> tuple[float, float]:
        created = [chunk.created_at for chunk in chunks]
        return min(created), max(created)

    @staticmethod
    def _recency_score(created_at: float, bounds: tuple[float, float]) -> float:
        minimum, maximum = bounds
        if math.isclose(minimum, maximum):
            return 1.0
        return max(0.0, min(1.0, (created_at - minimum) / (maximum - minimum)))

    @staticmethod
    def _chunk_recent_key(chunk: HistoryChunkRecord, message: HistoryMessageRecord | None) -> str:
        role = message.role if message is not None else str((chunk.metadata or {}).get("role") or chunk.source_kind)
        text = " ".join(chunk.text.split())
        return f"fp:{role}:{text[:200]}"

    def _diversify_by_session(self, ranked: list[RetrievedChunk], *, limit: int) -> list[RetrievedChunk]:
        selected: list[RetrievedChunk] = []
        session_counts: dict[str, int] = {}
        for chunk in ranked:
            count = session_counts.get(chunk.session_id, 0)
            if count >= self.max_per_session:
                continue
            selected.append(chunk)
            session_counts[chunk.session_id] = count + 1
            if len(selected) >= limit:
                return selected
        return selected
