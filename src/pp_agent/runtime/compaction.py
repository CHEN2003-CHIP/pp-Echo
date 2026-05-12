from __future__ import annotations

import re
from typing import Optional

from pp_agent.domain import ChatMessage, CompactionState, TextPart, ToolCallPart


class ConversationCompactor:
    """
    Conversation context compaction with a preserved recent tail.

    The compactor keeps the public CompactionState shape unchanged while producing
    structured summaries that preserve current work, pending work, key files, and
    tool references.
    """

    def __init__(
        self,
        keep_recent_messages: int = 8,
        max_summary_entries: int = 24,
        max_summary_chars: int = 4000,
    ) -> None:
        self.keep_recent_messages = keep_recent_messages
        self.max_summary_entries = max_summary_entries
        self.max_summary_chars = max_summary_chars

    def compact(self, messages: list[ChatMessage], current: CompactionState) -> CompactionState:
        if len(messages) <= self.keep_recent_messages:
            return current

        raw_cutoff = len(messages) - self.keep_recent_messages
        cutoff = self._safe_cutoff(messages, raw_cutoff, current.summarized_message_count)
        if cutoff <= current.summarized_message_count:
            return current

        new_messages = messages[current.summarized_message_count:cutoff]
        preserved_tail = messages[cutoff:]
        summary = self._build_summary(
            previous_summary=current.summary,
            newly_compacted=new_messages,
            preserved_tail=preserved_tail,
        )
        return CompactionState(
            summary=summary,
            summarized_message_count=cutoff,
        )

    def summary_message(self, state: CompactionState) -> Optional[ChatMessage]:
        if not state.summary:
            return None
        return ChatMessage(
            role="system",
            content=[TextPart(text="Conversation summary:\n" + state.summary)],
            timestamp=0.0,
        )

    def _build_summary(
        self,
        *,
        previous_summary: str,
        newly_compacted: list[ChatMessage],
        preserved_tail: list[ChatMessage],
    ) -> str:
        previous_lines = self._clean_summary_lines(previous_summary)
        new_lines = self._dedupe_lines([self._message_to_line(message) for message in newly_compacted])
        if len(new_lines) > self.max_summary_entries:
            new_lines = new_lines[-self.max_summary_entries :]

        all_messages = [*newly_compacted, *preserved_tail]
        sections: list[tuple[str, list[str]]] = [
            ("Previously compacted context", previous_lines[-8:]),
            ("Newly compacted context", new_lines),
            ("Current work", self._infer_current_work(preserved_tail or newly_compacted)),
            ("Pending work", self._infer_pending_work(all_messages)),
            ("Key files referenced", self._key_files(all_messages)),
            ("Tools mentioned", self._tools_mentioned(all_messages)),
        ]

        lines: list[str] = []
        for title, entries in sections:
            lines.append(f"{title}:")
            if entries:
                lines.extend(f"- {entry}" for entry in entries)
            else:
                lines.append("- None")
        return self._compress_to_budget(lines)

    def _compress_to_budget(self, lines: list[str]) -> str:
        deduped = self._dedupe_lines(lines)
        text = "\n".join(deduped)
        if len(text) <= self.max_summary_chars:
            return text

        protected_prefixes = (
            "Previously compacted context:",
            "Newly compacted context:",
            "Current work:",
            "Pending work:",
            "Key files referenced:",
            "Tools mentioned:",
        )
        protected = [line for line in deduped if line in protected_prefixes]
        remainder = [line for line in deduped if line not in protected_prefixes]
        kept: list[str] = []
        for line in remainder:
            candidate = "\n".join([*protected, *kept, line])
            if len(candidate) > self.max_summary_chars:
                break
            kept.append(line)
        return "\n".join([*protected, *kept])[: self.max_summary_chars].rstrip()

    @staticmethod
    def _safe_cutoff(messages: list[ChatMessage], cutoff: int, minimum: int) -> int:
        safe = cutoff
        while safe > minimum and safe < len(messages) and messages[safe].role == "tool":
            safe -= 1
        if safe > minimum and safe < len(messages) and ConversationCompactor._has_tool_call(messages[safe - 1]) and messages[safe].role == "tool":
            safe -= 1
        return safe

    @staticmethod
    def _has_tool_call(message: ChatMessage) -> bool:
        return any(isinstance(part, ToolCallPart) for part in message.content)

    @staticmethod
    def _clean_summary_lines(summary: str) -> list[str]:
        lines = []
        for line in summary.splitlines():
            clean = line.strip()
            if not clean or clean.endswith(":"):
                continue
            clean = clean[2:] if clean.startswith("- ") else clean
            if clean and clean != "None":
                lines.append(clean)
        return ConversationCompactor._dedupe_lines(lines)

    @staticmethod
    def _dedupe_lines(lines: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for line in lines:
            clean = " ".join(line.replace("\r", " ").split())
            if not clean:
                continue
            if clean.lower() in seen:
                continue
            seen.add(clean.lower())
            result.append(clean)
        return result

    @staticmethod
    def _infer_current_work(messages: list[ChatMessage]) -> list[str]:
        for message in reversed(messages):
            if message.role not in {"user", "assistant"}:
                continue
            text = ConversationCompactor._message_text(message)
            if text:
                return [ConversationCompactor._truncate(text, 180)]
        return []

    @staticmethod
    def _infer_pending_work(messages: list[ChatMessage]) -> list[str]:
        pending: list[str] = []
        for message in reversed(messages):
            text = ConversationCompactor._message_text(message)
            lowered = text.lower()
            if any(token in lowered for token in ("todo", "next", "pending", "follow up", "remaining", "待办", "下一步", "剩余")):
                pending.append(ConversationCompactor._truncate(text, 180))
            if len(pending) >= 3:
                break
        return list(reversed(pending))

    @staticmethod
    def _key_files(messages: list[ChatMessage]) -> list[str]:
        candidates: set[str] = set()
        for message in messages:
            text = ConversationCompactor._message_text(message, include_tool_calls=True)
            for match in re.findall(r"[\w./\\:-]+\.(?:py|ts|tsx|js|json|md|toml|yaml|yml|rs)", text):
                candidates.add(match.strip("`'\".,;()[]{}"))
        return sorted(candidates)[:8]

    @staticmethod
    def _tools_mentioned(messages: list[ChatMessage]) -> list[str]:
        tools: set[str] = set()
        for message in messages:
            if message.tool_name:
                tools.add(message.tool_name)
            for part in message.content:
                if isinstance(part, ToolCallPart):
                    tools.add(part.name)
        return sorted(tools)

    @staticmethod
    def _message_text(message: ChatMessage, *, include_tool_calls: bool = False) -> str:
        chunks: list[str] = []
        for part in message.content:
            if isinstance(part, TextPart):
                chunks.append(part.text)
            elif include_tool_calls and isinstance(part, ToolCallPart):
                chunks.append(f"{part.name} {part.arguments}")
        return " ".join(" ".join(chunks).replace("\n", " ").split()).strip()

    @staticmethod
    def _message_to_line(message: ChatMessage) -> str:
        role = message.role.upper()
        if message.role == "tool":
            if message.tool_name == "spawn_subagent":
                details = dict(message.metadata.get("tool_details") or {})
                success = bool(not message.metadata.get("is_error"))
                failure_kind = str(details.get("failure_kind") or "").strip()
                summary = str(details.get("summary") or "").strip()
                confidence = str(details.get("confidence") or "").strip()
                inspected = list(details.get("inspected_paths") or [])
                inspected_suffix = f" inspected={len(inspected)}" if inspected else ""
                status = "ok" if success else "failed"
                failure_suffix = f"/{failure_kind}" if failure_kind else ""
                compact = f"TOOL[spawn_subagent:{status}{failure_suffix}]{inspected_suffix}: {summary[:120]}"
                if confidence:
                    compact += f" (confidence={confidence})"
                return compact
            text = ConversationCompactor._message_text(message)
            return f"TOOL[{message.tool_name or 'unknown'}]: {ConversationCompactor._compress_error_stack(text)[:200]}"

        chunks: list[str] = []
        for part in message.content:
            if isinstance(part, TextPart):
                chunks.append(part.text)
            elif isinstance(part, ToolCallPart):
                chunks.append(f"TOOL_CALL {part.name} {part.arguments}")
        text = " ".join(chunks).replace("\n", " ").strip()
        return f"{role}: {ConversationCompactor._compress_error_stack(text)[:200]}"

    @staticmethod
    def _compress_error_stack(text: str) -> str:
        if "traceback" not in text.lower() and "exception" not in text.lower() and "error" not in text.lower():
            return text
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) <= 3:
            return text
        important = [
            line
            for line in lines
            if re.search(r"(error|exception|failed|failure|src/|tests/|\.py\b)", line, re.IGNORECASE)
        ]
        return " | ".join((important or lines[:3])[:3])

    @staticmethod
    def _truncate(content: str, max_chars: int) -> str:
        if len(content) <= max_chars:
            return content
        return content[: max_chars - 3].rstrip() + "..."
