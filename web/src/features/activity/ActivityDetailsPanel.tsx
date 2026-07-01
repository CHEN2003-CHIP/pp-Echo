import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Activity, CircleAlert, Clock3, Code2, Copy, ListChecks, ShieldCheck, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
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
      <Card className="activity-run-summary">
        <CardContent className="space-y-4 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Activity</p>
              <h3 className="text-lg font-semibold">{summary.status === "running" ? "Run in progress" : summary.activityCount ? "Run activity" : "Waiting for activity"}</h3>
              <p className="text-sm text-muted-foreground">{summary.durationLabel || "No runtime events yet"}</p>
            </div>
            <div className="flex items-center gap-2">
              <Button variant={follow ? "default" : "outline"} size="sm" onClick={() => setFollow((value) => !value)}>
                <Activity size={14} />
                {follow ? "Following" : "Paused"}
              </Button>
              {onClose ? (
                <Button variant="ghost" size="icon" onClick={onClose} title="Close activity">
                  <X size={14} />
                </Button>
              ) : null}
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-4">
            <Metric icon={ListChecks} label="Events" value={summary.eventCount} />
            <Metric icon={Code2} label="Tools" value={summary.toolCount} />
            <Metric icon={ShieldCheck} label="Approvals" value={summary.approvalCount} />
            <Metric icon={CircleAlert} label="Errors" value={summary.errorCount} />
          </div>
        </CardContent>
      </Card>

      <ActivityTimeline
        items={items}
        selectedId={selected?.id || ""}
        onSelect={(item) => {
          setSelectedId(item.id);
          setFollow(false);
        }}
      />

      <Card className="activity-selected-detail">
        <CardContent className="space-y-4 p-4">
          {selected ? (
            <>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">{selected.phase}</p>
                  <h4 className="text-base font-semibold">{selected.title}</h4>
                  <p className="text-sm text-muted-foreground">{selected.narrative || selected.summary}</p>
                </div>
                <Badge variant="outline">{selected.status}</Badge>
              </div>
              <Separator />
              <ActionRow selected={selected} onApprove={onApprove} onReject={onReject} onOpenArtifact={onOpenArtifact} onOpenCheckpoint={onOpenCheckpoint} />
              <DetailSection title="过程摘要">
                <p className="text-sm leading-6 text-foreground/90">{selected.narrative || selected.summary}</p>
              </DetailSection>
              <DetailSection title="安全细节">
                <dl className="grid gap-3 sm:grid-cols-2">
                  <Meta label="Activity ID" value={selected.activityId || selected.id} />
                  <Meta label="Parent" value={selected.parentActivityId || "none"} />
                  <Meta label="Run" value={selected.runId || "unknown"} />
                  <Meta label="Duration" value={selected.durationLabel || "n/a"} />
                  <Meta label="Events" value={selected.eventCount} />
                  <Meta label="Steps" value={selected.entries.length} />
                </dl>
              </DetailSection>
              <DetailSection title="工具与结果">
                <div className="space-y-3">
                  {selected.entries.map((entry) => (
                    <details key={entry.id} className="rounded-lg border border-border/60 bg-muted/20 p-3">
                      <summary className="flex cursor-pointer items-center justify-between gap-3 text-sm font-medium">
                        <span>{entry.label}</span>
                        <span className="text-xs text-muted-foreground">{[entry.rawType, entry.durationLabel].filter(Boolean).join(" · ")}</span>
                      </summary>
                      <pre className="mt-3 overflow-x-auto whitespace-pre-wrap text-xs leading-5 text-muted-foreground">{entry.detail || "No detail available."}</pre>
                      {entry.attachments?.length ? <div className="mt-3"><RichAttachments attachments={entry.attachments} /></div> : null}
                    </details>
                  ))}
                </div>
              </DetailSection>
              {selected.detail ? (
                <DetailSection title="结构化记录">
                  <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg bg-muted/30 p-3 text-xs leading-5 text-muted-foreground">{selected.detail}</pre>
                </DetailSection>
              ) : null}
            </>
          ) : (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Clock3 size={18} />
              <span>No activity selected.</span>
            </div>
          )}
        </CardContent>
      </Card>
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
  return (
    <div className="flex flex-wrap gap-2">
      {selected.phase === "approval" && onApprove ? <Button size="sm" onClick={() => onApprove(selected)}>Approve</Button> : null}
      {selected.phase === "approval" && onReject ? <Button size="sm" variant="outline" onClick={() => onReject(selected)}>Reject</Button> : null}
      {selected.phase === "artifact" && onOpenArtifact ? <Button size="sm" variant="outline" onClick={() => onOpenArtifact(selected)}>Open artifact</Button> : null}
      {selected.phase === "checkpoint" && onOpenCheckpoint ? <Button size="sm" variant="outline" onClick={() => onOpenCheckpoint(selected)}>Open checkpoint</Button> : null}
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h5 className="text-sm font-medium">{title}</h5>
      {children}
    </section>
  );
}

function Metric({ icon: Icon, label, value }: { icon: typeof Activity; label: string; value: number }) {
  return (
    <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
        <Icon size={14} />
        <span>{label}</span>
      </div>
      <div className="mt-2 text-2xl font-semibold">{value}</div>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
      <dt className="text-xs uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-sm font-medium">{value}</dd>
    </div>
  );
}

function RichAttachments({ attachments }: { attachments: Array<{ url: string; alt?: string; title?: string; name?: string }> }) {
  return <div className="space-y-2">{attachments.map((attachment) => <div key={attachment.url} className="text-xs text-muted-foreground">{attachment.title || attachment.alt || attachment.name || attachment.url}</div>)}</div>;
}
