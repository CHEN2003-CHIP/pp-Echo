from __future__ import annotations

from typing import Any, Protocol

from pp_agent.memory.types import HistoryChunkInput, HistoryChunkRecord, HistoryMessageRecord


class HistoryStore(Protocol):
    def append_message(
        self,
        *,
        session_id: str,
        turn_id: str,
        message_index: int,
        role: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        ...

    def append_chunks(
        self,
        *,
        session_id: str,
        turn_id: str,
        message_id: str,
        chunks: list[HistoryChunkInput],
    ) -> list[str]:
        ...

    def list_messages_by_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
    ) -> list[HistoryMessageRecord]:
        ...

    def list_pending_chunks(self, *, limit: int) -> list[HistoryChunkRecord]:
        ...

    def list_chunks_for_session(
        self,
        *,
        session_id: str,
        limit: int | None = None,
        statuses: list[str] | None = None,
    ) -> list[HistoryChunkRecord]:
        ...

    def get_chunks_by_ids(self, chunk_ids: list[str]) -> list[HistoryChunkRecord]:
        ...

    def get_messages_by_ids(self, message_ids: list[str]) -> list[HistoryMessageRecord]:
        ...

    def search_chunks_by_text(
        self,
        query_text: str,
        *,
        limit: int,
        session_id: str | None = None,
    ) -> list[HistoryChunkRecord]:
        ...

    def mark_chunk_embedded(
        self,
        *,
        chunk_id: str,
        embedding_model: str,
        embedding_dim: int,
    ) -> None:
        ...

    def mark_chunk_indexed(
        self,
        *,
        chunk_id: str,
        vector_ref: str | None = None,
    ) -> None:
        ...

    def mark_chunk_failed(
        self,
        *,
        chunk_id: str,
        error: str,
    ) -> None:
        ...
