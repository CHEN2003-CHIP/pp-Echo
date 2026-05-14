from __future__ import annotations

import threading


class OperationCancelled(RuntimeError):
    """Raised when a running turn or tool cooperatively observes cancellation."""


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._reason = ""

    def cancel(self, reason: str = "cancel_requested") -> None:
        self._reason = reason
        self._event.set()

    def clear(self) -> None:
        self._reason = ""
        self._event.clear()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason or "cancel_requested"

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise OperationCancelled(self.reason)

