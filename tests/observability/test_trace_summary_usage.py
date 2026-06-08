from pp_agent.observability.schema import TraceDetail, TraceRun, TraceSpan
from pp_agent.observability.summary import build_trace_summary


def test_summary_aggregates_llm_usage_cost_latency_and_retry(tmp_path) -> None:
    detail = TraceDetail(
        run=TraceRun(run_id="r1", workspace=str(tmp_path), started_at=1.0),
        spans=[
            TraceSpan(
                run_id="r1",
                span_id="s1",
                name="llm.call",
                span_type="llm",
                started_at=1.0,
                attributes={
                    "input_tokens": 100,
                    "output_tokens": 25,
                    "total_tokens": 125,
                    "cost_usd": 0.001,
                    "latency_ms": 800,
                    "retry_count": 1,
                },
            ),
            TraceSpan(
                run_id="r1",
                span_id="s2",
                name="llm.call",
                span_type="llm",
                started_at=2.0,
                output={"input_tokens": 10, "output_tokens": 5, "latency_ms": 200},
            ),
        ],
    )

    summary = build_trace_summary(detail)

    assert summary.total_input_tokens == 110
    assert summary.total_output_tokens == 30
    assert summary.total_tokens == 140
    assert summary.total_cost_usd == 0.001
    assert summary.llm_latency_ms_total == 1000
    assert summary.llm_latency_ms_avg == 500
    assert summary.llm_retry_count == 1


def test_summary_handles_old_llm_spans_without_usage(tmp_path) -> None:
    detail = TraceDetail(
        run=TraceRun(run_id="r1", workspace=str(tmp_path), started_at=1.0),
        spans=[TraceSpan(run_id="r1", span_id="s1", name="llm.call", span_type="llm", started_at=1.0)],
    )

    summary = build_trace_summary(detail)

    assert summary.llm_calls == 1
    assert summary.total_tokens == 0
    assert summary.total_cost_usd is None
