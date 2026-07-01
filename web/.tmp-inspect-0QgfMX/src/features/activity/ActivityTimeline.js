"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.ActivityTimeline = ActivityTimeline;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
const lucide_react_1 = require("lucide-react");
const badge_1 = require("@/components/ui/badge");
const button_1 = require("@/components/ui/button");
const card_1 = require("@/components/ui/card");
const ActivityCard_1 = require("./ActivityCard");
function ActivityTimeline({ items, selectedId, onSelect }) {
    const [filter, setFilter] = (0, react_1.useState)("all");
    const filtered = (0, react_1.useMemo)(() => items.filter((item) => matchesFilter(item.phase, filter)), [items, filter]);
    return ((0, jsx_runtime_1.jsxs)("section", { className: "activity-timeline space-y-3", children: [(0, jsx_runtime_1.jsx)("div", { className: "flex flex-wrap gap-2", children: filters.map((item) => ((0, jsx_runtime_1.jsxs)(button_1.Button, { size: "sm", variant: filter === item.id ? "default" : "outline", onClick: () => setFilter(item.id), type: "button", children: [(0, jsx_runtime_1.jsx)(item.icon, { size: 13 }), (0, jsx_runtime_1.jsx)("span", { children: item.label })] }, item.id))) }), (0, jsx_runtime_1.jsxs)("ol", { className: "space-y-2", children: [filtered.length === 0 ? (0, jsx_runtime_1.jsx)("li", { className: "rounded-lg border border-dashed p-4 text-sm text-muted-foreground", children: "No activity yet." }) : null, filtered.map((item) => ((0, jsx_runtime_1.jsx)("li", { children: (0, jsx_runtime_1.jsx)(card_1.Card, { className: selectedId === item.id ? "border-primary/60 bg-primary/5" : "", children: (0, jsx_runtime_1.jsx)(card_1.CardContent, { className: "p-0", children: (0, jsx_runtime_1.jsxs)("button", { className: `flex w-full items-start gap-3 px-4 py-3 text-left ${selectedId === item.id ? "bg-primary/5" : ""}`, onClick: () => onSelect?.(item), type: "button", children: [(0, jsx_runtime_1.jsx)("span", { className: "mt-0.5 text-muted-foreground", children: (0, jsx_runtime_1.jsx)(ActivityCard_1.StatusIcon, { status: item.status }) }), (0, jsx_runtime_1.jsxs)("span", { className: "min-w-0 flex-1", children: [(0, jsx_runtime_1.jsx)("strong", { className: "block truncate text-sm", children: item.title }), (0, jsx_runtime_1.jsx)("small", { className: "mt-1 block text-sm leading-6 text-muted-foreground", children: item.narrative || item.summary })] }), (0, jsx_runtime_1.jsx)(badge_1.Badge, { variant: "outline", className: "shrink-0", children: item.durationLabel || "…" })] }) }) }) }, item.id)))] })] }));
}
const filters = [
    { id: "all", label: "All", icon: lucide_react_1.Filter },
    { id: "analysis", label: "Progress", icon: lucide_react_1.Sparkles },
    { id: "tool", label: "Tools", icon: lucide_react_1.Code2 },
    { id: "approval", label: "Approvals", icon: lucide_react_1.ShieldCheck },
    { id: "subagent", label: "Subagents", icon: lucide_react_1.Bot },
    { id: "system", label: "System", icon: lucide_react_1.Activity }
];
function matchesFilter(phase, filter) {
    if (filter === "all")
        return true;
    if (filter === "system")
        return ["system", "queue", "memory", "checkpoint", "artifact", "event"].includes(phase);
    if (filter === "analysis")
        return ["preparing", "analyzing", "finalizing"].includes(phase);
    return phase === filter;
}
