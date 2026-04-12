import logging
import threading
import time

from pp_agent.memory.auto_index import AsyncMemoryIndexScheduler
from pp_agent.memory.types import IndexingSummary


class _RecordingPipeline:
    def __init__(self, *, delay: float = 0.0, should_fail: bool = False) -> None:
        self.delay = delay
        self.should_fail = should_fail
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()

    def index_pending_chunks(self, *, limit: int = 100) -> IndexingSummary:
        self.calls += 1
        self.started.set()
        if self.delay:
            self.release.wait(timeout=self.delay)
        if self.should_fail:
            raise RuntimeError("index failed")
        return IndexingSummary(scanned=limit, embedded=1, indexed=1, failed=0)


def test_async_auto_index_scheduler_is_single_flight() -> None:
    pipeline = _RecordingPipeline(delay=0.3)
    scheduler = AsyncMemoryIndexScheduler(pipeline=pipeline, limit=5)

    first = scheduler.submit()
    assert first is True
    assert pipeline.started.wait(timeout=1.0) is True

    second = scheduler.submit()
    assert second is False

    pipeline.release.set()
    assert scheduler.wait_for_idle(timeout=1.0) is True
    assert pipeline.calls == 1


def test_async_auto_index_scheduler_logs_failures(caplog) -> None:
    pipeline = _RecordingPipeline(should_fail=True)
    scheduler = AsyncMemoryIndexScheduler(pipeline=pipeline, limit=5)

    with caplog.at_level(logging.WARNING):
        assert scheduler.submit() is True
        assert scheduler.wait_for_idle(timeout=1.0) is True

    assert pipeline.calls == 1
    assert "Async memory indexing failed" in caplog.text
