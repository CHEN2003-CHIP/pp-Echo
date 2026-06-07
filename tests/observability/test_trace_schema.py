from pp_agent.observability.schema import TraceRun, TraceSpan


def test_trace_schema_defaults():
    run = TraceRun(run_id="r1", workspace=".", started_at=1.0)
    span = TraceSpan(run_id="r1", span_id="s1", name="tool.call", span_type="tool", started_at=1.0)
    assert run.schema_version == "1.0"
    assert run.status == "running"
    assert span.input == {}
    assert span.output == {}
