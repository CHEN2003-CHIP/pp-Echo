import type { TraceRunSummary } from "../../api";
import { formatDuration, statusLabel } from "./trace-utils";

type TraceStatTone = "positive" | "negative" | "neutral";

export function TraceSummaryCards({ summary }: { summary: TraceRunSummary | null }) {
  const cost = summary?.total_cost_usd == null ? "N/A" : `$${summary.total_cost_usd.toFixed(6)}`;
  const items: Array<{ label: string; value: string | number; tone: TraceStatTone }> = [
    { label: "Status", value: summary ? statusLabel(summary.status) : "-", tone: toneFor("status", summary?.status) },
    { label: "Duration", value: formatDuration(summary?.duration_ms), tone: "neutral" },
    { label: "LLM", value: summary?.llm_calls ?? 0, tone: "neutral" },
    { label: "Tools", value: summary?.tool_calls ?? 0, tone: "neutral" },
    { label: "Approvals", value: summary?.approval_count ?? 0, tone: "neutral" },
    { label: "Memory", value: summary?.memory_recall_count ?? 0, tone: "neutral" },
    { label: "Checkpoints", value: summary?.checkpoint_count ?? 0, tone: "neutral" },
    { label: "Errors", value: summary?.error_count ?? 0, tone: Number(summary?.error_count || 0) > 0 ? "negative" : "positive" },
    { label: "Risk", value: summary?.risk_level ?? "-", tone: toneFor("risk", summary?.risk_level) },
    { label: "Input Tokens", value: summary?.total_input_tokens ?? 0, tone: "neutral" },
    { label: "Output Tokens", value: summary?.total_output_tokens ?? 0, tone: "neutral" },
    { label: "Total Tokens", value: summary?.total_tokens ?? 0, tone: "neutral" },
    { label: "Cost", value: cost, tone: "neutral" },
    { label: "LLM Avg Latency", value: formatDuration(summary?.llm_latency_ms_avg), tone: "neutral" },
    { label: "Retry Count", value: summary?.llm_retry_count ?? 0, tone: Number(summary?.llm_retry_count || 0) > 0 ? "negative" : "positive" }
  ];
  return (
    <dl className="trace-inspect-summary" aria-label="Trace summary">
      {items.map((item) => (
        <div className={`trace-stat trace-stat-${item.tone}`} key={item.label}>
          <dt>{item.label}</dt>
          <dd>
            <strong>{item.value}</strong>
            {item.tone !== "neutral" ? <em>{item.tone === "positive" ? "OK" : "!"}</em> : null}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function toneFor(kind: "status" | "risk", value?: string | null): TraceStatTone {
  const normalized = String(value || "").toLowerCase();
  if (kind === "status") {
    if (["success", "completed", "ok"].some((item) => normalized.includes(item))) return "positive";
    if (["error", "failed", "cancel"].some((item) => normalized.includes(item))) return "negative";
  }
  if (kind === "risk" && ["high", "critical"].some((item) => normalized.includes(item))) return "negative";
  return "neutral";
}
