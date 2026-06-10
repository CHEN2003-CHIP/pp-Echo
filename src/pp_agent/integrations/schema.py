from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IncomingMessage:
    event_id: str
    event_type: str
    conversation_type: str
    conversation_key: str
    content: str
    raw: dict[str, Any]

