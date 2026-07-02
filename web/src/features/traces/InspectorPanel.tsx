import type { TraceDetail, TraceSpan } from "../../api";
import { formatDuration } from "./trace-utils";
import { shortJson, textValue } from "./trace-display";
import { EmptyState } from "./EmptyState";
import { StatusBadge } from "./StatusBadge";

export function InspectorPanel({ detail, span }: { detail: TraceDetail | null; span: TraceSpan | null }) {
  return (
    <aside className="trace-right-panel">
      <section className="trace-card">
        <div className="trace-card-header">
          <div>
            <h2>Selected Span</h2>
            <p>{span?.name || "No span selected"}</p>
          </div>
          {span ? <StatusBadge status={span.status} /> : null}
        </div>
        <div className="trace-card-body">
          {span ? (
            <dl className="trace-kv-list">
              <div><dt>Type</dt><dd>{span.span_type}</dd></div>
              <div><dt>Duration</dt><dd>{formatDuration(span.duration_ms)}</dd></div>
              <div><dt>Provider</dt><dd>{textValue(span.attributes?.provider || span.output?.provider)}</dd></div>
              <div><dt>Model</dt><dd>{textValue(span.attributes?.model || span.output?.model)}</dd></div>
              <div><dt>Input</dt><dd>{textValue(span.attributes?.input_tokens || span.output?.input_tokens)}</dd></div>
              <div><dt>Output</dt><dd>{textValue(span.attributes?.output_tokens || span.output?.output_tokens)}</dd></div>
            </dl>
          ) : <EmptyState title="Select a timeline item to inspect details." />}
        </div>
      </section>

      <section className="trace-card">
        <div className="trace-card-header">
          <div>
            <h2>Diagnosis</h2>
            <p>Warnings and runtime findings</p>
          </div>
          <StatusBadge status={detail?.diagnosis?.some((item) => item.severity === "error") ? "error" : "ok"} label={detail?.diagnosis?.length ? `${detail.diagnosis.length}` : "OK"} />
        </div>
        <div className="trace-card-body trace-diagnosis-list">
          {detail?.diagnosis?.map((item) => (
            <article key={`${item.code}-${item.title}`}>
              <strong>{item.title}</strong>
              <p>{item.message}</p>
            </article>
          ))}
          {detail?.warnings?.map((warning) => <article key={warning}><strong>Warning</strong><p>{warning}</p></article>)}
          {!detail?.diagnosis?.length && !detail?.warnings?.length ? <EmptyState title="No diagnosis">No errors, approval stalls, or high-risk findings were captured.</EmptyState> : null}
        </div>
      </section>

      <section className="trace-card">
        <div className="trace-card-header">
          <div>
            <h2>Attributes</h2>
            <p>Selected span JSON preview</p>
          </div>
        </div>
        <div className="trace-card-body">
          <pre className="trace-codebox">{span ? shortJson({ attributes: span.attributes, input: span.input, output: span.output }) : "{}"}</pre>
        </div>
      </section>
    </aside>
  );
}
