import { ArrowLeft, Copy, RefreshCw } from "lucide-react";
import type { TraceRunSummary } from "../../api";
import { compactId } from "./trace-utils";
import { StatusBadge } from "./StatusBadge";

export function TraceInspectHeader({
  run,
  selectedRunId,
  onBack,
  onRefresh,
  onCopyJson,
  canCopy
}: {
  run: TraceRunSummary | null;
  selectedRunId: string | null;
  onBack: () => void;
  onRefresh: () => void;
  onCopyJson: () => void;
  canCopy: boolean;
}) {
  const runId = run?.run_id || selectedRunId || "";
  return (
    <header className="trace-topbar">
      <div className="trace-header-copy">
        <div className="trace-crumbs">PP-ECHO / TRACEINSPECT / {runId ? compactId(runId) : "NO RUN"}</div>
        <div className="trace-title-row">
          <h1>TraceInspect</h1>
          <StatusBadge status={run?.status} />
          <span className="trace-badge trace-badge-neutral">Agent trace audit</span>
        </div>
        <p>
          Run {runId ? compactId(runId) : "Not captured"}
          {run?.session_id ? ` / Session ${compactId(run.session_id)}` : ""}
        </p>
      </div>
      <div className="trace-actions">
        <button type="button" className="trace-button" onClick={onBack}><ArrowLeft size={16} />Back</button>
        <button type="button" className="trace-button" onClick={onRefresh}><RefreshCw size={16} />Refresh</button>
        <button type="button" className="trace-button trace-button-primary" onClick={onCopyJson} disabled={!canCopy}><Copy size={16} />Copy JSON</button>
      </div>
    </header>
  );
}
