from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from typing import Any, Protocol

from pp_agent.observability.schema import SpanType, TraceStatus


class SpanHandle(Protocol):
    """
    业务模块操作当前 span 的最小接口。

    SpanHandle 隐藏 TraceRecorder 的具体实现，使 Runtime、ToolRegistry、Memory
    等模块只依赖抽象观测接口。调用方可以在 with obs.span(...) as span 中补充
    输入、输出、属性或错误信息，测试时也可以替换为 no-op 实现。
    """

    def set_input(self, data: dict[str, Any]) -> None: ...
    def set_output(self, data: dict[str, Any]) -> None: ...
    def set_attribute(self, key: str, value: Any) -> None: ...
    def set_error(self, exc: BaseException | str, *, kind: str | None = None) -> None: ...


class ObservabilityHooks(Protocol):
    """
    pp-Echo 结构化 Trace 的抽象入口。

    业务模块通过 ObservabilityHooks 创建 run、span 和 event，而不直接知道 JSONL、
    Web UI 或第三方 exporter。默认实现可以是 NoopObservabilityHooks，后续也可
    替换为 TraceRecorder、OpenTelemetry 或其它观测后端。
    """

    def start_run(
        self,
        *,
        session_id: str | None = None,
        turn_id: str | int | None = None,
        user_goal_preview: str = "",
        provider: str | None = None,
        model: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> str: ...

    def end_run(
        self,
        *,
        status: TraceStatus = "ok",
        attributes: dict[str, Any] | None = None,
        error: BaseException | str | None = None,
    ) -> None: ...

    def span(
        self,
        name: str,
        span_type: SpanType,
        *,
        attributes: dict[str, Any] | None = None,
        input: dict[str, Any] | None = None,
    ) -> AbstractContextManager[SpanHandle]: ...

    def event(
        self,
        name: str,
        *,
        attributes: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None: ...
