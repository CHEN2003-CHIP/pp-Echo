import pytest

from pp_agent.observability.noop import NoopObservabilityHooks
from pp_agent.observability.recorder import TraceRecorder
from pp_agent.observability.store import TraceStore


def test_trace_recorder_start_end_run(tmp_path):
    recorder = TraceRecorder(TraceStore(tmp_path), workspace=tmp_path)
    run_id = recorder.start_run(session_id="s1", user_goal_preview="hello", provider="p", model="m")
    with recorder.span("tool.call", "tool", attributes={"tool_name": "x"}) as span:
        span.set_output({"content_preview": "ok"})
    recorder.end_run()
    detail = TraceStore(tmp_path).read_run(run_id)
    assert detail.run and detail.run.status == "ok"
    assert detail.spans[0].name == "tool.call"
    assert TraceStore(tmp_path).list_runs()[0].run_id == run_id


def test_trace_recorder_nested_parent_and_error(tmp_path):
    recorder = TraceRecorder(TraceStore(tmp_path), workspace=tmp_path)
    run_id = recorder.start_run(session_id="s1")
    with pytest.raises(RuntimeError):
        with recorder.span("outer", "system"):
            with recorder.span("inner", "tool"):
                raise RuntimeError("boom")
    recorder.end_run(status="error")
    detail = TraceStore(tmp_path).read_run(run_id)
    inner = next(span for span in detail.spans if span.name == "inner")
    outer = next(span for span in detail.spans if span.name == "outer")
    assert inner.parent_span_id == outer.span_id
    assert inner.status == "error"


def test_noop_observability_does_not_swallow_exception():
    noop = NoopObservabilityHooks()
    with pytest.raises(ValueError):
        with noop.span("x", "system"):
            raise ValueError("still raised")
