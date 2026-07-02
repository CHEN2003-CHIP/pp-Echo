import { useEffect, useMemo, useState } from "react";
import { api, type TraceDetail, type TraceRunSummary, type TraceSpan } from "../../api";
import { InspectorPanel } from "./InspectorPanel";
import { summaryFromDetail } from "./trace-display";
import { TraceInspectHeader } from "./TraceInspectHeader";
import { TraceRunDetail } from "./TraceRunDetail";
import { TraceRunList } from "./TraceRunList";
import { TraceSummaryMetrics } from "./TraceSummaryMetrics";

export function TraceInspectPage({ activeSessionId, initialRunId, onBack }: { activeSessionId?: string; initialRunId?: string | null; onBack: () => void }) {
  const [runs, setRuns] = useState<TraceRunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(initialRunId || null);
  const [detail, setDetail] = useState<TraceDetail | null>(null);
  const [selectedSpan, setSelectedSpan] = useState<TraceSpan | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [error, setError] = useState("");

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

  const headerRun = useMemo(() => runs.find((run) => run.run_id === selectedRunId) || null, [runs, selectedRunId]);
  const activeSummary = summaryFromDetail(detail, headerRun);

  async function refresh() {
    setError("");
    const payload = await api.traces({ limit: 80, sessionId: activeSessionId || undefined }).catch(async () => api.traces({ limit: 80 }));
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
      <TraceInspectHeader
        run={activeSummary}
        selectedRunId={selectedRunId}
        onBack={onBack}
        onRefresh={() => refresh().catch((err) => setError(errorMessage(err)))}
        onCopyJson={copyJson}
        canCopy={Boolean(detail)}
      />
      {error ? <div className="trace-inspect-error">{error}</div> : null}
      <TraceSummaryMetrics summary={activeSummary} />
      <div className="trace-inspect-layout">
        <TraceRunList runs={runs} selectedRunId={selectedRunId} onSelect={setSelectedRunId} search={search} onSearch={setSearch} statusFilter={statusFilter} onStatusFilter={setStatusFilter} />
        <TraceRunDetail detail={detail} selectedSpan={selectedSpan} onSelectSpan={setSelectedSpan} />
        <InspectorPanel detail={detail} span={selectedSpan} />
      </div>
    </div>
  );
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}
