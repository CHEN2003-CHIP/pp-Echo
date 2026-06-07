import type { TraceSpan } from "../../api";
import { formatDuration, spanTypeLabel, statusLabel, statusTone } from "./trace-utils";

export function TraceTimeline({ spans, selectedSpanId, onSelect }: { spans: TraceSpan[]; selectedSpanId: string | null; onSelect: (span: TraceSpan) => void }) {
  const first = spans[0]?.started_at || 0;
  return (
    <section className="trace-inspect-section trace-timeline-list">
      <h3>Timeline</h3>
      {spans.map((span) => (
        <button key={span.span_id} className={span.span_id === selectedSpanId ? "active" : ""} onClick={() => onSelect(span)}>
          <span>{first ? `+${Math.max(0, Math.round((span.started_at - first) * 1000))}ms` : "-"}</span>
          <strong>{spanTypeLabel(span.span_type)} · {span.name}</strong>
          <em className={`trace-status-${statusTone(span.status)}`}>{statusLabel(span.status)}</em>
          <small>{formatDuration(span.duration_ms)}</small>
        </button>
      ))}
    </section>
  );
}
