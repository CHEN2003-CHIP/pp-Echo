from __future__ import annotations

import logging
import threading
from typing import Protocol

from pp_agent.memory.index_pipeline import MemoryIndexPipeline


logger = logging.getLogger(__name__)


class AutoIndexScheduler(Protocol):
    def is_enabled(self) -> bool:
        ...

    def submit(self) -> bool:
        ...


class NoopAutoIndexScheduler:
    def is_enabled(self) -> bool:
        return False

    def submit(self) -> bool:
        return False


class AsyncMemoryIndexScheduler:
    def __init__(
        self,
        *,
        pipeline: MemoryIndexPipeline,
        limit: int,
        name: str = "pp-agent-memory-index",
    ) -> None:
        self.pipeline = pipeline
        self.limit = max(1, limit)
        self.name = name
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

    def is_enabled(self) -> bool:
        return True

    def submit(self) -> bool:
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
            self._thread.start()
            return True

    def wait_for_idle(self, timeout: float | None = None) -> bool:
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout=timeout)
        return not thread.is_alive()

    def _run(self) -> None:
        try:
            summary = self.pipeline.index_pending_chunks(limit=self.limit)
            logger.debug(
                "Async memory indexing finished: scanned=%s embedded=%s indexed=%s failed=%s",
                summary.scanned,
                summary.embedded,
                summary.indexed,
                summary.failed,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Async memory indexing failed: %s", exc)
        finally:
            with self._lock:
                self._running = False
