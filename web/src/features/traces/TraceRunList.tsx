import type { TraceRunSummary } from "../../api";
import { compactId, formatDuration, formatRelativeTime, statusLabel, statusTone } from "./trace-utils";

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
    <aside className="trace-inspect-sidebar">
      <div className="trace-inspect-filters">
        <input value={search} onChange={(event) => onSearch(event.target.value)} placeholder="Search traces" />
        <select value={statusFilter} onChange={(event) => onStatusFilter(event.target.value)}>
          {["all", "ok", "error", "pending", "blocked", "running", "cancelled"].map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
      </div>
      <div className="trace-inspect-run-list">
        {filtered.map((run) => (
          <button key={run.run_id} className={run.run_id === selectedRunId ? "active" : ""} onClick={() => onSelect(run.run_id)}>
            <strong>{compactId(run.run_id)} <em className={`trace-status-${statusTone(run.status)}`}>{statusLabel(run.status)}</em></strong>
            <span>{run.user_goal_preview || run.session_id || "trace run"}</span>
            <small>{formatRelativeTime(run.started_at)} · {formatDuration(run.duration_ms)}</small>
          </button>
        ))}
      </div>
    </aside>
  );
}
