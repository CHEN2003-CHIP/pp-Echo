import type { TraceRunSummary } from "../../api";
import type { ReactNode } from "react";
import { formatDuration } from "./trace-utils";
import { metricValue, modelSummary, traceErrorCount, traceRisk } from "./trace-display";
import { StatusBadge } from "./StatusBadge";

export function TraceSummaryMetrics({ summary }: { summary: TraceRunSummary | null }) {
  const items = [
    {
      label: "Status",
      value: summary?.status ? <StatusBadge status={summary.status} /> : "Not captured",
      note: summary?.ended_at ? "Run completed" : "Current run state"
    },
    { label: "Duration", value: formatDuration(summary?.duration_ms), note: summary?.llm_latency_ms_avg ? `LLM avg ${formatDuration(summary.llm_latency_ms_avg)}` : "Wall-clock run time" },
    { label: "Model", value: modelSummary(summary), note: summary?.llm_calls ? `${summary.llm_calls} LLM call(s)` : "No LLM calls captured" },
    { label: "Input tokens", value: metricValue(summary?.total_input_tokens), note: "Context + prompt" },
    { label: "Output tokens", value: metricValue(summary?.total_output_tokens), note: "Model response" },
    { label: "Risk", value: <StatusBadge status={traceRisk(summary)} label={traceRisk(summary)} />, note: `${traceErrorCount(summary)} errors / ${summary?.approval_count || 0} approvals` }
  ];
  return (
    <section className="trace-summary-grid" aria-label="Trace summary metrics">
      {items.map((item) => <MetricCard key={item.label} {...item} />)}
    </section>
  );
}

export function MetricCard({ label, value, note }: { label: string; value: ReactNode; note: string }) {
  return (
    <article className="trace-metric-card">
      <div className="trace-metric-label">{label}</div>
      <div className="trace-metric-value">{value}</div>
      <div className="trace-metric-note">{note}</div>
    </article>
  );
}
