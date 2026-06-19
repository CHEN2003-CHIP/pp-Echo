import { useMemo, useState } from "react";
import { Activity, Bot, Code2, Filter, ShieldCheck, Sparkles } from "lucide-react";
import type { ActivityItem, ActivityPhase } from "./activity-types";
import { StatusIcon } from "./ActivityCard";

type FilterKey = "all" | "reasoning" | "tool" | "approval" | "subagent" | "system";

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
    <section className="activity-timeline">
      <div className="activity-filter-row">
        {filters.map((item) => (
          <button className={filter === item.id ? "active" : ""} key={item.id} onClick={() => setFilter(item.id)} type="button">
            <item.icon size={13} />
            <span>{item.label}</span>
          </button>
        ))}
      </div>
      <ol>
        {filtered.length === 0 ? <li className="activity-empty">No activity yet.</li> : null}
        {filtered.map((item) => (
          <li key={item.id}>
            <button className={selectedId === item.id ? `activity-timeline-row active ${item.status}` : `activity-timeline-row ${item.status}`} onClick={() => onSelect?.(item)} type="button">
              <span className="activity-timeline-status"><StatusIcon status={item.status} /></span>
              <span>
                <strong>{item.title}</strong>
                <small>{item.summary}</small>
              </span>
              <em>{item.durationLabel}</em>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

const filters: Array<{ id: FilterKey; label: string; icon: typeof Activity }> = [
  { id: "all", label: "All", icon: Filter },
  { id: "reasoning", label: "Thinking", icon: Sparkles },
  { id: "tool", label: "Tools", icon: Code2 },
  { id: "approval", label: "Approvals", icon: ShieldCheck },
  { id: "subagent", label: "Subagents", icon: Bot },
  { id: "system", label: "System", icon: Activity }
];

function matchesFilter(phase: ActivityPhase, filter: FilterKey) {
  if (filter === "all") return true;
  if (filter === "system") return ["system", "queue", "memory", "checkpoint", "artifact", "event"].includes(phase);
  return phase === filter;
}
