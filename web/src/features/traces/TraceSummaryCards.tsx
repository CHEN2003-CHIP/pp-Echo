import type { TraceRunSummary } from "../../api";
import { formatDuration, statusLabel } from "./trace-utils";

export function TraceSummaryCards({ summary }: { summary: TraceRunSummary | null }) {
  const cost = summary?.total_cost_usd == null ? "N/A" : `$${summary.total_cost_usd.toFixed(6)}`;
  const items = [
    ["Status", summary ? statusLabel(summary.status) : "-"],
    ["Duration", formatDuration(summary?.duration_ms)],
    ["LLM", summary?.llm_calls ?? 0],
    ["Tools", summary?.tool_calls ?? 0],
    ["Approvals", summary?.approval_count ?? 0],
    ["Memory", summary?.memory_recall_count ?? 0],
    ["Checkpoints", summary?.checkpoint_count ?? 0],
    ["Errors", summary?.error_count ?? 0],
    ["Risk", summary?.risk_level ?? "-"],
    ["Input Tokens", summary?.total_input_tokens ?? 0],
    ["Output Tokens", summary?.total_output_tokens ?? 0],
    ["Total Tokens", summary?.total_tokens ?? 0],
    ["Cost", cost],
    ["LLM Avg Latency", formatDuration(summary?.llm_latency_ms_avg)],
    ["Retry Count", summary?.llm_retry_count ?? 0]
  ];
  return <section className="trace-inspect-summary">{items.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</section>;
}
