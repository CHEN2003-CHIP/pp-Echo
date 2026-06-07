from pp_agent.observability.schema import TraceRun, TraceRunSummary, TraceSpan
from pp_agent.observability.store import TraceStore


def test_trace_store_write_read_and_index_dedupe(tmp_path):
    store = TraceStore(tmp_path)
    run = TraceRun(run_id="run-1", workspace=str(tmp_path), started_at=1.0, ended_at=2.0, duration_ms=1000, status="ok")
    span = TraceSpan(run_id="run-1", span_id="s1", name="tool.call", span_type="tool", started_at=1.1, ended_at=1.2, status="ok")
    store.append_record("run-1", {"record_type": "run_start", "data": run.model_dump(mode="json")})
    store.append_record("run-1", {"record_type": "span_end", "data": span.model_dump(mode="json")})
    detail = store.read_run("run-1")
    assert detail.run and detail.run.run_id == "run-1"
    assert detail.spans[0].span_id == "s1"
    store.append_index(TraceRunSummary(run_id="run-1", workspace=str(tmp_path), started_at=1.0, status="running"))
    store.append_index(TraceRunSummary(run_id="run-1", workspace=str(tmp_path), started_at=2.0, status="ok"))
    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0].status == "ok"


def test_trace_store_list_runs_scans_when_index_missing(tmp_path):
    store = TraceStore(tmp_path)
    run = TraceRun(
        run_id="run-no-index",
        session_id="session-1",
        workspace=str(tmp_path),
        started_at=3.0,
        ended_at=4.0,
        duration_ms=1000,
        status="ok",
    )
    span = TraceSpan(
        run_id="run-no-index",
        span_id="s1",
        name="llm.call",
        span_type="llm",
        started_at=3.1,
        ended_at=3.2,
        status="ok",
        attributes={"input_tokens": "[REDACTED]", "output_tokens": 5},
    )
    store.append_record("run-no-index", {"record_type": "run_start", "data": run.model_dump(mode="json")})
    store.append_record("run-no-index", {"record_type": "span_end", "data": span.model_dump(mode="json")})
    store.append_record("run-no-index", {"record_type": "run_end", "data": run.model_dump(mode="json")})

    runs = store.list_runs(session_id="session-1")

    assert [item.run_id for item in runs] == ["run-no-index"]
    assert runs[0].status == "ok"
    assert runs[0].total_output_tokens == 5


def test_trace_store_skips_corrupt_rows(tmp_path):
    store = TraceStore(tmp_path)
    path = store._run_path("run-2")
    path.parent.mkdir(parents=True)
    path.write_text('{"record_type":"bad","data":{}}\nnot-json\n', encoding="utf-8")
    detail = store.read_run("run-2")
    assert detail.warnings
