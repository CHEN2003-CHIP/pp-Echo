from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional


SourceKind = Literal["user", "assistant", "tool", "system", "summary"]


@dataclass(frozen=True)
class HistoryChunkInput:
    chunk_index: int
    text: str
    token_estimate: int
    source_kind: SourceKind
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding_model: Optional[str] = None
    embedding_status: str = "pending"
    embedding_dim: Optional[int] = None
    vector_ref: Optional[str] = None


@dataclass(frozen=True)
class HistoryMessageRecord:
    id: str
    session_id: str
    turn_id: str
    message_index: int
    role: str
    text: str
    created_at: float
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class HistoryChunkRecord:
    id: str
    message_id: str
    session_id: str
    turn_id: str
    chunk_index: int
    source_kind: SourceKind
    text: str
    token_estimate: int
    created_at: float
    embedding_model: Optional[str] = None
    embedding_status: str = "pending"
    embedding_dim: Optional[int] = None
    vector_ref: Optional[str] = None
    embedding_error: Optional[str] = None
    indexed_at: Optional[float] = None
    updated_at: float = 0.0
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class IndexedChunk:
    chunk_id: str
    message_id: str
    session_id: str
    turn_id: str
    role: str
    source_kind: SourceKind
    text: str
    created_at: float
    embedding: list[float]
    embedding_model: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorQueryResult:
    chunk_id: str
    score: float
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IndexingSummary:
    scanned: int = 0
    embedded: int = 0
    indexed: int = 0
    failed: int = 0

    def combine(self, other: "IndexingSummary") -> "IndexingSummary":
        return IndexingSummary(
            scanned=self.scanned + other.scanned,
            embedded=self.embedded + other.embedded,
            indexed=self.indexed + other.indexed,
            failed=self.failed + other.failed,
        )
