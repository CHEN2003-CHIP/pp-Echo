import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Activity, CircleAlert, Clock3, Code2, Copy, ListChecks, ShieldCheck, X } from "lucide-react";
import type { ActivityItem } from "./activity-types";
import { ActivityTimeline } from "./ActivityTimeline";
import { buildActivitySummary } from "./activity-normalizer";

export function ActivityDetailsPanel({
  items,
  onClose,
  onApprove,
  onReject,
  onOpenArtifact,
  onOpenCheckpoint
}: {
  items: ActivityItem[];
  onClose?: () => void;
  onApprove?: (item: ActivityItem) => void;
  onReject?: (item: ActivityItem) => void;
  onOpenArtifact?: (item: ActivityItem) => void;
  onOpenCheckpoint?: (item: ActivityItem) => void;
}) {
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
        <div className="activity-run-actions">
          <button className={follow ? "active" : ""} onClick={() => setFollow((value) => !value)} type="button">
            <Activity size={14} />
            {follow ? "Following" : "Paused"}
          </button>
          {onClose ? <button onClick={onClose} type="button" title="Close activity"><X size={14} /></button> : null}
        </div>
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
            <ActionRow selected={selected} onApprove={onApprove} onReject={onReject} onOpenArtifact={onOpenArtifact} onOpenCheckpoint={onOpenCheckpoint} />
            <DetailSection title="Metadata">
              <dl>
                <div><dt>Activity ID</dt><dd>{selected.activityId || selected.id}</dd></div>
                <div><dt>Parent</dt><dd>{selected.parentActivityId || "none"}</dd></div>
                <div><dt>Run</dt><dd>{selected.runId || "unknown"}</dd></div>
                <div><dt>Duration</dt><dd>{selected.durationLabel || "n/a"}</dd></div>
                <div><dt>Events</dt><dd>{selected.eventCount}</dd></div>
                <div><dt>Steps</dt><dd>{selected.entries.length}</dd></div>
              </dl>
            </DetailSection>
            <DetailSection title="Input">
              <pre>{detailLines(selected, ["Command:", "Path:", "Tool:", "Token:", "Child session:"]) || "No input summary."}</pre>
            </DetailSection>
            <DetailSection title="Result">
              <pre>{detailLines(selected, ["Exit:", "Changed:", "Step status:"]) || selected.detail || "No result summary yet."}</pre>
            </DetailSection>
            <DetailSection title="Safe Raw Event">
              {selected.entries.length ? selected.entries.map((entry) => (
                <details key={entry.id} className="activity-raw-event">
                  <summary><span>{entry.rawType || entry.label}</span><Copy size={12} /></summary>
                  <pre>{entry.safeRaw || "No raw event available."}</pre>
                </details>
              )) : <pre>No raw event available.</pre>}
            </DetailSection>
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

function ActionRow({
  selected,
  onApprove,
  onReject,
  onOpenArtifact,
  onOpenCheckpoint
}: {
  selected: ActivityItem;
  onApprove?: (item: ActivityItem) => void;
  onReject?: (item: ActivityItem) => void;
  onOpenArtifact?: (item: ActivityItem) => void;
  onOpenCheckpoint?: (item: ActivityItem) => void;
}) {
  if (!onApprove && !onReject && !onOpenArtifact && !onOpenCheckpoint) return null;
  return (
    <div className="activity-detail-actions">
      {selected.phase === "approval" && onApprove ? <button onClick={() => onApprove(selected)} type="button">Approve</button> : null}
      {selected.phase === "approval" && onReject ? <button onClick={() => onReject(selected)} type="button">Reject</button> : null}
      {selected.phase === "artifact" && onOpenArtifact ? <button onClick={() => onOpenArtifact(selected)} type="button">Open artifact</button> : null}
      {selected.phase === "checkpoint" && onOpenCheckpoint ? <button onClick={() => onOpenCheckpoint(selected)} type="button">Open checkpoint</button> : null}
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="activity-detail-section">
      <h5>{title}</h5>
      {children}
    </section>
  );
}

function detailLines(item: ActivityItem, prefixes: string[]) {
  const lines = item.detail.split("\n").filter((line) => prefixes.some((prefix) => line.startsWith(prefix)));
  return Array.from(new Set(lines)).join("\n");
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
