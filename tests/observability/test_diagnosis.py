from pp_agent.observability.diagnosis import diagnose_trace
from pp_agent.observability.schema import TraceDetail, TraceRun, TraceSpan


def test_diagnosis_detects_error_pending_and_digest_mismatch(tmp_path):
    detail = TraceDetail(
        run=TraceRun(run_id="r1", workspace=str(tmp_path), started_at=1.0),
        spans=[
            TraceSpan(run_id="r1", span_id="s1", name="tool.call", span_type="tool", status="error", started_at=1.0, error_message="failed"),
            TraceSpan(run_id="r1", span_id="s2", name="approval.decision", span_type="approval", status="pending", started_at=1.1),
            TraceSpan(run_id="r1", span_id="s3", name="approval.execute", span_type="approval", status="error", started_at=1.2, attributes={"digest_mismatch": True}),
        ],
    )
    codes = {item.code for item in diagnose_trace(detail)}
    assert "first_error_span" in codes
    assert "approval_pending" in codes
    assert "approval_digest_mismatch" in codes


def test_diagnosis_tolerates_redacted_token_counts(tmp_path):
    detail = TraceDetail(
        run=TraceRun(run_id="r1", workspace=str(tmp_path), started_at=1.0),
        spans=[
            TraceSpan(
                run_id="r1",
                span_id="s1",
                name="llm.call",
                span_type="llm",
                status="ok",
                started_at=1.0,
                attributes={"estimated_tokens": "[REDACTED]"},
            ),
            TraceSpan(
                run_id="r1",
                span_id="s2",
                name="memory.recall",
                span_type="memory",
                status="ok",
                started_at=1.1,
                output={"returned_count": "[REDACTED]"},
            ),
        ],
    )
    findings = diagnose_trace(detail)
    assert all(item.code != "context_large" for item in findings)
