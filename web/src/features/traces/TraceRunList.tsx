import type { TraceRunSummary } from "../../api";
import { compactId, formatDuration, formatRelativeTime } from "./trace-utils";
import { tokenTotal } from "./trace-display";
import { StatusBadge } from "./StatusBadge";
import { EmptyState } from "./EmptyState";

export function TraceRunList({
  runs,
  selectedRunId,
  onSelect,
  search,
  onSearch,
  statusFilter,
  onStatusFilter
}: {
  runs: TraceRunSummary[];
  selectedRunId: string | null;
  onSelect: (runId: string) => void;
  search: string;
  onSearch: (value: string) => void;
  statusFilter: string;
  onStatusFilter: (value: string) => void;
}) {
  const filtered = runs.filter((run) => {
    const matchesStatus = statusFilter === "all" || run.status === statusFilter;
    const haystack = `${run.run_id} ${run.session_id || ""} ${run.user_goal_preview}`.toLowerCase();
    return matchesStatus && haystack.includes(search.toLowerCase());
  });
  return (
    <aside className="trace-sidebar trace-card">
      <div className="trace-card-header">
        <div>
          <h2>Runs</h2>
          <p>Recent agent traces</p>
        </div>
        <span className="trace-badge trace-badge-primary">{filtered.length}</span>
      </div>
      <div className="trace-card-body">
        <div className="trace-run-filters">
          <input value={search} onChange={(event) => onSearch(event.target.value)} placeholder="Search traces" />
          <select value={statusFilter} onChange={(event) => onStatusFilter(event.target.value)}>
            {["all", "ok", "error", "pending", "blocked", "running", "cancelled"].map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </div>
        <div className="trace-run-list">
          {filtered.map((run) => (
            <button key={run.run_id} type="button" className={run.run_id === selectedRunId ? "active" : ""} onClick={() => onSelect(run.run_id)}>
              <span className="trace-run-name">
                <strong>{compactId(run.run_id)}</strong>
                <StatusBadge status={run.status} />
              </span>
              <span className="trace-run-preview">{run.user_goal_preview || run.session_id || "Trace run"}</span>
              <span className="trace-run-meta">
                <span>{formatRelativeTime(run.started_at)}</span>
                <span>{formatDuration(run.duration_ms)}</span>
              </span>
              <span className="trace-run-meta">
                <span>{run.model || "Model not captured"}</span>
                <span>{tokenTotal(run).toLocaleString()} tokens</span>
              </span>
            </button>
          ))}
          {!filtered.length ? <EmptyState title="No traces found">Adjust search or status filters.</EmptyState> : null}
        </div>
      </div>
    </aside>
  );
}
