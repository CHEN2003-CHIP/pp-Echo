from pp_agent.observability.schema import TraceDetail, TraceRun, TraceSpan
from pp_agent.observability.summary import build_trace_summary


def test_summary_dedupes_tool_spans_by_tool_call_id_and_prefers_middleware(tmp_path) -> None:
    detail = TraceDetail(
        run=TraceRun(run_id="r1", workspace=str(tmp_path), started_at=1.0),
        spans=[
            TraceSpan(
                run_id="r1",
                span_id="runtime",
                name="tool.call",
                span_type="tool",
                started_at=1.0,
                status="ok",
                attributes={"tool_name": "read_file", "tool_call_id": "call-1", "source": "runtime_lifecycle_event"},
            ),
            TraceSpan(
                run_id="r1",
                span_id="middleware",
                name="tool.call",
                span_type="tool",
                started_at=1.0,
                status="error",
                attributes={
                    "tool_name": "read_file",
                    "tool_call_id": "call-1",
                    "source": "tool_registry_middleware",
                    "permission_domain": "read",
                },
                output={"is_error": True, "changed_paths": ["a.py"]},
            ),
            TraceSpan(
                run_id="r1",
                span_id="shell",
                name="tool.call",
                span_type="tool",
                started_at=2.0,
                status="ok",
                attributes={
                    "tool_name": "run_shell",
                    "tool_call_id": "call-2",
                    "source": "tool_registry_middleware",
                    "tool_family": "shell",
                    "permission_domain": "bash",
                },
            ),
        ],
    )

    summary = build_trace_summary(detail)

    assert summary.tool_calls == 2
    assert summary.tool_error_count == 1
    assert summary.tools_used == ["read_file", "run_shell"]
    assert summary.shell_tool_calls == 1
    assert summary.changed_path_count == 1
