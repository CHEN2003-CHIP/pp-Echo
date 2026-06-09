from __future__ import annotations

import time
from pathlib import Path

from pp_agent.attachments.service import AttachmentService
from pp_agent.domain import ChatMessage, TextPart
from pp_agent.runtime.state import AgentState


class AttachmentContextHook:
    """向模型上下文注入附件清单和摘要，不注入完整附件内容。"""

    def __init__(self, workspace: Path, session_id: str) -> None:
        self.workspace = workspace.resolve()
        self.session_id = session_id

    def transform_context(self, state: AgentState, messages: list[ChatMessage]) -> list[ChatMessage]:
        summary = AttachmentService(self.workspace).context_summary(self.session_id)
        if not summary:
            return messages
        context = ChatMessage(role="system", content=[TextPart(text=summary)], timestamp=time.time())
        return [messages[0], context, *messages[1:]] if messages and messages[0].role == "system" else [context, *messages]
