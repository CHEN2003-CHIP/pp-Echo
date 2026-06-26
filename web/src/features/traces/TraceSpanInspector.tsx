import { Fragment } from "react";
import type { TraceSpan } from "../../api";
import { formatDuration, safeJsonStringify, spanTypeLabel, statusLabel } from "./trace-utils";

export function TraceSpanInspector({ span }: { span: TraceSpan | null }) {
  if (!span) return <section className="trace-inspect-section"><h3>Span</h3><p className="muted">Select a timeline span.</p></section>;
  const rows = summaryRows(span);
  return (
    <section className="trace-inspect-section trace-span-inspector">
      <h3>{span.name}</h3>
      <dl>
        <dt>Type</dt><dd>{spanTypeLabel(span.span_type)}</dd>
        <dt>Status</dt><dd>{statusLabel(span.status)}</dd>
        <dt>Duration</dt><dd>{formatDuration(span.duration_ms)}</dd>
        <dt>Error</dt><dd>{span.error_message || "-"}</dd>
        {rows.map(([label, value]) => (
          <Fragment key={label}><dt>{label}</dt><dd>{formatValue(value)}</dd></Fragment>
        ))}
      </dl>
      <details><summary>Attributes</summary><pre>{safeJsonStringify(span.attributes)}</pre></details>
      <details><summary>Input</summary><pre>{safeJsonStringify(span.input)}</pre></details>
      <details><summary>Output</summary><pre>{safeJsonStringify(span.output)}</pre></details>
    </section>
  );
}

function summaryRows(span: TraceSpan): Array<[string, unknown]> {
  if (span.span_type === "llm" || span.name === "llm.call") {
    return [
      ["Provider", span.attributes.provider],
      ["Model", span.attributes.model],
      ["Input Tokens", span.attributes.input_tokens ?? span.output.input_tokens],
      ["Output Tokens", span.attributes.output_tokens ?? span.output.output_tokens],
      ["Total Tokens", span.attributes.total_tokens ?? span.output.total_tokens],
      ["Cost", moneyValue(span.attributes.cost_usd ?? span.output.cost_usd)],
      ["Retries", span.attributes.retry_count],
      ["Request ID", span.attributes.request_id]
    ];
  }
  if (span.span_type === "tool" || span.name === "tool.call") {
    return [
      ["Tool", span.attributes.tool_name ?? span.name],
      ["Tool Call ID", span.attributes.tool_call_id],
      ["Source", span.attributes.source],
      ["Permission", span.attributes.permission ?? span.attributes.permission_level ?? span.attributes.risk_level],
      ["Requires Approval", boolText(span.attributes.requires_approval ?? span.attributes.approval_required ?? span.output.requires_approval)],
      ["Changed Paths", changedPaths(span).join(", ")]
    ];
  }
  if (span.span_type === "context" || span.name === "context.build") {
    const context = objectValue(span.output.context);
    const report = objectValue(context?.budget_report);
    return [
      ["Payload Version", span.output.context_payload_version],
      ["Used", report?.used],
      ["Total Budget", report?.total_budget],
      ["Included Sources", arrayLength(report?.included_items)],
      ["Dropped Sources", arrayLength(report?.dropped_items)],
      ["Fallback", report?.fallback_reason]
    ];
  }
  if (span.span_type === "approval" || span.name === "approval.decision") {
    return [
      ["Decision", span.attributes.decision ?? span.output.decision],
      ["Token", span.attributes.approval_token ?? span.output.approval_token],
      ["Payload Digest", span.attributes.payload_digest ?? span.output.payload_digest],
      ["Reason", span.attributes.reason ?? span.output.reason]
    ];
  }
  if (span.span_type === "checkpoint" || span.name.startsWith("checkpoint.")) {
    return [
      ["Checkpoint", span.attributes.checkpoint_id ?? span.output.checkpoint_id],
      ["Reason", span.attributes.reason ?? span.output.reason],
      ["Passed", boolText(span.attributes.passed ?? span.output.passed)],
      ["Changed Paths", changedPaths(span).join(", ")]
    ];
  }
  return [];
}

function changedPaths(span: TraceSpan): string[] {
  const raw = span.output.changed_paths || span.attributes.changed_paths;
  return Array.isArray(raw) ? raw.map((item) => String(item)).filter(Boolean) : [];
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function arrayLength(value: unknown) {
  return Array.isArray(value) ? value.length : undefined;
}

function moneyValue(value: unknown) {
  return typeof value === "number" ? `$${value.toFixed(6)}` : value;
}

function boolText(value: unknown) {
  if (value === true) return "Yes";
  if (value === false) return "No";
  return value;
}

function formatValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}
