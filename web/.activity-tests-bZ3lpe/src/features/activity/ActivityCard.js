"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.ActivityCard = ActivityCard;
exports.ProgressBlock = ProgressBlock;
exports.StatusIcon = StatusIcon;
const jsx_runtime_1 = require("react/jsx-runtime");
const lucide_react_1 = require("lucide-react");
const rich_text_1 = require("../../rich-text");
function ActivityCard({ item }) {
    const Icon = phaseIcon(item.phase);
    const open = item.running || item.status === "error" || item.status === "pending";
    return ((0, jsx_runtime_1.jsxs)("details", { className: `activity-card ${item.phase} ${item.status}`, open: open, children: [(0, jsx_runtime_1.jsxs)("summary", { children: [(0, jsx_runtime_1.jsx)("span", { className: "activity-card-icon", children: (0, jsx_runtime_1.jsx)(Icon, { size: 15 }) }), (0, jsx_runtime_1.jsxs)("span", { className: "activity-card-main", children: [(0, jsx_runtime_1.jsx)("strong", { children: item.title }), (0, jsx_runtime_1.jsx)("small", { children: item.summary })] }), (0, jsx_runtime_1.jsx)("span", { className: `activity-status ${item.status}`, children: statusCopy(item.status) }), (0, jsx_runtime_1.jsx)(lucide_react_1.ChevronRight, { className: "activity-chevron", size: 15 })] }), (0, jsx_runtime_1.jsxs)("div", { className: "activity-card-body", children: [isProgressPhase(item.phase) ? (0, jsx_runtime_1.jsx)(ProgressBlock, { item: item }) : null, item.entries.length > 0 ? ((0, jsx_runtime_1.jsx)("ol", { className: "activity-step-list", children: item.entries.map((entry) => ((0, jsx_runtime_1.jsxs)("li", { className: `activity-step ${entry.status}`, children: [(0, jsx_runtime_1.jsx)("span", { className: "activity-step-dot" }), (0, jsx_runtime_1.jsxs)("div", { className: "activity-step-content", children: [(0, jsx_runtime_1.jsxs)("div", { className: "activity-step-head", children: [(0, jsx_runtime_1.jsx)("strong", { children: entry.label }), (0, jsx_runtime_1.jsx)("small", { children: [entry.rawType, entry.durationLabel].filter(Boolean).join(" · ") })] }), entry.detail ? (0, jsx_runtime_1.jsx)("pre", { children: entry.detail }) : null, entry.attachments?.length ? (0, jsx_runtime_1.jsx)(rich_text_1.RichMessageAttachments, { attachments: entry.attachments }) : null] })] }, entry.id))) })) : item.detail ? ((0, jsx_runtime_1.jsx)("pre", { className: "activity-detail-pre", children: item.detail })) : null, item.attachments?.length ? (0, jsx_runtime_1.jsx)(rich_text_1.RichMessageAttachments, { attachments: item.attachments }) : null] })] }));
}
function ProgressBlock({ item }) {
    return ((0, jsx_runtime_1.jsxs)("section", { className: `progress-block ${item.running ? "live" : ""}`, children: [(0, jsx_runtime_1.jsx)("div", { className: "progress-pulse", children: (0, jsx_runtime_1.jsx)(lucide_react_1.Sparkles, { size: 14 }) }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("strong", { children: item.running ? "Analyzing the next step" : "Progress summary" }), (0, jsx_runtime_1.jsx)("p", { children: item.summary || "Public progress from the runtime." })] })] }));
}
function phaseIcon(phase) {
    if (isProgressPhase(phase))
        return lucide_react_1.Sparkles;
    if (phase === "planning")
        return lucide_react_1.Layers3;
    if (phase === "tool")
        return lucide_react_1.Code2;
    if (phase === "approval")
        return lucide_react_1.ShieldCheck;
    if (phase === "artifact")
        return lucide_react_1.FileWarning;
    if (phase === "checkpoint")
        return lucide_react_1.GitBranch;
    if (phase === "subagent")
        return lucide_react_1.Bot;
    if (phase === "queue")
        return lucide_react_1.Clock3;
    if (phase === "memory")
        return lucide_react_1.CircleDashed;
    return lucide_react_1.PlayCircle;
}
function isProgressPhase(phase) {
    return phase === "preparing" || phase === "analyzing" || phase === "finalizing";
}
function statusCopy(status) {
    if (status === "running")
        return "Running";
    if (status === "pending")
        return "Pending";
    if (status === "success")
        return "Done";
    if (status === "warning")
        return "Review";
    if (status === "error")
        return "Failed";
    if (status === "cancelled")
        return "Cancelled";
    return status;
}
function StatusIcon({ status }) {
    if (status === "success")
        return (0, jsx_runtime_1.jsx)(lucide_react_1.CheckCircle2, { size: 14 });
    if (status === "error" || status === "cancelled")
        return (0, jsx_runtime_1.jsx)(lucide_react_1.CircleAlert, { size: 14 });
    return (0, jsx_runtime_1.jsx)(lucide_react_1.CircleDashed, { size: 14 });
}
