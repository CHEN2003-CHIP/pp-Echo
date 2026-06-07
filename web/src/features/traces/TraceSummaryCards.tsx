import type { TraceRunSummary } from "../../api";
import { formatDuration, statusLabel } from "./trace-utils";

export function TraceSummaryCards({ summary }: { summary: TraceRunSummary | null }) {
  const items = [
    ["状态", summary ? statusLabel(summary.status) : "-"],
    ["耗时", formatDuration(summary?.duration_ms)],
    ["LLM", summary?.llm_calls ?? 0],
    ["工具", summary?.tool_calls ?? 0],
    ["审批", summary?.approval_count ?? 0],
    ["记忆", summary?.memory_recall_count ?? 0],
    ["检查点", summary?.checkpoint_count ?? 0],
    ["错误", summary?.error_count ?? 0],
    ["风险", summary?.risk_level ?? "-"],
    ["Tokens", summary?.total_tokens ?? 0]
  ];
  return <section className="trace-inspect-summary">{items.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</section>;
}
