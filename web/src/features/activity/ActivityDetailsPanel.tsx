import { useEffect, useMemo, useState } from "react";
import { Activity, CircleAlert, Clock3, Code2, ListChecks, ShieldCheck } from "lucide-react";
import type { ActivityItem } from "./activity-types";
import { ActivityTimeline } from "./ActivityTimeline";
import { buildActivitySummary } from "./activity-normalizer";

export function ActivityDetailsPanel({ items }: { items: ActivityItem[] }) {
  const [selectedId, setSelectedId] = useState("");
  const [follow, setFollow] = useState(true);
  const summary = useMemo(() => buildActivitySummary(items), [items]);
  const selected = items.find((item) => item.id === selectedId) || items[items.length - 1];

  useEffect(() => {
    if (follow) setSelectedId(items[items.length - 1]?.id || "");
  }, [items, follow]);

  return (
    <section className="activity-details-panel">
      <header className={`activity-run-summary ${summary.status}`}>
        <div>
          <small>ACTIVITY</small>
          <h3>{summary.status === "running" ? "Run in progress" : summary.activityCount ? "Run activity" : "Waiting for activity"}</h3>
          <p>{summary.durationLabel || "No runtime events yet"}</p>
        </div>
        <button className={follow ? "active" : ""} onClick={() => setFollow((value) => !value)} type="button">
          <Activity size={14} />
          {follow ? "Following" : "Paused"}
        </button>
      </header>

      <div className="activity-summary-grid">
        <Metric icon={ListChecks} label="Events" value={summary.eventCount} />
        <Metric icon={Code2} label="Tools" value={summary.toolCount} />
        <Metric icon={ShieldCheck} label="Approvals" value={summary.approvalCount} />
        <Metric icon={CircleAlert} label="Errors" value={summary.errorCount} />
      </div>

      <ActivityTimeline
        items={items}
        selectedId={selected?.id || ""}
        onSelect={(item) => {
          setSelectedId(item.id);
          setFollow(false);
        }}
      />

      <section className="activity-selected-detail">
        {selected ? (
          <>
            <div className="activity-selected-head">
              <div>
                <small>{selected.phase.toUpperCase()}</small>
                <h4>{selected.title}</h4>
              </div>
              <span className={`activity-status ${selected.status}`}>{selected.status}</span>
            </div>
            <p>{selected.summary}</p>
            <dl>
              <div><dt>Activity ID</dt><dd>{selected.activityId || selected.id}</dd></div>
              <div><dt>Run</dt><dd>{selected.runId || "unknown"}</dd></div>
              <div><dt>Duration</dt><dd>{selected.durationLabel || "n/a"}</dd></div>
              <div><dt>Steps</dt><dd>{selected.entries.length}</dd></div>
            </dl>
            {selected.detail ? <pre>{selected.detail}</pre> : null}
          </>
        ) : (
          <div className="activity-detail-empty">
            <Clock3 size={18} />
            <span>No activity selected.</span>
          </div>
        )}
      </section>
    </section>
  );
}

function Metric({ icon: Icon, label, value }: { icon: typeof Activity; label: string; value: number }) {
  return (
    <div className="activity-metric">
      <Icon size={14} />
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
