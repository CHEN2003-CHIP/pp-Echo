from __future__ import annotations

import json
import math
from typing import Any, Optional

from pp_agent.domain import ChatMessage, TextPart, ToolCallPart


def estimate_text_tokens(text: str) -> int:
    cleaned = text.strip()
    if not cleaned:
        return 0
    return max(1, math.ceil(len(cleaned) / 4))


def estimate_messages(messages: list[ChatMessage], tools: Optional[list[dict[str, Any]]] = None) -> int:
    total = 0
    for message in messages:
        total += estimate_text_tokens(message.role)
        for part in message.content:
            if isinstance(part, TextPart):
                total += estimate_text_tokens(part.text)
            elif isinstance(part, ToolCallPart):
                total += estimate_text_tokens(part.name)
                total += estimate_text_tokens(json.dumps(part.arguments, ensure_ascii=False, sort_keys=True))
        if message.tool_name:
            total += estimate_text_tokens(message.tool_name)
    if tools:
        total += estimate_tools(tools)
    return total


def estimate_tools(tools: list[dict[str, Any]]) -> int:
    rendered = json.dumps(tools, ensure_ascii=False, sort_keys=True)
    return estimate_text_tokens(rendered)
