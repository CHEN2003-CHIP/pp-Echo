from __future__ import annotations

import time
import uuid
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from pp_agent.observability.context import (
    get_current_trace_context,
    reset_current_trace_context,
    set_current_trace_context,
)
from pp_agent.observability.redaction import json_safe, redact_mapping, safe_preview
from pp_agent.observability.schema import SpanType, TraceEvent, TraceRun, TraceRunSummary, TraceSpan, TraceStatus
from pp_agent.observability.store import TraceStore
from pp_agent.observability.summary import build_trace_summary
from pp_agent.observability.schema import TraceDetail


class TraceSpanContext(AbstractContextManager["TraceSpanHandle"]):
    """
    Trace span 的上下文管理器。

    进入 with 块时写入 span_start，并把当前 span_id 放入 contextvars；退出时写入
    span_end。如果 with 块抛出异常，会自动标记 error_kind 和 error_message，然后
    继续把异常抛给原业务逻辑，避免观测系统吞掉真实错误。
    """

    def __init__(
        self,
        recorder: "TraceRecorder",
        name: str,
        span_type: SpanType,
        *,
        attributes: dict[str, Any] | None = None,
        input: dict[str, Any] | None = None,
    ) -> None:
        self.recorder = recorder
        self.name = name
        self.span_type = span_type
        self.attributes = attributes or {}
        self.input = input or {}
        self.span: TraceSpan | None = None
        self.handle: TraceSpanHandle | None = None
        self._tokens = None

    def __enter__(self) -> "TraceSpanHandle":
        context = get_current_trace_context()
        span_id = str(uuid.uuid4())
        now = time.time()
        self.span = TraceSpan(
            run_id=context.run_id or self.recorder.current_run_id or str(uuid.uuid4()),
            span_id=span_id,
            parent_span_id=context.span_id,
            session_id=context.session_id or self.recorder.current_session_id,
            turn_id=context.turn_id or self.recorder.current_turn_id,
            name=self.name,
            span_type=self.span_type,
            started_at=now,
            input=redact_mapping(self.input),
            attributes=redact_mapping(self.attributes),
            redaction_applied=True,
        )
        self.handle = TraceSpanHandle(self.span)
        self.recorder._append("span_start", self.span.model_dump(mode="json"))
        self._tokens = set_current_trace_context(
            run_id=self.span.run_id,
            span_id=span_id,
            session_id=self.span.session_id,
            turn_id=self.span.turn_id,
        )
        return self.handle

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if self.span is None:
            return False
        if exc is not None:
            self.span.status = "error"
            self.span.error_kind = exc.__class__.__name__
            self.span.error_message = safe_preview(str(exc), 1000)
        elif self.span.status == "running":
            self.span.status = "ok"
        self.span.ended_at = time.time()
        self.span.duration_ms = int((self.span.ended_at - self.span.started_at) * 1000)
        self.span.input = redact_mapping(self.span.input)
        self.span.output = redact_mapping(self.span.output)
        self.span.attributes = redact_mapping(self.span.attributes)
        self.span.redaction_applied = True
        self.recorder._append("span_end", self.span.model_dump(mode="json"))
        if self._tokens is not None:
            reset_current_trace_context(self._tokens)
        return False


class TraceSpanHandle:
    """
    TraceSpanContext 暴露给业务代码的可变句柄。

    句柄允许在 span 执行过程中补充 input、output、attribute 或 error 信息。
    所有写入都会在 span 结束时统一脱敏并落盘，避免业务代码需要关心 JSONL 格式。
    """

    def __init__(self, span: TraceSpan) -> None:
        self._span = span

    def set_input(self, data: dict[str, Any]) -> None:
        self._span.input.update(redact_mapping(data))

    def set_output(self, data: dict[str, Any]) -> None:
        self._span.output.update(redact_mapping(data))

    def set_attribute(self, key: str, value: Any) -> None:
        self._span.attributes[key] = json_safe(value)

    def set_error(self, exc: BaseException | str, *, kind: str | None = None) -> None:
        self._span.status = "error"
        self._span.error_kind = kind or (exc.__class__.__name__ if isinstance(exc, BaseException) else "error")
        self._span.error_message = safe_preview(str(exc), 1000)


class TraceRecorder:
    """
    Runtime Trace 的默认实现。

    TraceRecorder 通过 ObservabilityHooks 接口接入 AgentRuntime、ToolRegistry、
    Memory、Approval、Checkpoint 等核心边界。它负责创建 run/span/event，
    自动维护 parent_span_id，执行输入输出脱敏，并把审计记录追加写入 TraceStore。

    设计边界：
    - 它不改变业务流程。
    - 它不能因为写 trace 失败导致 Agent 主任务失败。
    - 它不保存模型隐藏推理链。
    - 它保存的是可审计摘要和结构化元数据。
    """

    def __init__(self, store: TraceStore, *, workspace: Path) -> None:
        self.store = store
        self.workspace = workspace.resolve()
        self.current_run: TraceRun | None = None
        self.current_run_id: str | None = None
        self.current_session_id: str | None = None
        self.current_turn_id: str | int | None = None
        self._run_tokens = None
        self.internal_warnings: list[str] = []

    def start_run(
        self,
        *,
        run_id: str | None = None,
        session_id: str | None = None,
        turn_id: str | int | None = None,
        user_goal_preview: str = "",
        provider: str | None = None,
        model: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> str:
        run_id = str(run_id or uuid.uuid4())
        self.current_run = TraceRun(
            run_id=run_id,
            session_id=session_id,
            turn_id=turn_id,
            workspace=str(self.workspace),
            user_goal_preview=safe_preview(user_goal_preview, 1000),
            status="running",
            started_at=time.time(),
            provider=provider,
            model=model,
            attributes=redact_mapping(attributes or {}),
        )
        self.current_run_id = run_id
        self.current_session_id = session_id
        self.current_turn_id = turn_id
        self._run_tokens = set_current_trace_context(run_id=run_id, session_id=session_id, turn_id=turn_id)
        self._append("run_start", self.current_run.model_dump(mode="json"))
        return run_id

    def end_run(
        self,
        *,
        status: TraceStatus = "ok",
        attributes: dict[str, Any] | None = None,
        error: BaseException | str | None = None,
    ) -> None:
        if self.current_run is None:
            return
        ended_at = time.time()
        self.current_run.ended_at = ended_at
        self.current_run.duration_ms = int((ended_at - self.current_run.started_at) * 1000)
        self.current_run.status = "error" if error is not None else status
        if attributes:
            self.current_run.attributes.update(redact_mapping(attributes))
        if error is not None:
            self.current_run.attributes["error_message"] = safe_preview(str(error), 1000)
        self._append("run_end", self.current_run.model_dump(mode="json"))
        try:
            detail = self.store.read_run(self.current_run.run_id)
            detail.run = self.current_run
            summary = build_trace_summary(detail)
            summary.status = self.current_run.status
            self.store.append_index(summary)
        except Exception as exc:  # noqa: BLE001
            self.internal_warnings.append(f"trace index write failed: {exc}")
        if self._run_tokens is not None:
            reset_current_trace_context(self._run_tokens)
        self.current_run = None
        self.current_run_id = None
        self.current_session_id = None
        self.current_turn_id = None
        self._run_tokens = None

    def span(
        self,
        name: str,
        span_type: SpanType,
        *,
        attributes: dict[str, Any] | None = None,
        input: dict[str, Any] | None = None,
    ) -> TraceSpanContext:
        return TraceSpanContext(self, name, span_type, attributes=attributes, input=input)

    def event(
        self,
        name: str,
        *,
        attributes: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        context = get_current_trace_context()
        run_id = context.run_id or self.current_run_id
        if not run_id:
            return
        event = TraceEvent(
            run_id=run_id,
            event_id=str(uuid.uuid4()),
            name=name,
            timestamp=time.time(),
            session_id=context.session_id or self.current_session_id,
            turn_id=context.turn_id or self.current_turn_id,
            span_id=context.span_id,
            attributes=redact_mapping(attributes or {}),
            payload=redact_mapping(payload or {}),
            redaction_applied=True,
        )
        self._append("event", event.model_dump(mode="json"))

    def record_completed_span(
        self,
        name: str,
        span_type: SpanType,
        *,
        status: TraceStatus = "ok",
        started_at: float | None = None,
        ended_at: float | None = None,
        attributes: dict[str, Any] | None = None,
        input: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        error: BaseException | str | None = None,
    ) -> None:
        """
        记录一个已经完成的 span。

        该方法用于把既有 Runtime lifecycle event 转换为 TraceSpan，而无需重写主
        控制流。调用方可以传入 start/end 时间，TraceRecorder 负责补齐上下文、
        脱敏和 JSONL 写入。
        """

        context = get_current_trace_context()
        run_id = context.run_id or self.current_run_id
        if not run_id:
            return
        now = time.time()
        start = started_at or ended_at or now
        end = ended_at or now
        span = TraceSpan(
            run_id=run_id,
            span_id=str(uuid.uuid4()),
            parent_span_id=context.span_id,
            session_id=context.session_id or self.current_session_id,
            turn_id=context.turn_id or self.current_turn_id,
            name=name,
            span_type=span_type,
            status="error" if error is not None else status,
            started_at=start,
            ended_at=end,
            duration_ms=int(max(0.0, end - start) * 1000),
            input=redact_mapping(input or {}),
            output=redact_mapping(output or {}),
            attributes=redact_mapping(attributes or {}),
            error_kind=error.__class__.__name__ if isinstance(error, BaseException) else ("error" if error is not None else None),
            error_message=safe_preview(str(error), 1000) if error is not None else None,
            redaction_applied=True,
        )
        self._append("span_start", span.model_dump(mode="json"))
        self._append("span_end", span.model_dump(mode="json"))

    def _append(self, record_type: str, data: dict[str, Any]) -> None:
        run_id = str(data.get("run_id") or self.current_run_id or "")
        if not run_id:
            return
        try:
            self.store.append_record(run_id, {"record_type": record_type, "data": json_safe(data)})
        except Exception as exc:  # noqa: BLE001
            self.internal_warnings.append(f"trace append failed: {exc}")
