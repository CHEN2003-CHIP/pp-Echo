import pytest

from pp_agent.observability.recorder import TraceRecorder
from pp_agent.observability.store import TraceStore
from pp_agent.tools.registry import ToolRegistry


def _registry_with_trace(tmp_path):
    recorder = TraceRecorder(TraceStore(tmp_path / "traces"), workspace=tmp_path)
    recorder.start_run(session_id="s1")
    registry = ToolRegistry(tmp_path, observability=recorder)
    return registry, recorder


def test_tool_registry_execute_records_middleware_span(tmp_path) -> None:
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    registry, recorder = _registry_with_trace(tmp_path)

    result = registry.execute("read_file", {"path": "notes.txt"}, tool_call_id="call-1")
    run_id = recorder.current_run_id
    recorder.end_run()
    detail = TraceStore(tmp_path / "traces").read_run(run_id)

    span = next(span for span in detail.spans if span.name == "tool.call")
    assert span.attributes["tool_name"] == "read_file"
    assert span.attributes["tool_call_id"] == "call-1"
    assert span.attributes["source"] == "tool_registry_middleware"
    assert span.output["content_preview"] == "hello"


def test_tool_registry_trace_redacts_arguments_and_previews_output(tmp_path) -> None:
    registry, recorder = _registry_with_trace(tmp_path)
    registry.register_function_tool(
        name="demo_secret",
        description="Inspect local state",
        parameters={"type": "object", "properties": {"api_key": {"type": "string"}, "query": {"type": "string"}}},
        executor=lambda workspace, arguments: "x" * 3000,
        permission_domain="read",
        tool_family="extension",
        exact_effect_mode="auto",
        non_side_effectful=True,
        known_safe_inspect=True,
    )

    registry.execute("demo_secret", {"api_key": "sk-secret-value", "query": "status"}, tool_call_id="call-2")
    run_id = recorder.current_run_id
    recorder.end_run()
    detail = TraceStore(tmp_path / "traces").read_run(run_id)

    span = next(span for span in detail.spans if span.attributes.get("tool_call_id") == "call-2")
    assert span.input["arguments"]["api_key"] == "[REDACTED]"
    assert len(span.output["content_preview"]) <= 2000


def test_tool_registry_trace_marks_result_errors_and_preserves_exceptions(tmp_path) -> None:
    registry, recorder = _registry_with_trace(tmp_path)
    registry.register_function_tool(
        name="demo_boom",
        description="Inspect local state",
        parameters={"type": "object", "properties": {}},
        executor=lambda workspace, arguments: (_ for _ in ()).throw(RuntimeError("boom")),
        permission_domain="read",
        tool_family="extension",
        exact_effect_mode="auto",
        non_side_effectful=True,
        known_safe_inspect=True,
    )

    with pytest.raises(RuntimeError, match="boom"):
        registry.execute("demo_boom", {}, tool_call_id="call-3")
    run_id = recorder.current_run_id
    recorder.end_run(status="error")
    detail = TraceStore(tmp_path / "traces").read_run(run_id)

    span = next(span for span in detail.spans if span.attributes.get("tool_call_id") == "call-3")
    assert span.status == "error"
    assert span.error_message == "boom"
