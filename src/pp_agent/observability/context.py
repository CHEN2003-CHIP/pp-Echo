from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass

current_run_id: ContextVar[str | None] = ContextVar("pp_agent_trace_run_id", default=None)
current_span_id: ContextVar[str | None] = ContextVar("pp_agent_trace_span_id", default=None)
current_session_id: ContextVar[str | None] = ContextVar("pp_agent_trace_session_id", default=None)
current_turn_id: ContextVar[str | int | None] = ContextVar("pp_agent_trace_turn_id", default=None)


@dataclass(frozen=True)
class TraceContextSnapshot:
    """
    当前 Trace 上下文的只读快照。

    使用 contextvars 是为了让同一请求或同一次 Agent 运行中的嵌套 LLM、tool、
    approval span 自动继承 parent_span_id，同时避免不同 session 并发运行时互相
    污染 trace。调用方通常只读取这个快照，不直接操作 ContextVar。
    """

    run_id: str | None
    span_id: str | None
    session_id: str | None
    turn_id: str | int | None


@dataclass(frozen=True)
class TraceContextTokens:
    """
    set_current_trace_context 的重置凭据。

    ContextVar.reset 必须使用 set 时返回的 Token。这个对象把多个字段的 token
    绑定在一起，确保 run/span/session/turn 能在 finally 中一次性恢复到进入前
    的状态。
    """

    run_id: Token[str | None] | None = None
    span_id: Token[str | None] | None = None
    session_id: Token[str | None] | None = None
    turn_id: Token[str | int | None] | None = None


def get_current_trace_context() -> TraceContextSnapshot:
    """
    返回当前执行上下文中的 trace 标识。

    业务模块可通过该函数读取当前 run_id 和 span_id，用于把事件或子 span 自动
    挂到正确父级上。函数不创建任何状态，也不会因为未启用 trace 而报错。
    """

    return TraceContextSnapshot(
        run_id=current_run_id.get(),
        span_id=current_span_id.get(),
        session_id=current_session_id.get(),
        turn_id=current_turn_id.get(),
    )


def set_current_trace_context(
    *,
    run_id: str | None = None,
    span_id: str | None = None,
    session_id: str | None = None,
    turn_id: str | int | None = None,
) -> TraceContextTokens:
    """
    设置当前 trace 上下文字段并返回可恢复 token。

    只有显式传入的字段会被覆盖。调用方应在 finally 中调用
    reset_current_trace_context(tokens)，避免嵌套 span 结束后污染外层上下文。
    """

    return TraceContextTokens(
        run_id=current_run_id.set(run_id) if run_id is not None else None,
        span_id=current_span_id.set(span_id) if span_id is not None else None,
        session_id=current_session_id.set(session_id) if session_id is not None else None,
        turn_id=current_turn_id.set(turn_id) if turn_id is not None else None,
    )


def reset_current_trace_context(tokens: TraceContextTokens) -> None:
    """
    恢复 set_current_trace_context 之前的上下文。

    reset 顺序采用 span -> turn -> session -> run，优先撤销最内层 span，降低
    嵌套 context manager 在异常路径上的残留风险。
    """

    if tokens.span_id is not None:
        current_span_id.reset(tokens.span_id)
    if tokens.turn_id is not None:
        current_turn_id.reset(tokens.turn_id)
    if tokens.session_id is not None:
        current_session_id.reset(tokens.session_id)
    if tokens.run_id is not None:
        current_run_id.reset(tokens.run_id)
