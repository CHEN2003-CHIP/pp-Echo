import { useState } from "react";
import type { TraceDetail, TraceSpan } from "../../api";
import { ContextInspector } from "./ContextInspector";
import { EmptyState } from "./EmptyState";
import { rawJson } from "./trace-display";
import { TraceMemoryPanel } from "./TraceMemoryPanel";
import { TraceTabs, type TraceTab } from "./TraceTabs";
import { TraceTimeline } from "./TraceTimeline";
import { TraceToolCallsPanel } from "./TraceToolCallsPanel";

export function TraceRunDetail({ detail, selectedSpan, onSelectSpan }: { detail: TraceDetail | null; selectedSpan: TraceSpan | null; onSelectSpan: (span: TraceSpan) => void }) {
  const [tab, setTab] = useState<TraceTab>("context");
  if (!detail) {
    return (
      <main className="trace-main-stack">
        <EmptyState title="No trace selected">Select a run from the list.</EmptyState>
      </main>
    );
  }

  return (
    <main className="trace-main-stack">
      <TraceTimeline spans={detail.spans} selectedSpanId={selectedSpan?.span_id || null} onSelect={onSelectSpan} />

      <section className="trace-card">
        <div className="trace-card-header trace-card-header-with-tabs">
          <div>
            <h2>Run Details</h2>
            <p>Context inspector, tools, memory, and sanitized raw trace JSON</p>
          </div>
          <TraceTabs value={tab} onChange={setTab} />
        </div>
        <div className="trace-card-body">
          {tab === "overview" ? <OverviewPanel detail={detail} /> : null}
          {tab === "context" ? <ContextInspector detail={detail} /> : null}
          {tab === "tools" ? <TraceToolCallsPanel spans={detail.spans} selectedSpanId={selectedSpan?.span_id || null} onSelectSpan={onSelectSpan} /> : null}
          {tab === "memory" ? <TraceMemoryPanel spans={detail.spans} /> : null}
          {tab === "raw" ? <RawJsonPanel detail={detail} /> : null}
        </div>
      </section>
    </main>
  );
}

function OverviewPanel({ detail }: { detail: TraceDetail }) {
  const summary = detail.summary;
  return (
    <div className="trace-overview-grid">
      <article className="trace-soft-panel">
        <h3>Run</h3>
        <dl className="trace-kv-list">
          <div><dt>Run ID</dt><dd>{summary?.run_id || "Not captured"}</dd></div>
          <div><dt>Session</dt><dd>{summary?.session_id || "Not captured"}</dd></div>
          <div><dt>Workspace</dt><dd>{summary?.workspace || "Not captured"}</dd></div>
          <div><dt>Goal</dt><dd>{summary?.user_goal_preview || "No goal preview recorded."}</dd></div>
        </dl>
      </article>
      <article className="trace-soft-panel">
        <h3>Activity</h3>
        <dl className="trace-kv-list">
          <div><dt>Tools</dt><dd>{summary?.tool_calls || 0}</dd></div>
          <div><dt>Memory</dt><dd>{summary?.memory_recall_count || 0}</dd></div>
          <div><dt>Checkpoints</dt><dd>{summary?.checkpoint_count || 0}</dd></div>
          <div><dt>Artifacts</dt><dd>{detail.artifacts.length}</dd></div>
        </dl>
      </article>
    </div>
  );
}

function RawJsonPanel({ detail }: { detail: TraceDetail }) {
  return (
    <section className="trace-raw-panel">
      <pre className="trace-codebox trace-codebox-large">{rawJson(detail)}</pre>
    </section>
  );
}
