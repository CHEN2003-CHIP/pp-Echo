import { useMemo, useState } from "react";
import { Activity, Bot, Code2, Filter, ShieldCheck, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { ActivityItem, ActivityPhase } from "./activity-types";
import { StatusIcon } from "./ActivityCard";

type FilterKey = "all" | "analysis" | "tool" | "approval" | "subagent" | "system";

export function ActivityTimeline({
  items,
  selectedId,
  onSelect
}: {
  items: ActivityItem[];
  selectedId?: string;
  onSelect?: (item: ActivityItem) => void;
}) {
  const [filter, setFilter] = useState<FilterKey>("all");
  const filtered = useMemo(() => items.filter((item) => matchesFilter(item.phase, filter)), [items, filter]);
  return (
    <section className="activity-timeline space-y-3">
      <div className="flex flex-wrap gap-2">
        {filters.map((item) => (
          <Button key={item.id} size="sm" variant={filter === item.id ? "default" : "outline"} onClick={() => setFilter(item.id)} type="button">
            <item.icon size={13} />
            <span>{item.label}</span>
          </Button>
        ))}
      </div>
      <ol className="space-y-2">
        {filtered.length === 0 ? <li className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">No activity yet.</li> : null}
        {filtered.map((item) => (
          <li key={item.id}>
            <Card className={selectedId === item.id ? "border-primary/60 bg-primary/5" : ""}>
              <CardContent className="p-0">
                <button className={`flex w-full items-start gap-3 px-4 py-3 text-left ${selectedId === item.id ? "bg-primary/5" : ""}`} onClick={() => onSelect?.(item)} type="button">
                  <span className="mt-0.5 text-muted-foreground"><StatusIcon status={item.status} /></span>
                  <span className="min-w-0 flex-1">
                    <strong className="block truncate text-sm">{item.title}</strong>
                    <small className="mt-1 block text-sm leading-6 text-muted-foreground">{item.narrative || item.summary}</small>
                  </span>
                  <Badge variant="outline" className="shrink-0">{item.durationLabel || "…"}</Badge>
                </button>
              </CardContent>
            </Card>
          </li>
        ))}
      </ol>
    </section>
  );
}

const filters: Array<{ id: FilterKey; label: string; icon: typeof Activity }> = [
  { id: "all", label: "All", icon: Filter },
  { id: "analysis", label: "Progress", icon: Sparkles },
  { id: "tool", label: "Tools", icon: Code2 },
  { id: "approval", label: "Approvals", icon: ShieldCheck },
  { id: "subagent", label: "Subagents", icon: Bot },
  { id: "system", label: "System", icon: Activity }
];

function matchesFilter(phase: ActivityPhase, filter: FilterKey) {
  if (filter === "all") return true;
  if (filter === "system") return ["system", "queue", "memory", "checkpoint", "artifact", "event"].includes(phase);
  if (filter === "analysis") return ["preparing", "analyzing", "finalizing"].includes(phase);
  return phase === filter;
}
