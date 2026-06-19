import { Bot, CheckCircle2, ChevronRight, CircleAlert, CircleDashed, Clock3, Code2, FileWarning, GitBranch, Layers3, PlayCircle, ShieldCheck, Sparkles } from "lucide-react";
import { RichMessageAttachments } from "../../rich-text";
import type { ActivityItem, ActivityPhase, ActivityStatus } from "./activity-types";

export function ActivityCard({ item }: { item: ActivityItem }) {
  const Icon = phaseIcon(item.phase);
  const open = item.running || item.status === "error" || item.status === "pending";
  return (
    <details className={`activity-card ${item.phase} ${item.status}`} open={open}>
      <summary>
        <span className="activity-card-icon"><Icon size={15} /></span>
        <span className="activity-card-main">
          <strong>{item.title}</strong>
          <small>{item.summary}</small>
        </span>
        <span className={`activity-status ${item.status}`}>{statusCopy(item.status)}</span>
        <ChevronRight className="activity-chevron" size={15} />
      </summary>
      <div className="activity-card-body">
        {item.phase === "reasoning" ? <ReasoningBlock item={item} /> : null}
        {item.entries.length > 0 ? (
          <ol className="activity-step-list">
            {item.entries.map((entry) => (
              <li className={`activity-step ${entry.status}`} key={entry.id}>
                <span className="activity-step-dot" />
                <div className="activity-step-content">
                  <div className="activity-step-head">
                    <strong>{entry.label}</strong>
                    <small>{[entry.rawType, entry.durationLabel].filter(Boolean).join(" · ")}</small>
                  </div>
                  {entry.detail ? <pre>{entry.detail}</pre> : null}
                  {entry.attachments?.length ? <RichMessageAttachments attachments={entry.attachments} /> : null}
                </div>
              </li>
            ))}
          </ol>
        ) : item.detail ? (
          <pre className="activity-detail-pre">{item.detail}</pre>
        ) : null}
        {item.attachments?.length ? <RichMessageAttachments attachments={item.attachments} /> : null}
      </div>
    </details>
  );
}

export function ReasoningBlock({ item }: { item: ActivityItem }) {
  return (
    <section className={`reasoning-block ${item.running ? "live" : ""}`}>
      <div className="reasoning-pulse"><Sparkles size={14} /></div>
      <div>
        <strong>{item.running ? "Thinking through the next step" : "Reasoning summary"}</strong>
        <p>{item.summary || "Public progress from the runtime."}</p>
      </div>
    </section>
  );
}

function phaseIcon(phase: ActivityPhase) {
  if (phase === "reasoning") return Sparkles;
  if (phase === "planning") return Layers3;
  if (phase === "tool") return Code2;
  if (phase === "approval") return ShieldCheck;
  if (phase === "artifact") return FileWarning;
  if (phase === "checkpoint") return GitBranch;
  if (phase === "subagent") return Bot;
  if (phase === "queue") return Clock3;
  if (phase === "memory") return CircleDashed;
  return PlayCircle;
}

function statusCopy(status: ActivityStatus) {
  if (status === "running") return "Running";
  if (status === "pending") return "Pending";
  if (status === "success") return "Done";
  if (status === "warning") return "Review";
  if (status === "error") return "Failed";
  if (status === "cancelled") return "Cancelled";
  return status;
}

export function StatusIcon({ status }: { status: ActivityStatus }) {
  if (status === "success") return <CheckCircle2 size={14} />;
  if (status === "error" || status === "cancelled") return <CircleAlert size={14} />;
  return <CircleDashed size={14} />;
}
