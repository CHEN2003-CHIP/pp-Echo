from __future__ import annotations

from pp_agent.observability.schema import TraceDetail, TraceRunSummary


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _span_value(span, key: str) -> object:
    if key in span.attributes:
        return span.attributes.get(key)
    return span.output.get(key)


def _dedupe_tool_spans(spans) -> list:
    """
    按 tool_call_id 对 tool span 去重，并优先保留 ToolRegistry middleware 生成的主 span。

    Runtime lifecycle event 仍会被转换成 tool.call span，以兼容旧 trace 和现有事件链路；当同一次
    调用同时存在 middleware 与 lifecycle span 时，summary.py 只统计一次，避免 TraceInspect 列表
    和运行摘要出现明显重复。缺失 tool_call_id 的旧 span 保持原样统计。
    """

    selected: dict[str, object] = {}
    anonymous: list[object] = []
    for span in spans:
        tool_call_id = str(span.attributes.get("tool_call_id") or "").strip()
        if not tool_call_id:
            anonymous.append(span)
            continue
        current = selected.get(tool_call_id)
        source = span.attributes.get("source")
        current_source = getattr(current, "attributes", {}).get("source") if current is not None else None
        if current is None or (source == "tool_registry_middleware" and current_source != "tool_registry_middleware"):
            selected[tool_call_id] = span
    return [*selected.values(), *anonymous]


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
    tools_used: set[str] = set()
    high_risk = False
    medium_risk = False
    tool_span_ids = {span.span_id for span in _dedupe_tool_spans([span for span in detail.spans if span.span_type == "tool"])}
    for span in detail.spans:
        if span.span_type == "llm":
            summary.llm_calls += 1
            input_tokens = _safe_int(_span_value(span, "input_tokens"))
            output_tokens = _safe_int(_span_value(span, "output_tokens"))
            summary.total_input_tokens += input_tokens
            summary.total_output_tokens += output_tokens
            span_total = _safe_int(_span_value(span, "total_tokens"))
            summary.total_tokens += span_total or (input_tokens + output_tokens)
            cost = _safe_float(_span_value(span, "cost_usd"))
            if cost is not None:
                summary.total_cost_usd = round((summary.total_cost_usd or 0.0) + cost, 8)
            latency = _safe_int(_span_value(span, "latency_ms"))
            if latency:
                summary.llm_latency_ms_total += latency
            summary.llm_retry_count += _safe_int(_span_value(span, "retry_count"))
        elif span.span_type == "tool":
            if span.span_id in tool_span_ids:
                summary.tool_calls += 1
                tool_name = str(span.attributes.get("tool_name") or span.name or "").strip()
                if tool_name:
                    tools_used.add(tool_name)
                if span.status == "error" or bool(span.output.get("is_error")):
                    summary.tool_error_count += 1
                if bool(span.attributes.get("is_mcp_tool")) or span.attributes.get("tool_family") == "mcp" or span.attributes.get("tool_category") == "mcp":
                    summary.mcp_tool_calls += 1
                if bool(span.attributes.get("is_subagent_tool")):
                    summary.subagent_tool_calls += 1
                if span.attributes.get("tool_family") == "shell" or span.attributes.get("permission_domain") == "bash" or tool_name == "run_shell":
                    summary.shell_tool_calls += 1
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
    if summary.total_tokens == 0:
        summary.total_tokens = summary.total_input_tokens + summary.total_output_tokens
    summary.tools_used = sorted(tools_used)
    if summary.llm_calls and summary.llm_latency_ms_total:
        summary.llm_latency_ms_avg = int(summary.llm_latency_ms_total / summary.llm_calls)
    if summary.blocked_count or high_risk:
        summary.risk_level = "high"
    elif summary.approval_count or medium_risk:
        summary.risk_level = "medium"
    else:
        summary.risk_level = "low"
    if summary.status == "running" and run and run.ended_at is not None:
        summary.status = "ok" if summary.error_count == 0 and summary.blocked_count == 0 else "error"
    return summary
