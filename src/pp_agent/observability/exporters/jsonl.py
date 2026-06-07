from __future__ import annotations

from pp_agent.observability.schema import TraceDetail
from pp_agent.observability.store import TraceStore


class JsonlTraceExporter:
    """
    将 TraceDetail 写回本地 JSONL store 的导出器。

    这是一个轻量适配层，主要用于统一 exporter 接口。实际运行时 TraceRecorder
    已经逐行写入 store，因此该导出器通常只需要刷新 index summary。
    """

    def __init__(self, store: TraceStore) -> None:
        self.store = store

    def export_run(self, detail: TraceDetail) -> None:
        if detail.summary is not None:
            self.store.append_index(detail.summary)
