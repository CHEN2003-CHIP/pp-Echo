from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any

from pp_agent.observability.schema import SpanType, TraceStatus


class _NoopSpanHandle:
    """
    无副作用 span 句柄。

    该对象用于 trace 关闭或测试场景，所有方法都接受调用但不记录任何数据，
    从而保证业务控制流与未接入 observability 时完全一致。
    """

    def set_input(self, data: dict[str, Any]) -> None:
        _ = data

    def set_output(self, data: dict[str, Any]) -> None:
        _ = data

    def set_attribute(self, key: str, value: Any) -> None:
        _ = key, value

    def set_error(self, exc: BaseException | str, *, kind: str | None = None) -> None:
        _ = exc, kind


class _NoopSpanContext(AbstractContextManager[_NoopSpanHandle]):
    """
    无副作用 context manager。

    __exit__ 永远返回 False，意味着业务异常会继续向外抛出，不会被观测系统吞掉。
    """

    def __enter__(self) -> _NoopSpanHandle:
        return _NoopSpanHandle()

    def __exit__(self, exc_type, exc, traceback) -> bool:
        _ = exc_type, exc, traceback
        return False


class NoopObservabilityHooks:
    """
    ObservabilityHooks 的默认空实现。

    该实现用于 trace 未启用、测试隔离或 TraceRecorder 初始化失败时。所有方法
    均无副作用，span context manager 可以正常进入和退出，并且不会吞掉业务异常。
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
    ) -> str:
        _ = session_id, turn_id, user_goal_preview, provider, model, attributes
        return ""

    def end_run(
        self,
        *,
        status: TraceStatus = "ok",
        attributes: dict[str, Any] | None = None,
        error: BaseException | str | None = None,
    ) -> None:
        _ = status, attributes, error

    def span(
        self,
        name: str,
        span_type: SpanType,
        *,
        attributes: dict[str, Any] | None = None,
        input: dict[str, Any] | None = None,
    ) -> _NoopSpanContext:
        _ = name, span_type, attributes, input
        return _NoopSpanContext()

    def event(
        self,
        name: str,
        *,
        attributes: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        _ = name, attributes, payload
