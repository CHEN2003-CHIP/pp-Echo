import type { TraceDetail, TraceSpan } from "../../api";
import { TraceApprovalPanel } from "./TraceApprovalPanel";
import { TraceArtifactsPanel } from "./TraceArtifactsPanel";
import { TraceCheckpointPanel } from "./TraceCheckpointPanel";
import { TraceDiagnosisPanel } from "./TraceDiagnosisPanel";
import { TraceMemoryPanel } from "./TraceMemoryPanel";
import { TraceModelRuntimeCard } from "./TraceModelRuntimeCard";
import { TraceRawJsonPanel } from "./TraceRawJsonPanel";
import { TraceSpanInspector } from "./TraceSpanInspector";
import { TraceSummaryCards } from "./TraceSummaryCards";
import { TraceTimeline } from "./TraceTimeline";
import { TraceToolCallsPanel } from "./TraceToolCallsPanel";

export function TraceRunDetail({ detail, selectedSpan, onSelectSpan }: { detail: TraceDetail | null; selectedSpan: TraceSpan | null; onSelectSpan: (span: TraceSpan) => void }) {
  if (!detail) return <main className="trace-inspect-detail"><div className="empty"><h2>No trace selected</h2><p>Select a run from the list.</p></div></main>;
  return (
    <main className="trace-inspect-detail">
      <TraceSummaryCards summary={detail.summary} />
      <TraceModelRuntimeCard detail={detail} />
      <TraceDiagnosisPanel diagnosis={detail.diagnosis} warnings={detail.warnings} />
      <div className="trace-inspect-two-col">
        <TraceTimeline spans={detail.spans} selectedSpanId={selectedSpan?.span_id || null} onSelect={onSelectSpan} />
        <TraceSpanInspector span={selectedSpan} />
      </div>
      <TraceToolCallsPanel spans={detail.spans} />
      <TraceApprovalPanel spans={detail.spans} />
      <TraceMemoryPanel spans={detail.spans} />
      <TraceCheckpointPanel spans={detail.spans} />
      <TraceArtifactsPanel artifacts={detail.artifacts} />
      <TraceRawJsonPanel detail={detail} />
    </main>
  );
}
