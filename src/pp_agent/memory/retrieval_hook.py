from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.memory.classification import classify_memory_text
from pp_agent.memory.recall_builder import RecallSnippetBuilder
from pp_agent.memory.retrieval import HistoryRetriever, RetrievedChunk
from pp_agent.runtime.state import AgentState


logger = logging.getLogger(__name__)

RECALL_METADATA_KEY = "memory_recall"


@dataclass
class MemoryRetrievalHook:
    """
    记忆检索钩子类：用于在AI对话上下文处理中自动检索历史记忆、生成记忆片段
    并将其插入到对话消息中，增强AI的上下文记忆能力
    核心功能：检索历史对话记忆 → 去重 → 构建提示片段 → 插入系统消息
    """
    retriever: HistoryRetriever | None = None
    builder: RecallSnippetBuilder | None = None
    session_id: str | None = None
    enabled: bool = False
    retrieval_limit: int = 6
    retrieval_max_snippets: int = 4
    retrieval_max_chars: int = 1600
    query_max_chars: int = 1200
    recent_dedup_enable: bool = True
    recent_dedup_use_chunk_metadata: bool = True
    retrieval_version: str = "v2_rerank_metadata"
    _recent_recalled_chunk_ids: set[str] = field(default_factory=set, init=False, repr=False)
    _recent_fallback_keys: set[str] = field(default_factory=set, init=False, repr=False)

    def transform_context(self, state: AgentState | None, messages: list[ChatMessage]) -> list[ChatMessage]:
        if not self.enabled or self.retriever is None or self.builder is None:
            return messages
        query_text = self._build_query_text(state, messages)
        if not query_text:
            return messages
        try:
            recent_chunk_ids, recent_fallback_keys = self._recent_chunk_ids(state, messages)
            retrieved = self.retriever.retrieve(
                query_text=query_text,
                session_id=self.session_id,
                recent_chunk_ids=recent_chunk_ids,
                limit=self.retrieval_limit,
                recent_fallback_keys=recent_fallback_keys,
            )
            snippet = self.builder.build(
                query_text=query_text,
                retrieved_chunks=retrieved,
                max_items=self.retrieval_max_snippets,
                max_chars=self.retrieval_max_chars,
            )
            if not snippet:
                return messages
            recall_chunks = retrieved[: self.retrieval_max_snippets]
            self._remember_recent_chunks(recall_chunks)
            metadata = self._recall_metadata(
                recall_chunks,
                snippet=snippet,
                recent_chunk_ids=recent_chunk_ids,
                recent_fallback_keys=recent_fallback_keys,
            )
            if state is not None:
                state.memory_context[RECALL_METADATA_KEY] = metadata
            recall_message = ChatMessage(
                role="system",
                content=[TextPart(text=snippet)],
                metadata={RECALL_METADATA_KEY: metadata},
                timestamp=0.0,
            )
            insert_at = self._insertion_index(messages)
            return [*messages[:insert_at], recall_message, *messages[insert_at:]]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Memory retrieval hook failed and was skipped: %s", exc)
            return messages

    @staticmethod
    def _latest_user_text(messages: list[ChatMessage]) -> str:
        for message in reversed(messages):
            if message.role != "user":
                continue
            text = " ".join(part.text.strip() for part in message.content if isinstance(part, TextPart) and part.text.strip()).strip()
            if text:
                return text
        return ""

    def _build_query_text(self, state: AgentState | None, messages: list[ChatMessage]) -> str:
        parts: list[str] = []
        latest_user = self._latest_user_text(messages)
        if latest_user:
            parts.append(f"Current user request: {latest_user}")
        goal_summary = self._current_work_summary(state)
        if goal_summary:
            parts.append(f"Current session summary: {goal_summary}")
        hints = self._recent_tool_path_hints(messages)
        if hints:
            parts.append("Recent tool/path hints: " + " | ".join(hints))
        return self._trim_query("\n".join(parts), max_chars=self.query_max_chars)

    @staticmethod
    def _current_work_summary(state: AgentState | None) -> str:
        if state is None:
            return ""
        summary = (state.compaction.summary or "").strip()
        if not summary:
            return ""
        lines = [line.strip() for line in summary.splitlines() if line.strip()]
        interesting = [
            line
            for line in lines
            if any(label in line.lower() for label in ("current work", "pending work", "key files", "tools mentioned"))
        ]
        return " ".join(interesting[-4:] or lines[-3:])

    @staticmethod
    def _recent_tool_path_hints(messages: list[ChatMessage], *, limit: int = 4) -> list[str]:
        hints: list[str] = []
        for message in reversed(messages):
            if message.role not in {"tool", "assistant"}:
                continue
            text = " ".join(
                part.text.strip()
                for part in message.content
                if isinstance(part, TextPart) and part.text.strip()
            )
            compact = " ".join(text.split())
            if not compact:
                continue
            if any(token in compact.lower() for token in ("src/", "tests/", ".py", ".json", "pytest", "git ", "error", "traceback")):
                hints.append(compact[:180])
            if len(hints) >= limit:
                break
        return list(reversed(hints))

    @staticmethod
    def _trim_query(text: str, *, max_chars: int) -> str:
        compact = text.strip()
        if len(compact) <= max_chars:
            return compact
        return compact[-max_chars:].lstrip()

    def _recent_chunk_ids(self, state: AgentState | None, messages: list[ChatMessage]) -> tuple[set[str], set[str]]:
        if not self.recent_dedup_enable:
            return set(), set()
        explicit_chunk_ids: set[str] = set()
        fallback_keys = set(self._recent_fallback_keys)
        if self.recent_dedup_use_chunk_metadata:
            explicit_chunk_ids.update(self._chunk_ids_from_messages(messages))
            if state is not None:
                explicit_chunk_ids.update(self._chunk_ids_from_state(state))
        explicit_chunk_ids.update(self._recent_recalled_chunk_ids)
        for message in messages:
            key = self._message_fallback_key(message)
            if key is not None:
                fallback_keys.add(key)
        return explicit_chunk_ids, fallback_keys

    def _remember_recent_chunks(self, chunks: list[RetrievedChunk]) -> None:
        if not self.recent_dedup_enable:
            return
        for chunk in chunks:
            self._recent_recalled_chunk_ids.add(chunk.chunk_id)
            self._recent_fallback_keys.add(self._chunk_fallback_key(chunk))

    def _recall_metadata(
        self,
        chunks: list[RetrievedChunk],
        *,
        snippet: str,
        recent_chunk_ids: set[str],
        recent_fallback_keys: set[str],
    ) -> dict[str, object]:
        return {
            "recalled_chunk_ids": [chunk.chunk_id for chunk in chunks],
            "source_session_ids": sorted({chunk.session_id for chunk in chunks}),
            "source_turn_ids": sorted({chunk.turn_id for chunk in chunks}),
            "categories": [self._category_for(chunk) for chunk in chunks],
            "final_scores": [round(float(chunk.final_score), 6) for chunk in chunks],
            "retrieval_sources": [list(chunk.retrieval_sources) for chunk in chunks],
            "snippet_chars": len(snippet),
            "recent_deduped_chunk_ids": sorted(recent_chunk_ids),
            "recent_deduped_fingerprint_count": len(recent_fallback_keys),
            "retrieval_version": self.retrieval_version,
        }

    @staticmethod
    def _category_for(chunk: RetrievedChunk) -> str:
        metadata_category = str((chunk.metadata or {}).get("memory_category") or "").strip()
        if metadata_category:
            return metadata_category
        return classify_memory_text(chunk.text, role=chunk.role, source_kind=chunk.source_kind)

    @staticmethod
    def _chunk_ids_from_messages(messages: list[ChatMessage]) -> set[str]:
        recovered: set[str] = set()
        for message in messages:
            payload = (message.metadata or {}).get(RECALL_METADATA_KEY)
            if isinstance(payload, dict):
                for chunk_id in payload.get("recalled_chunk_ids", []):
                    if isinstance(chunk_id, str):
                        recovered.add(chunk_id)
        return recovered

    @staticmethod
    def _chunk_ids_from_state(state: AgentState) -> set[str]:
        payload = state.memory_context.get(RECALL_METADATA_KEY)
        if not isinstance(payload, dict):
            return set()
        return {chunk_id for chunk_id in payload.get("recalled_chunk_ids", []) if isinstance(chunk_id, str)}

    @staticmethod
    def _message_fallback_key(message: ChatMessage) -> str | None:
        if message.role not in {"user", "assistant", "tool", "system"}:
            return None
        text = " ".join(part.text.strip() for part in message.content if isinstance(part, TextPart) and part.text.strip()).strip()
        if not text:
            return None
        return f"fp:{message.role}:{' '.join(text.split())[:200]}"

    @staticmethod
    def _chunk_fallback_key(chunk: RetrievedChunk) -> str:
        text = " ".join(chunk.text.split())
        return f"fp:{chunk.role}:{text[:200]}"

    @staticmethod
    def _insertion_index(messages: list[ChatMessage]) -> int:
        index = 0
        while index < len(messages) and messages[index].role == "system":
            index += 1
        return index
