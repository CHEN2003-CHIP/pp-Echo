from __future__ import annotations

from pp_agent.observability.schema import TraceDetail, TraceDiagnosis


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def diagnose_trace(detail: TraceDetail) -> list[TraceDiagnosis]:
    """
    对 TraceDetail 进行基础可读诊断。

    诊断规则覆盖错误 span、pending approval、工具错误后最终回答、memory 召回为空、
    token 膨胀、approval digest mismatch 和 policy blocked。结果用于 TraceInspect
    的 DiagnosisPanel，帮助用户快速理解任务卡住或失败的原因。
    """

    findings: list[TraceDiagnosis] = []
    error_span = next((span for span in detail.spans if span.status == "error"), None)
    if error_span is not None:
        findings.append(
            TraceDiagnosis(
                code="first_error_span",
                severity="error",
                title="首个失败步骤",
                message=f"{error_span.name} 失败：{error_span.error_message or '未记录错误详情'}",
                span_id=error_span.span_id,
            )
        )
    for span in detail.spans:
        if span.span_type == "approval" and span.status == "pending":
            findings.append(
                TraceDiagnosis(
                    code="approval_pending",
                    severity="warning",
                    title="等待审批",
                    message="任务正在等待 host 审批，批准或拒绝后才能继续。",
                    span_id=span.span_id,
                    attributes={"approval_token": span.attributes.get("approval_token") or span.output.get("approval_token")},
                )
            )
        if span.span_type == "memory" and _safe_int(span.output.get("returned_count")) == 0:
            findings.append(
                TraceDiagnosis(
                    code="memory_empty",
                    severity="info",
                    title="没有召回记忆",
                    message="memory recall 没有返回命中，回答可能只基于当前上下文。",
                    span_id=span.span_id,
                )
            )
        if span.span_type in {"context", "llm"}:
            tokens = _safe_int(span.attributes.get("estimated_tokens") or span.attributes.get("total_tokens"))
            if tokens >= 24000:
                findings.append(
                    TraceDiagnosis(
                        code="context_large",
                        severity="warning",
                        title="上下文较大",
                        message="上下文或工具 schema token 较大，可能影响模型稳定性和成本。",
                        span_id=span.span_id,
                        attributes={"estimated_tokens": tokens},
                    )
                )
        if span.span_type == "approval" and bool(span.attributes.get("digest_mismatch") or span.output.get("digest_mismatch")):
            findings.append(
                TraceDiagnosis(
                    code="approval_digest_mismatch",
                    severity="error",
                    title="审批摘要不匹配",
                    message="执行前 payload_digest 与审批阶段不一致，这是严重审计问题。",
                    span_id=span.span_id,
                )
            )
        if span.span_type == "policy" and span.status == "blocked":
            findings.append(
                TraceDiagnosis(
                    code="policy_blocked",
                    severity="warning",
                    title="策略拦截",
                    message="安全策略阻止了该步骤执行。",
                    span_id=span.span_id,
                )
            )
    if any(span.span_type == "tool" and span.status == "error" for span in detail.spans):
        final = next((span for span in reversed(detail.spans) if span.name == "final.answer"), None)
        if final is not None and final.status == "ok":
            findings.append(
                TraceDiagnosis(
                    code="tool_error_with_final_answer",
                    severity="warning",
                    title="工具失败后仍有最终回答",
                    message="存在工具错误，但运行仍产生最终回答，请复核回答是否可靠。",
                    span_id=final.span_id,
                )
            )
    return findings
