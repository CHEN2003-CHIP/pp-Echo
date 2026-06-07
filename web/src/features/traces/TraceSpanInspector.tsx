import type { TraceSpan } from "../../api";
import { safeJsonStringify, spanTypeLabel, statusLabel } from "./trace-utils";

export function TraceSpanInspector({ span }: { span: TraceSpan | null }) {
  if (!span) return <section className="trace-inspect-section"><h3>Span</h3><p className="muted">Select a timeline span.</p></section>;
  return (
    <section className="trace-inspect-section trace-span-inspector">
      <h3>{span.name}</h3>
      <dl>
        <dt>Type</dt><dd>{spanTypeLabel(span.span_type)}</dd>
        <dt>Status</dt><dd>{statusLabel(span.status)}</dd>
        <dt>Error</dt><dd>{span.error_message || "-"}</dd>
      </dl>
      <details open><summary>Attributes</summary><pre>{safeJsonStringify(span.attributes)}</pre></details>
      <details><summary>Input</summary><pre>{safeJsonStringify(span.input)}</pre></details>
      <details><summary>Output</summary><pre>{safeJsonStringify(span.output)}</pre></details>
    </section>
  );
}
