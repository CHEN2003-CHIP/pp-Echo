from __future__ import annotations

from typing import Optional

from pp_agent.domain import ChatMessage, CompactionState, TextPart, ToolCallPart


class ConversationCompactor:
    """
    对话上下文压缩工具
    功能：保留最新的N条完整消息，将历史消息压缩为精简摘要，解决大模型上下文过长问题
    """
    def __init__(self, keep_recent_messages: int = 8, max_summary_entries: int = 24) -> None:
        self.keep_recent_messages = keep_recent_messages
        self.max_summary_entries = max_summary_entries

    def compact(self, messages: list[ChatMessage], current: CompactionState) -> CompactionState:
        # 1. 如果总消息数 ≤ 保留的最新消息数，无需压缩，直接返回原状态
        if len(messages) <= self.keep_recent_messages:
            return current

        # 2. 计算截断点：超过这个位置的消息【保留完整】，之前的【压缩为摘要】
        cutoff = len(messages) - self.keep_recent_messages
        # 3. 如果截断点 ≤ 已经压缩过的消息数，无需重复压缩
        if cutoff <= current.summarized_message_count:
            return current
        # 4. 提取【新增需要压缩】的消息（上次压缩后 ~ 本次截断点）
        new_messages = messages[current.summarized_message_count:cutoff]
        # 5. 处理原有摘要：去除空行
        summary_lines = [line for line in current.summary.splitlines() if line.strip()]
        #6. 将新增消息转为单行摘要，追加到摘要列表
        summary_lines.extend(self._message_to_line(message) for message in new_messages)
        # 7. 截断摘要：只保留最后 max_summary_entries 条，防止摘要过长
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
            if message.tool_name == "spawn_subagent":
                details = dict(message.metadata.get("tool_details") or {})
                success = bool(not message.metadata.get("is_error"))
                failure_kind = str(details.get("failure_kind") or "").strip()
                summary = str(details.get("summary") or "").strip()
                confidence = str(details.get("confidence") or "").strip()
                inspected = list(details.get("inspected_paths") or [])
                inspected_suffix = ""
                if inspected:
                    inspected_suffix = f" inspected={len(inspected)}"
                status = "ok" if success else "failed"
                failure_suffix = f"/{failure_kind}" if failure_kind else ""
                compact = f"TOOL[spawn_subagent:{status}{failure_suffix}]{inspected_suffix}: {summary[:120]}"
                if confidence:
                    compact += f" (confidence={confidence})"
                return compact
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
