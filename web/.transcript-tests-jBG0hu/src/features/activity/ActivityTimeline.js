"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.ActivityTimeline = ActivityTimeline;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
const lucide_react_1 = require("lucide-react");
const ActivityCard_1 = require("./ActivityCard");
function ActivityTimeline({ items, selectedId, onSelect }) {
    const [filter, setFilter] = (0, react_1.useState)("all");
    const filtered = (0, react_1.useMemo)(() => items.filter((item) => matchesFilter(item.phase, filter)), [items, filter]);
    return ((0, jsx_runtime_1.jsxs)("section", { className: "activity-timeline", children: [(0, jsx_runtime_1.jsx)("div", { className: "activity-filter-row", children: filters.map((item) => ((0, jsx_runtime_1.jsxs)("button", { className: filter === item.id ? "active" : "", onClick: () => setFilter(item.id), type: "button", children: [(0, jsx_runtime_1.jsx)(item.icon, { size: 13 }), (0, jsx_runtime_1.jsx)("span", { children: item.label })] }, item.id))) }), (0, jsx_runtime_1.jsxs)("ol", { children: [filtered.length === 0 ? (0, jsx_runtime_1.jsx)("li", { className: "activity-empty", children: "No activity yet." }) : null, filtered.map((item) => ((0, jsx_runtime_1.jsx)("li", { children: (0, jsx_runtime_1.jsxs)("button", { className: selectedId === item.id ? `activity-timeline-row active ${item.status}` : `activity-timeline-row ${item.status}`, onClick: () => onSelect?.(item), type: "button", children: [(0, jsx_runtime_1.jsx)("span", { className: "activity-timeline-status", children: (0, jsx_runtime_1.jsx)(ActivityCard_1.StatusIcon, { status: item.status }) }), (0, jsx_runtime_1.jsxs)("span", { children: [(0, jsx_runtime_1.jsx)("strong", { children: item.title }), (0, jsx_runtime_1.jsx)("small", { children: item.summary })] }), (0, jsx_runtime_1.jsx)("em", { children: item.durationLabel })] }) }, item.id)))] })] }));
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
