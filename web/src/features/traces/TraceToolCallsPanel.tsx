import type { TraceSpan } from "../../api";
import { formatDuration, safeJsonStringify, statusLabel } from "./trace-utils";

export function TraceToolCallsPanel({ spans }: { spans: TraceSpan[] }) {
  const tools = spans.filter((span) => span.span_type === "tool");
  return <TraceSpanList title="Tool Calls" spans={tools} renderMeta={(span) => `${span.attributes.tool_name || span.name} · ${statusLabel(span.status)} · ${formatDuration(span.duration_ms)}`} />;
}

export function TraceSpanList({ title, spans, renderMeta }: { title: string; spans: TraceSpan[]; renderMeta: (span: TraceSpan) => string }) {
  return (
    <section className="trace-inspect-section trace-span-list">
      <h3>{title}</h3>
      {spans.map((span) => <details key={span.span_id}><summary>{renderMeta(span)}</summary><pre>{safeJsonStringify({ input: span.input, output: span.output, attributes: span.attributes })}</pre></details>)}
      {spans.length === 0 ? <p className="muted">No records.</p> : null}
    </section>
  );
}
