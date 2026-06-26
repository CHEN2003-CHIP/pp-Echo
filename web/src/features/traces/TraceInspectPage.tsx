import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Copy, PanelLeftClose, PanelLeftOpen, RefreshCw } from "lucide-react";
import { api, type TraceDetail, type TraceRunSummary, type TraceSpan } from "../../api";
import { TraceRunDetail } from "./TraceRunDetail";
import { TraceRunList } from "./TraceRunList";
import { compactId, statusLabel } from "./trace-utils";

export function TraceInspectPage({ activeSessionId, initialRunId, onBack }: { activeSessionId?: string; initialRunId?: string | null; onBack: () => void }) {
  const [runs, setRuns] = useState<TraceRunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(initialRunId || null);
  const [detail, setDetail] = useState<TraceDetail | null>(null);
  const [selectedSpan, setSelectedSpan] = useState<TraceSpan | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [error, setError] = useState("");
  const [isRunListCollapsed, setIsRunListCollapsed] = useState(false);

  const currentStatus = detail?.summary?.status || runs.find((run) => run.run_id === selectedRunId)?.status;
  const shouldPoll = currentStatus === "running" || currentStatus === "pending";

  useEffect(() => { refresh().catch((err) => setError(errorMessage(err))); }, [activeSessionId]);
  useEffect(() => {
    if (!selectedRunId) return;
    loadDetail(selectedRunId).catch((err) => setError(errorMessage(err)));
  }, [selectedRunId]);
  useEffect(() => {
    if (!shouldPoll || !selectedRunId) return;
    const timer = window.setInterval(() => loadDetail(selectedRunId).catch((err) => setError(errorMessage(err))), 1500);
    return () => window.clearInterval(timer);
  }, [shouldPoll, selectedRunId]);

  const headerRun = useMemo(() => runs.find((run) => run.run_id === selectedRunId), [runs, selectedRunId]);

  async function refresh() {
    setError("");
    let payload = await api.traces({ limit: 80, sessionId: activeSessionId || undefined }).catch(async () => api.traces({ limit: 80 }));
    setRuns(payload.runs);
    const nextRunId = selectedRunId || initialRunId || payload.runs[0]?.run_id || null;
    setSelectedRunId(nextRunId);
    if (nextRunId) await loadDetail(nextRunId);
  }

  async function loadDetail(runId: string) {
    const loaded = await api.traceDetail(runId);
    setDetail(loaded);
    setSelectedSpan((current) => loaded.spans.find((span) => span.span_id === current?.span_id) || loaded.spans[0] || null);
  }

  function copyJson() {
    navigator.clipboard?.writeText(JSON.stringify(detail, null, 2)).catch(() => undefined);
  }

  return (
    <div className="trace-inspect-page">
      <header className="trace-inspect-toolbar">
        <button onClick={onBack}><ArrowLeft size={16} />返回会话</button>
        <button onClick={() => refresh().catch((err) => setError(errorMessage(err)))}><RefreshCw size={16} />刷新</button>
        <button onClick={() => setIsRunListCollapsed((value) => !value)} title={isRunListCollapsed ? "Show run list" : "Collapse run list"}>
          {isRunListCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          {isRunListCollapsed ? "Runs" : "Hide runs"}
        </button>
        <span>run {selectedRunId ? compactId(selectedRunId) : "-"}</span>
        <span>{currentStatus ? statusLabel(currentStatus) : "-"}</span>
        <button onClick={copyJson} disabled={!detail}><Copy size={16} />复制 JSON</button>
      </header>
      {error ? <div className="trace-inspect-error">{error}</div> : null}
      <div className={`trace-inspect-layout ${isRunListCollapsed ? "trace-inspect-layout-collapsed" : ""}`}>
        <TraceRunList runs={runs} selectedRunId={selectedRunId} onSelect={setSelectedRunId} search={search} onSearch={setSearch} statusFilter={statusFilter} onStatusFilter={setStatusFilter} />
        <TraceRunDetail detail={detail || (headerRun ? null : null)} selectedSpan={selectedSpan} onSelectSpan={setSelectedSpan} />
      </div>
    </div>
  );
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}
