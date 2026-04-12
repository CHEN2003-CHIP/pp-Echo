from __future__ import annotations

import logging
from typing import Any, Protocol

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.memory.indexer import HistoryIndexer
from pp_agent.memory.store import HistoryStore


logger = logging.getLogger(__name__)


class MemoryProvider(Protocol):
    def is_enabled(self) -> bool:
        ...

    def on_turn_persisted(
        self,
        *,
        session_id: str,
        turn_id: str,
        new_messages: list[ChatMessage],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        ...


class NoopMemoryProvider:
    def is_enabled(self) -> bool:
        return False

    def on_turn_persisted(
        self,
        *,
        session_id: str,
        turn_id: str,
        new_messages: list[ChatMessage],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        return None


class SQLiteMemoryProvider:
    """把一轮对话的新消息落到 memory store 里，并顺手把每条消息切成 chunk，供后面检索/索引用"""
    def __init__(self, *, store: HistoryStore, indexer: HistoryIndexer) -> None:
        self.store = store
        self.indexer = indexer

    def is_enabled(self) -> bool:
        return True

    def on_turn_persisted(
        self,
        *,
        session_id: str,
        turn_id: str,
        new_messages: list[ChatMessage],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        message_count = 0
        chunk_count = 0
        for message_index, message in enumerate(new_messages):
            text = self._message_text(message)
            if not text:
                continue
            message_metadata = {
                **(metadata or {}),
                "role": message.role,
                "tool_call_id": message.tool_call_id,
                "tool_name": message.tool_name,
                "timestamp": message.timestamp,
            }
            message_id = self.store.append_message(
                session_id=session_id,
                turn_id=turn_id,
                message_index=message_index,
                role=message.role,
                text=text,
                metadata=message_metadata,
            )
            chunks = self.indexer.chunk_message(text=text, role=message.role, metadata=message_metadata)
            self.store.append_chunks(
                session_id=session_id,
                turn_id=turn_id,
                message_id=message_id,
                chunks=chunks,
            )
            message_count += 1
            chunk_count += len(chunks)
        logger.debug(
            "Memory dual write appended %s messages and %s chunks for session=%s turn=%s",
            message_count,
            chunk_count,
            session_id,
            turn_id,
        )

    @staticmethod
    def _message_text(message: ChatMessage) -> str:
        parts: list[str] = []
        for part in message.content:
            if isinstance(part, TextPart):
                value = part.text.strip()
                if value:
                    parts.append(value)
        return " ".join(parts).strip()
