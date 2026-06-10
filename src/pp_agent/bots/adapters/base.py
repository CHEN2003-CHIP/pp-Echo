from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseBotAdapter(ABC):
    @abstractmethod
    def start(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> dict[str, Any]:
        raise NotImplementedError

    def restart(self) -> dict[str, Any]:
        self.stop()
        return self.start()

    @abstractmethod
    def health(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def handle_incoming_event(self, raw_event: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def send_message(self, target: dict[str, Any], text: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError
