import type { TraceSpan } from "../../api";
import { formatDuration, formatOffset, spanTypeLabel, statusLabel, statusTone } from "./trace-utils";

export function TraceTimeline({ spans, selectedSpanId, onSelect }: { spans: TraceSpan[]; selectedSpanId: string | null; onSelect: (span: TraceSpan) => void }) {
  const starts = spans.map((span) => span.started_at).filter(Boolean);
  const ends = spans.map((span) => span.ended_at || (span.duration_ms ? span.started_at + span.duration_ms / 1000 : span.started_at)).filter(Boolean);
  const first = starts.length ? Math.min(...starts) : null;
  const last = ends.length ? Math.max(...ends) : null;
  const totalMs = first && last ? Math.max(1, Math.round((last - first) * 1000)) : 1;

  return (
    <section className="trace-inspect-section trace-timeline">
      <h3>Timeline</h3>
      <div className="trace-timeline-head" aria-hidden="true">
        <span>Time</span>
        <span>Span</span>
        <span>Status</span>
        <span>Duration</span>
        <span>Waterfall</span>
      </div>
      <div className="trace-timeline-list">
        {spans.map((span) => {
          const duration = Math.max(1, span.duration_ms || 0);
          const offset = first ? Math.max(0, Math.round((span.started_at - first) * 1000)) : 0;
          const left = Math.min(96, (offset / totalMs) * 100);
          const width = Math.max(2, Math.min(100 - left, (duration / totalMs) * 100));
          const tone = statusTone(span.status);
          return (
            <button key={span.span_id} className={`${span.span_id === selectedSpanId ? "active" : ""} trace-span-tone-${tone}`} onClick={() => onSelect(span)}>
              <span>{formatOffset(span.started_at, first)}</span>
              <strong><small>{spanTypeLabel(span.span_type)}</small>{span.name}</strong>
              <em className={`trace-status-${tone}`}>{statusLabel(span.status)}</em>
              <span>{formatDuration(span.duration_ms)}</span>
              <i className="trace-waterfall-track" aria-hidden="true"><b style={{ left: `${left}%`, width: `${width}%` }} /></i>
            </button>
          );
        })}
      </div>
      {spans.length === 0 ? <p className="muted">No spans.</p> : null}
    </section>
  );
}
