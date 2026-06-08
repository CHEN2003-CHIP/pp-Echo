import type { TraceSpan } from "../../api";
import { safeJsonStringify, spanTypeLabel, statusLabel } from "./trace-utils";
import { Fragment } from "react";

export function TraceSpanInspector({ span }: { span: TraceSpan | null }) {
  if (!span) return <section className="trace-inspect-section"><h3>Span</h3><p className="muted">Select a timeline span.</p></section>;
  const attrs = span.attributes || {};
  const llmRows: Array<[string, unknown]> = span.span_type === "llm"
    ? [
        ["Provider", attrs.provider],
        ["Model", attrs.model],
        ["Input Tokens", attrs.input_tokens],
        ["Output Tokens", attrs.output_tokens],
        ["Total Tokens", attrs.total_tokens],
        ["Cost", attrs.cost_usd == null ? "N/A" : `$${Number(attrs.cost_usd).toFixed(6)}`],
        ["Latency", attrs.latency_ms],
        ["Retry Count", attrs.retry_count],
        ["Request ID", attrs.request_id]
      ]
    : [];
  const toolRows: Array<[string, unknown]> = span.span_type === "tool"
    ? [
        ["Source", attrs.source],
        ["Tool", attrs.tool_name],
        ["Tool Call ID", attrs.tool_call_id]
      ]
    : [];
  return (
    <section className="trace-inspect-section trace-span-inspector">
      <h3>{span.name}</h3>
      <dl>
        <dt>Type</dt><dd>{spanTypeLabel(span.span_type)}</dd>
        <dt>Status</dt><dd>{statusLabel(span.status)}</dd>
        <dt>Error</dt><dd>{span.error_message || "-"}</dd>
        {[...llmRows, ...toolRows].map(([label, value]) => (
          <Fragment key={String(label)}><dt>{label}</dt><dd>{value == null || value === "" ? "-" : String(value)}</dd></Fragment>
        ))}
      </dl>
      <details open><summary>Attributes</summary><pre>{safeJsonStringify(span.attributes)}</pre></details>
      <details><summary>Input</summary><pre>{safeJsonStringify(span.input)}</pre></details>
      <details><summary>Output</summary><pre>{safeJsonStringify(span.output)}</pre></details>
    </section>
  );
}
