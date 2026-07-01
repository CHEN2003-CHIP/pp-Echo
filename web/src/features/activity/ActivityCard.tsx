import { useEffect, useMemo, useState } from "react";
import { Bot, CheckCircle2, ChevronDown, CircleAlert, CircleDashed, Clock3, Code2, FileWarning, GitBranch, Layers3, PlayCircle, ShieldCheck, Sparkles } from "lucide-react";
import { RichMessageAttachments } from "../../rich-text";
import type { ActivityItem, ActivityPhase, ActivityStatus } from "./activity-types";

export function ActivityCard({ item }: { item: ActivityItem }) {
  const lines = buildThinkingLines(item);
  const [expanded, setExpanded] = useState(item.running);

  useEffect(() => {
    if (item.running) {
      setExpanded(true);
      return;
    }
    if (item.status === "success" || item.status === "error" || item.status === "cancelled") {
      setExpanded(false);
    }
  }, [item.id, item.running, item.status]);

  const summary = useMemo(
    () => [item.title, item.durationLabel ? `· ${item.durationLabel}` : "", statusCopy(item.status)].filter(Boolean).join(" "),
    [item.durationLabel, item.status, item.title],
  );

  return (
    <section className={`activity-thought ${item.phase} ${item.status} ${expanded ? "expanded" : "collapsed"}`}>
      <button className="activity-thought-head" onClick={() => setExpanded((value) => !value)} type="button" aria-expanded={expanded}>
        <span className="activity-thought-icon" aria-hidden="true">
          <PhaseIcon phase={item.phase} />
        </span>
        <span className="activity-thought-title">{item.title}</span>
        {item.durationLabel ? <span className="activity-thought-meta">· {item.durationLabel}</span> : null}
        <span className={`activity-thought-status ${item.status}`}>{statusCopy(item.status)}</span>
        <span className="activity-thought-toggle" aria-hidden="true">
          <ChevronDown size={13} />
        </span>
      </button>
      {!expanded ? <div className="activity-thought-summary">{summary}</div> : null}
      {expanded ? (
        <div className="activity-thought-body">
          {lines.map((line, index) => (
            <p className="activity-thought-line" key={`${item.id}-line-${index}`}>
              {line}
            </p>
          ))}
          {!lines.length && item.attachments?.length ? <RichMessageAttachments attachments={item.attachments} /> : null}
        </div>
      ) : null}
    </section>
  );
}

export function ProgressBlock({ item }: { item: ActivityItem }) {
  const label = item.running ? "正在推演这一步" : "思考已收束";
  const summary = item.narrative || item.summary || "Agent 正在推进当前任务。";
  return (
    <section className={`progress-block reasoning-block ${item.running ? "live" : ""}`}>
      <div className="progress-pulse" aria-hidden="true">
        <Sparkles size={14} />
      </div>
      <div className="progress-block-copy">
        <div className="progress-block-line">
          <strong>{label}</strong>
          {item.durationLabel ? <span className="progress-block-meta">· {item.durationLabel}</span> : null}
          <span className={`progress-block-status ${item.status}`}>{statusCopy(item.status)}</span>
        </div>
        <p>{summary}</p>
      </div>
    </section>
  );
}

function PhaseIcon({ phase }: { phase: ActivityPhase }) {
  const Icon = phaseIcon(phase);
  return <Icon size={14} />;
}

function phaseIcon(phase: ActivityPhase) {
  if (phase === "preparing" || phase === "analyzing" || phase === "finalizing") return Sparkles;
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
  return status;
}

function buildThinkingLines(item: ActivityItem) {
  const lines: string[] = [];
  const narrative = item.narrative || item.summary || item.detail || "";
  if (narrative) lines.push(narrative);

  for (const entry of item.entries || []) {
    const parts = [entry.label, entry.narrative || entry.detail, [entry.rawType, entry.durationLabel].filter(Boolean).join(" · ")].filter(Boolean);
    if (parts.length) lines.push(parts.join(" · "));
    if (entry.attachments?.length) lines.push(`${entry.attachments.length} 个附件`);
  }

  return lines;
}

export function StatusIcon({ status }: { status: ActivityStatus }) {
  if (status === "success") return <CheckCircle2 size={14} />;
  if (status === "error" || status === "cancelled") return <CircleAlert size={14} />;
  return <CircleDashed size={14} />;
}
