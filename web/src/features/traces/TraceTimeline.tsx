import { Bot, Braces, CheckCircle2, CircleDot, Cpu, Database, ShieldCheck, Wrench } from "lucide-react";
import type { TraceSpan } from "../../api";
import { formatDuration, formatOffset } from "./trace-utils";
import { spanSubtitle, timelineMaxDuration } from "./trace-display";
import { StatusBadge } from "./StatusBadge";
import { EmptyState } from "./EmptyState";

export function TraceTimeline({ spans, selectedSpanId, onSelect }: { spans: TraceSpan[]; selectedSpanId: string | null; onSelect: (span: TraceSpan) => void }) {
  const maxDuration = timelineMaxDuration(spans);
  const baseStartedAt = spans[0]?.started_at || null;
  return (
    <section className="trace-card">
      <div className="trace-card-header">
        <div>
          <h2>Execution Timeline</h2>
          <p>Run steps, duration, status, and relative timing</p>
        </div>
        <span className="trace-badge trace-badge-neutral">{spans.length} spans</span>
      </div>
      <div className="trace-card-body trace-timeline-list">
        {spans.map((span) => {
          const pct = Math.max(4, Math.min(100, ((span.duration_ms || 0) / maxDuration) * 100));
          const Icon = iconForSpan(span.span_type);
          return (
            <button key={span.span_id} type="button" className={`trace-timeline-row ${span.span_id === selectedSpanId ? "selected" : ""}`} onClick={() => onSelect(span)}>
              <span className="trace-span-icon"><Icon size={15} /></span>
              <span className="trace-span-main">
                <strong>{span.name}</strong>
                <small>{spanSubtitle(span)}</small>
              </span>
              <StatusBadge status={span.status} />
              <span className="trace-span-duration">{formatDuration(span.duration_ms)}</span>
              <span className="trace-waterfall" title={formatOffset(span.started_at, baseStartedAt)}>
                <i style={{ width: `${pct}%` }} />
              </span>
            </button>
          );
        })}
        {!spans.length ? <EmptyState title="No timeline spans">This run did not capture execution spans.</EmptyState> : null}
      </div>
    </section>
  );
}

function iconForSpan(type: string) {
  if (type === "llm") return Cpu;
  if (type === "tool") return Wrench;
  if (type === "context") return Braces;
  if (type === "memory") return Database;
  if (type === "approval" || type === "policy") return ShieldCheck;
  if (type === "subagent") return Bot;
  if (type === "turn" || type === "run") return CircleDot;
  return CheckCircle2;
}
