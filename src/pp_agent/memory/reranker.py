from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import TYPE_CHECKING, Protocol

from pp_agent.memory.classification import classify_memory_text, is_error_or_fix, looks_like_path_or_command

if TYPE_CHECKING:
    from pp_agent.memory.retrieval import RetrievedChunk


logger = logging.getLogger(__name__)


class Reranker(Protocol):
    def is_enabled(self) -> bool:
        ...

    def rerank(
        self,
        *,
        query_text: str,
        candidates: list[RetrievedChunk],
        limit: int,
    ) -> list[RetrievedChunk]:
        ...


class NoopReranker:
    def is_enabled(self) -> bool:
        return False

    def rerank(
        self,
        *,
        query_text: str,
        candidates: list[RetrievedChunk],
        limit: int,
    ) -> list[RetrievedChunk]:
        _ = query_text
        return candidates[:limit]


class LightweightReranker:
    def __init__(
        self,
        *,
        enabled: bool = True,
        max_candidates: int = 8,
        path_weight_boost: float = 1.0,
        semantic_weight: float = 0.55,
        keyword_weight: float = 0.15,
        same_session_weight: float = 0.10,
        recency_weight: float = 0.05,
        source_kind_weight: float = 0.05,
        file_path_weight: float = 0.04,
        error_stack_weight: float = 0.03,
        long_term_preference_weight: float = 0.02,
        command_or_path_bonus_weight: float = 0.01,
    ) -> None:
        self.enabled = enabled
        self.max_candidates = max(1, max_candidates)
        self.path_weight_boost = path_weight_boost
        self.semantic_weight = semantic_weight
        self.keyword_weight = keyword_weight
        self.same_session_weight = same_session_weight
        self.recency_weight = recency_weight
        self.source_kind_weight = source_kind_weight
        self.file_path_weight = file_path_weight
        self.error_stack_weight = error_stack_weight
        self.long_term_preference_weight = long_term_preference_weight
        self.command_or_path_bonus_weight = command_or_path_bonus_weight

    def is_enabled(self) -> bool:
        return self.enabled

    def rerank(
        self,
        *,
        query_text: str,
        candidates: list[RetrievedChunk],
        limit: int,
    ) -> list[RetrievedChunk]:
        if not self.enabled or not candidates:
            return candidates[:limit]
        target_limit = min(limit, self.max_candidates)
        reranked: list[RetrievedChunk] = []
        for candidate in candidates:
            details = self._details_for(query_text=query_text, candidate=candidate)
            final_score = (
                self.semantic_weight * candidate.semantic_score
                + self.keyword_weight * candidate.keyword_score
                + self.same_session_weight * candidate.same_session_bonus
                + self.recency_weight * candidate.recency_score
                + self.source_kind_weight * candidate.source_kind_weight
                + self.file_path_weight * details["file_path_weight"]
                + self.error_stack_weight * details["error_stack_weight"]
                + self.long_term_preference_weight * details["long_term_preference_weight"]
                + self.command_or_path_bonus_weight * details["command_or_path_bonus"]
            )
            reranked.append(replace(candidate, final_score=final_score, rerank_details=details))
        return sorted(
            reranked,
            key=lambda item: (
                -item.final_score,
                -(item.rerank_details or {}).get("long_term_preference_weight", 0.0),
                -(item.rerank_details or {}).get("file_path_weight", 0.0),
                -(item.rerank_details or {}).get("error_stack_weight", 0.0),
                -item.keyword_score,
                -item.semantic_score,
                item.chunk_id,
            ),
        )[:target_limit]

    def _details_for(self, *, query_text: str, candidate: RetrievedChunk) -> dict[str, float]:
        text = candidate.text
        normalized = text.lower()
        query = query_text.lower()
        file_path_weight = self._file_path_weight(normalized) * self.path_weight_boost
        error_stack_weight = self._error_stack_weight(normalized)
        long_term_preference_weight = self._long_term_preference_weight(normalized, candidate)
        command_or_path_bonus = self._command_or_path_bonus(query, normalized)
        return {
            "file_path_weight": min(1.0, file_path_weight),
            "error_stack_weight": error_stack_weight,
            "long_term_preference_weight": long_term_preference_weight,
            "command_or_path_bonus": command_or_path_bonus,
        }

    @staticmethod
    def _file_path_weight(text: str) -> float:
        return 1.0 if looks_like_path_or_command(text) else 0.0

    @staticmethod
    def _error_stack_weight(text: str) -> float:
        return 1.0 if is_error_or_fix(text) or "stack" in text else 0.0

    @staticmethod
    def _long_term_preference_weight(text: str, candidate: RetrievedChunk) -> float:
        metadata_category = str((candidate.metadata or {}).get("memory_category") or "").strip()
        category = metadata_category or classify_memory_text(
            f"{text} {candidate.message.text}",
            role=candidate.role,
            source_kind=candidate.source_kind,
        )
        if category == "preference" and candidate.source_kind == "user":
            return 1.0
        return 0.6 if category == "preference" else 0.0

    @staticmethod
    def _command_or_path_bonus(query_text: str, text: str) -> float:
        query_mentions_path = any(
            token in query_text
            for token in ("path", "file", "command", "error", "pytest", "traceback", "路径", "文件", "命令", "错误")
        )
        text_has_command = bool(
            re.search(r"(\brun pytest\b|\bpytest\b|\bgit status\b|\bgit diff\b|\bpython [\w./:-]+\b|\bnpm run\b|\buv run\b)", text)
        )
        return 1.0 if query_mentions_path and text_has_command else 0.5 if text_has_command else 0.0
