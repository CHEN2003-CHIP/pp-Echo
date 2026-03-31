from __future__ import annotations

from typing import Optional

from agent_core.types import ChatMessage, CompactionState, TextPart, ToolCallPart


class ConversationCompactor:
    def __init__(self, keep_recent_messages: int = 8, max_summary_entries: int = 24) -> None:
        self.keep_recent_messages = keep_recent_messages
        self.max_summary_entries = max_summary_entries

    def compact(self, messages: list[ChatMessage], current: CompactionState) -> CompactionState:
        if len(messages) <= self.keep_recent_messages:
            return current

        cutoff = len(messages) - self.keep_recent_messages
        if cutoff <= current.summarized_message_count:
            return current

        new_messages = messages[current.summarized_message_count:cutoff]
        summary_lines = [line for line in current.summary.splitlines() if line.strip()]
        summary_lines.extend(self._message_to_line(message) for message in new_messages)
        trimmed_lines = summary_lines[-self.max_summary_entries :]
        return CompactionState(
            summary="\n".join(trimmed_lines),
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

    @staticmethod
    def _message_to_line(message: ChatMessage) -> str:
        role = message.role.upper()
        if message.role == "tool":
            text = " ".join(part.text for part in message.content if isinstance(part, TextPart))
            return f"TOOL[{message.tool_name or 'unknown'}]: {text[:200]}"

        chunks: list[str] = []
        for part in message.content:
            if isinstance(part, TextPart):
                chunks.append(part.text)
            elif isinstance(part, ToolCallPart):
                chunks.append(f"TOOL_CALL {part.name} {part.arguments}")
        text = " ".join(chunks).replace("\n", " ").strip()
        return f"{role}: {text[:200]}"