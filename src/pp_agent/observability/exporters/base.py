from __future__ import annotations

from typing import Protocol

from pp_agent.observability.schema import TraceDetail


class TraceExporter(Protocol):
    """
    Trace 导出器抽象接口。

    当前版本主要使用本地 JSONL。该接口预留给 OpenTelemetry、Opik、Langfuse 等
    平台接入，避免未来把第三方依赖耦合进 Runtime 或 Web API。
    """

    def export_run(self, detail: TraceDetail) -> None: ...


class NoopTraceExporter:
    """
    无副作用导出器。

    用于未配置外部平台或测试场景，调用 export_run 不会执行任何 I/O。
    """

    def export_run(self, detail: TraceDetail) -> None:
        _ = detail
