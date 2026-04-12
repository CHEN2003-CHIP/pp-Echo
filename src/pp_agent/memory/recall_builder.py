from __future__ import annotations

import re
from dataclasses import dataclass

from pp_agent.memory.retrieval import RetrievedChunk


SECTION_ORDER = (
    "偏好 / 约束",
    "决策 / 结论",
    "错误 / 修复",
    "路径 / 文件 / 命令",
)


@dataclass(frozen=True)
class RecallSnippetBuilder:
    """把检索出来的历史 chunk，重新排序、分类、压缩，然后拼成一段可塞回 prompt 的 [History Recall] 提示文本。"""
    categorize: bool = True
    prioritize_long_term_preferences: bool = True
    compress_error_stacks: bool = True
    path_weight_boost: float = 1.0

    def build(
        self,
        *,
        query_text: str,
        retrieved_chunks: list[RetrievedChunk],
        max_items: int = 4,
        max_chars: int = 1600,
    ) -> str:
        _ = query_text
        if not retrieved_chunks or max_items <= 0 or max_chars <= 0:
            return ""
        ranked = self._rank_for_snippet(retrieved_chunks)[:max_items]
        return (
            self._build_categorized(ranked, max_chars=max_chars)
            if self.categorize
            else self._build_simple(ranked, max_chars=max_chars)
        )

    def _rank_for_snippet(self, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        return sorted(
            chunks,
            key=lambda chunk: (
                -self._priority_score(chunk),
                -chunk.final_score,
                chunk.chunk_id,
            ),
        )

    def _priority_score(self, chunk: RetrievedChunk) -> float:
        text = chunk.text.lower()
        score = chunk.final_score
        if self.prioritize_long_term_preferences and self._is_long_term_preference(chunk):
            score += 1.5
        if self._looks_like_path_or_command(text):
            score += 1.0 * self.path_weight_boost
        if self._is_error_or_fix(text):
            score += 0.9
        if chunk.source_kind == "user":
            score += 0.5
        return score

    def _build_categorized(self, retrieved_chunks: list[RetrievedChunk], *, max_chars: int) -> str:
        """把检索出来的历史片段按类别分组，去重，按顺序拼成一段不超过 max_chars 的“历史回忆文本”。"""
        grouped: dict[str, list[str]] = {title: [] for title in SECTION_ORDER}
        seen: set[str] = set()
        for chunk in retrieved_chunks:
            summary = self._summarize(chunk)
            normalized = summary.lower()
            if normalized in seen:
                continue
            grouped[self._categorize(chunk)].append(summary)
            seen.add(normalized)

        lines = self._header_lines()
        item_index = 1
        for section in SECTION_ORDER:
            entries = grouped.get(section) or []
            if not entries:
                continue
            working_lines = [*lines]
            section_added = False
            for entry in entries:
                candidate_lines = [*working_lines]
                if not section_added:
                    candidate_lines.append(f"{section}:")
                candidate_lines.append(f"{item_index}. {entry}")
                fitted = self._fit_within_budget(candidate_lines, max_chars=max_chars, item_index=item_index)
                if fitted is None:
                    break
                working_lines = fitted
                section_added = True
                item_index += 1
            lines = working_lines
        return "\n".join(lines) if item_index > 1 else ""

    def _build_simple(self, retrieved_chunks: list[RetrievedChunk], *, max_chars: int) -> str:
        lines = self._header_lines()
        count = 0
        seen: set[str] = set()
        for chunk in retrieved_chunks:
            summary = self._summarize(chunk)
            normalized = summary.lower()
            if normalized in seen:
                continue
            fitted = self._fit_within_budget([*lines, f"{count + 1}. {summary}"], max_chars=max_chars, item_index=count + 1)
            if fitted is None:
                break
            lines = fitted
            seen.add(normalized)
            count += 1
        return "\n".join(lines) if count else ""

    @staticmethod
    def _header_lines() -> list[str]:
        return [
            "[History Recall]",
            "以下是与当前问题相关的历史片段，仅在相关时参考：",
        ]

    def _summarize(self, chunk: RetrievedChunk) -> str:
        text = self._compress_error_text(chunk.text) if self.compress_error_stacks else chunk.text
        text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
        if len(text) > 140:
            text = text[:137] + "..."
        location = f"{chunk.session_id}@{chunk.turn_id}"
        return f"{text} ({location})"

    def _compress_error_text(self, text: str) -> str:
        if not self._is_error_or_fix(text.lower()):
            return text
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return text
        important = []
        for line in lines:
            if line.startswith("Traceback"):
                continue
            if re.search(r"(error|exception|failed|failure|missing|not found|报错|错误|失败|异常|修复)", line, re.IGNORECASE):
                important.append(line)
            elif re.search(r"([a-z]:\\|/|src/|tests/|\.py\b|\.ts\b|\.json\b)", line, re.IGNORECASE):
                important.append(line)
            if len(important) >= 3:
                break
        if not important:
            important = lines[:2]
        return " | ".join(dict.fromkeys(important))

    def _categorize(self, chunk: RetrievedChunk) -> str:
        text = chunk.text.lower()
        if self._is_long_term_preference(chunk):
            return "偏好 / 约束"
        if self._is_error_or_fix(text):
            return "错误 / 修复"
        if self._looks_like_path_or_command(text):
            return "路径 / 文件 / 命令"
        if any(keyword in text for keyword in ("decide", "decided", "decision", "choose", "chosen", "agreed", "结论", "决定", "采用", "选用", "保留")):
            return "决策 / 结论"
        if chunk.source_kind == "user":
            return "偏好 / 约束"
        return "决策 / 结论"

    def _is_long_term_preference(self, chunk: RetrievedChunk) -> bool:
        text = f"{chunk.text} {chunk.message.text}".lower()
        keywords = (
            "prefer",
            "preference",
            "avoid",
            "always",
            "must",
            "keep",
            "constraint",
            "偏好",
            "约束",
            "尽量",
            "不要",
            "必须",
            "保持",
        )
        return any(keyword in text for keyword in keywords) and chunk.source_kind == "user"

    @staticmethod
    def _is_error_or_fix(text: str) -> bool:
        keywords = ("error", "failed", "failure", "traceback", "exception", "fix", "fixed", "missing", "报错", "错误", "失败", "异常", "修复")
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _looks_like_path_or_command(text: str) -> bool:
        return bool(
            re.search(
                r"([a-z]:\\|/|\.py\b|\.ts\b|\.json\b|src/|tests/|pp_agent/|\brun pytest\b|\bgit status\b|\bgit diff\b|\bpython [\w./-]+\b|\bnpm run\b|\buv run\b)",
                text,
            )
        )

    @staticmethod
    def _fit_within_budget(lines: list[str], *, max_chars: int, item_index: int) -> list[str] | None:
        candidate = "\n".join(lines)
        if len(candidate) <= max_chars:
            return lines
        prefix, _, summary = lines[-1].partition(". ")
        if not summary:
            return None
        budget_without_summary = len("\n".join([*lines[:-1], f"{prefix}. "]))
        remaining = max_chars - budget_without_summary
        if remaining <= 3:
            return None
        trimmed = RecallSnippetBuilder._trim_to_budget(summary, remaining)
        if not trimmed:
            return None
        fitted = [*lines[:-1], f"{item_index}. {trimmed}"]
        return fitted if len("\n".join(fitted)) <= max_chars else None

    @staticmethod
    def _trim_to_budget(text: str, limit: int) -> str:
        if limit <= 0:
            return ""
        if len(text) <= limit:
            return text
        if limit <= 3:
            return ""
        return text[: limit - 3].rstrip() + "..."
