import { useState } from "react";
import type { TraceDetail, TraceSpan } from "../../api";
import { TraceApprovalPanel } from "./TraceApprovalPanel";
import { TraceArtifactsPanel } from "./TraceArtifactsPanel";
import { TraceCapabilityPanel } from "./TraceCapabilityPanel";
import { TraceCheckpointPanel } from "./TraceCheckpointPanel";
import { TraceContextBudgetPanel } from "./TraceContextBudgetPanel";
import { TraceDiagnosisPanel } from "./TraceDiagnosisPanel";
import { TraceMemoryPanel } from "./TraceMemoryPanel";
import { TraceModelRuntimeCard } from "./TraceModelRuntimeCard";
import { TraceRawJsonPanel } from "./TraceRawJsonPanel";
import { TraceSpanInspector } from "./TraceSpanInspector";
import { TraceSummaryCards } from "./TraceSummaryCards";
import { TraceTimeline } from "./TraceTimeline";
import { TraceToolCallsPanel } from "./TraceToolCallsPanel";
import { compactId, formatRelativeTime, statusLabel } from "./trace-utils";

type TraceTab = "tools" | "context" | "approval" | "checkpoints" | "memory" | "artifacts" | "raw";

export function TraceRunDetail({ detail, selectedSpan, onSelectSpan }: { detail: TraceDetail | null; selectedSpan: TraceSpan | null; onSelectSpan: (span: TraceSpan) => void }) {
  const [tab, setTab] = useState<TraceTab>("tools");
  if (!detail) return <main className="trace-inspect-detail"><div className="empty"><h2>No trace selected</h2><p>Select a run from the list.</p></div></main>;

  const tabs: Array<[TraceTab, string]> = [["tools", "Tools"], ["context", "Context"], ["approval", "Approval"], ["checkpoints", "Checkpoints"], ["memory", "Memory"], ["artifacts", "Artifacts"], ["raw", "Raw JSON"]];

  return (
    <main className="trace-inspect-detail">
      <section className="trace-run-head">
        <div>
          <h2>Run {compactId(detail.summary?.run_id || String(detail.run?.run_id || ""))}</h2>
          <p>{detail.summary?.user_goal_preview || "No goal preview recorded."}</p>
        </div>
        <dl>
          <div><dt>Status</dt><dd>{detail.summary ? statusLabel(detail.summary.status) : "-"}</dd></div>
          <div><dt>Session</dt><dd>{detail.summary?.session_id ? compactId(detail.summary.session_id) : "-"}</dd></div>
          <div><dt>Started</dt><dd>{formatRelativeTime(detail.summary?.started_at)}</dd></div>
          <div><dt>Workspace</dt><dd>{detail.summary?.workspace || "-"}</dd></div>
        </dl>
      </section>
      <TraceSummaryCards summary={detail.summary} />
      <div className="trace-debug-console">
        <aside className="trace-run-support">
          <TraceModelRuntimeCard detail={detail} />
          <TraceCapabilityPanel detail={detail} />
        </aside>
        <section className="trace-debug-main">
          <TraceTimeline spans={detail.spans} selectedSpanId={selectedSpan?.span_id || null} onSelect={onSelectSpan} />
          <div className="trace-tabs" role="tablist" aria-label="Trace detail panels">
            {tabs.map(([value, label]) => <button key={value} className={tab === value ? "active" : ""} onClick={() => setTab(value)}>{label}</button>)}
          </div>
          {tab === "tools" ? <TraceToolCallsPanel spans={detail.spans} selectedSpanId={selectedSpan?.span_id || null} onSelectSpan={onSelectSpan} /> : null}
          {tab === "context" ? <TraceContextBudgetPanel detail={detail} /> : null}
          {tab === "approval" ? <TraceApprovalPanel spans={detail.spans} /> : null}
          {tab === "checkpoints" ? <TraceCheckpointPanel spans={detail.spans} /> : null}
          {tab === "memory" ? <TraceMemoryPanel spans={detail.spans} /> : null}
          {tab === "artifacts" ? <TraceArtifactsPanel artifacts={detail.artifacts} /> : null}
          {tab === "raw" ? <TraceRawJsonPanel detail={detail} /> : null}
        </section>
        <aside className="trace-debug-side">
          <TraceSpanInspector span={selectedSpan} />
          <TraceDiagnosisPanel diagnosis={detail.diagnosis} warnings={detail.warnings} />
        </aside>
      </div>
    </main>
  );
}
