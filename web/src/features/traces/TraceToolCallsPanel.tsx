import type { TraceSpan } from "../../api";
import { formatDuration, safeJsonStringify, statusLabel } from "./trace-utils";

function dedupeToolSpans(spans: TraceSpan[]) {
  const selected = new Map<string, TraceSpan>();
  const anonymous: TraceSpan[] = [];
  for (const span of spans.filter((item) => item.span_type === "tool")) {
    const id = String(span.attributes.tool_call_id || "");
    if (!id) {
      anonymous.push(span);
      continue;
    }
    const current = selected.get(id);
    if (!current || (span.attributes.source === "tool_registry_middleware" && current.attributes.source !== "tool_registry_middleware")) {
      selected.set(id, span);
    }
  }
  return [...selected.values(), ...anonymous];
}

export function TraceToolCallsPanel({ spans }: { spans: TraceSpan[] }) {
  const tools = dedupeToolSpans(spans);
  return <TraceSpanList title="Tool Calls" spans={tools} renderMeta={(span) => {
    const changed = Array.isArray(span.output.changed_paths) ? ` paths:${span.output.changed_paths.length}` : "";
    return `${span.attributes.tool_name || span.name} | ${span.attributes.source || "-"} | ${span.attributes.tool_call_id || "-"} | ${statusLabel(span.status)} | ${formatDuration(span.duration_ms)}${changed}`;
  }} />;
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
