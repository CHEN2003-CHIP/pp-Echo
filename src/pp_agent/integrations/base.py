from __future__ import annotations

from typing import Protocol


class MessagingAdapter(Protocol):
    async def handle_payload(self, payload: dict) -> None:
        ...

