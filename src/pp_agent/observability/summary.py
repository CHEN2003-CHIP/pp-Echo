from __future__ import annotations

from pp_agent.observability.schema import TraceDetail, TraceRunSummary


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def build_trace_summary(detail: TraceDetail) -> TraceRunSummary:
    """
    从 TraceDetail 聚合列表页摘要。

    该函数只读取 run/span/event/artifact 的结构化字段，生成调用次数、错误数量、
    token 统计、风险等级和变更路径数量。它为后续 eval 从 trace 读取指标预留了
    稳定入口。
    """

    run = detail.run
    summary = TraceRunSummary(
        run_id=run.run_id if run else "",
        session_id=run.session_id if run else None,
        turn_id=run.turn_id if run else None,
        workspace=run.workspace if run else "",
        user_goal_preview=run.user_goal_preview if run else "",
        status=run.status if run else "error",
        started_at=run.started_at if run else 0.0,
        ended_at=run.ended_at if run else None,
        duration_ms=run.duration_ms if run else None,
        provider=run.provider if run else None,
        model=run.model if run else None,
        attributes=dict(run.attributes) if run else {},
    )
    changed_paths: set[str] = set()
    high_risk = False
    medium_risk = False
    for span in detail.spans:
        if span.span_type == "llm":
            summary.llm_calls += 1
        elif span.span_type == "tool":
            summary.tool_calls += 1
        elif span.span_type == "approval":
            summary.approval_count += 1
        elif span.span_type == "memory":
            summary.memory_recall_count += 1
        elif span.span_type == "checkpoint":
            summary.checkpoint_count += 1
        elif span.span_type == "subagent":
            summary.subagent_count += 1
        if span.status == "error":
            summary.error_count += 1
        if span.status == "blocked":
            summary.blocked_count += 1
        if span.status == "pending":
            summary.pending_count += 1
        summary.total_input_tokens += _safe_int(span.attributes.get("input_tokens") or span.output.get("input_tokens"))
        summary.total_output_tokens += _safe_int(span.attributes.get("output_tokens") or span.output.get("output_tokens"))
        for source in (span.attributes, span.output):
            for path in source.get("changed_paths") or []:
                if isinstance(path, str) and path:
                    changed_paths.add(path)
            risk_class = str(source.get("risk_class") or "")
            if risk_class in {"destructive", "external", "network", "blocked"}:
                high_risk = True
            if any(bool(source.get(key)) for key in ("destructive_hint", "touches_external_paths", "requests_network", "digest_mismatch")):
                high_risk = True
            if any(bool(source.get(key)) for key in ("approval_expected", "staged", "writes_workspace_files")):
                medium_risk = True
        if span.span_type == "tool" and span.status == "error":
            medium_risk = True
    for event in detail.events:
        attrs = event.attributes
        if event.name.endswith("blocked") or attrs.get("policy_action") == "deny":
            high_risk = True
        if event.name.startswith("approval.") or attrs.get("approval_token"):
            medium_risk = True
    summary.changed_path_count = len(changed_paths)
    summary.total_tokens = summary.total_input_tokens + summary.total_output_tokens
    if summary.blocked_count or high_risk:
        summary.risk_level = "high"
    elif summary.approval_count or medium_risk:
        summary.risk_level = "medium"
    else:
        summary.risk_level = "low"
    if summary.status == "running" and run and run.ended_at is not None:
        summary.status = "ok" if summary.error_count == 0 and summary.blocked_count == 0 else "error"
    return summary
