"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.ActivityCard = ActivityCard;
exports.ProgressBlock = ProgressBlock;
exports.StatusIcon = StatusIcon;
const jsx_runtime_1 = require("react/jsx-runtime");
const lucide_react_1 = require("lucide-react");
const badge_1 = require("@/components/ui/badge");
const card_1 = require("@/components/ui/card");
const collapsible_1 = require("@/components/ui/collapsible");
const separator_1 = require("@/components/ui/separator");
const rich_text_1 = require("../../rich-text");
function ActivityCard({ item }) {
    const Icon = phaseIcon(item.phase);
    const open = item.running || item.status === "error" || item.status === "pending";
    return ((0, jsx_runtime_1.jsx)(collapsible_1.Collapsible, { defaultOpen: open, className: `activity-card ${item.phase} ${item.status}`, children: (0, jsx_runtime_1.jsxs)(card_1.Card, { className: "activity-card-shell", children: [(0, jsx_runtime_1.jsxs)(collapsible_1.CollapsibleTrigger, { className: "activity-card-trigger", children: [(0, jsx_runtime_1.jsx)("span", { className: "activity-card-icon", children: (0, jsx_runtime_1.jsx)(Icon, { size: 15 }) }), (0, jsx_runtime_1.jsxs)("span", { className: "activity-card-main", children: [(0, jsx_runtime_1.jsx)("strong", { children: item.title }), (0, jsx_runtime_1.jsx)("small", { children: item.summary })] }), (0, jsx_runtime_1.jsx)(badge_1.Badge, { className: `activity-status ${item.status}`, variant: statusVariant(item.status), children: statusCopy(item.status) }), (0, jsx_runtime_1.jsx)(lucide_react_1.ChevronRight, { className: "activity-chevron", size: 15 })] }), (0, jsx_runtime_1.jsx)(collapsible_1.CollapsibleContent, { children: (0, jsx_runtime_1.jsxs)(card_1.CardContent, { className: "activity-card-body", children: [isProgressPhase(item.phase) ? (0, jsx_runtime_1.jsx)(ProgressBlock, { item: item }) : null, item.entries.length > 0 ? (0, jsx_runtime_1.jsx)(separator_1.Separator, { className: "activity-separator" }) : null, item.entries.length > 0 ? ((0, jsx_runtime_1.jsx)("ol", { className: "activity-step-list", children: item.entries.map((entry) => ((0, jsx_runtime_1.jsxs)("li", { className: `activity-step ${entry.status}`, children: [(0, jsx_runtime_1.jsx)("span", { className: "activity-step-dot" }), (0, jsx_runtime_1.jsxs)("div", { className: "activity-step-content", children: [(0, jsx_runtime_1.jsxs)("div", { className: "activity-step-head", children: [(0, jsx_runtime_1.jsx)("strong", { children: entry.label }), (0, jsx_runtime_1.jsx)("small", { children: [entry.rawType, entry.durationLabel].filter(Boolean).join(" \u00b7 ") })] }), entry.detail ? (0, jsx_runtime_1.jsx)("pre", { children: entry.detail }) : null, entry.attachments?.length ? (0, jsx_runtime_1.jsx)(rich_text_1.RichMessageAttachments, { attachments: entry.attachments }) : null] })] }, entry.id))) })) : item.detail ? ((0, jsx_runtime_1.jsx)("pre", { className: "activity-detail-pre", children: item.detail })) : null, item.attachments?.length ? (0, jsx_runtime_1.jsx)(rich_text_1.RichMessageAttachments, { attachments: item.attachments }) : null] }) })] }) }));
}
function ProgressBlock({ item }) {
    return ((0, jsx_runtime_1.jsxs)("section", { className: `progress-block ${item.running ? "live" : ""}`, children: [(0, jsx_runtime_1.jsx)("div", { className: "progress-pulse", children: (0, jsx_runtime_1.jsx)(lucide_react_1.Sparkles, { size: 14 }) }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("strong", { children: item.running ? "\u6b63\u5728\u5206\u6790\u4e0b\u4e00\u6b65" : "\u8fd0\u884c\u8fdb\u5ea6" }), (0, jsx_runtime_1.jsx)("p", { children: item.summary || "Agent \u6b63\u5728\u63a8\u8fdb\u5f53\u524d\u4efb\u52a1\u3002" })] })] }));
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
        return "\u8fdb\u884c\u4e2d";
    if (status === "pending")
        return "\u5f85\u786e\u8ba4";
    if (status === "success")
        return "\u5b8c\u6210";
    if (status === "warning")
        return "\u9700\u68c0\u67e5";
    if (status === "error")
        return "\u5931\u8d25";
    if (status === "cancelled")
        return "\u5df2\u53d6\u6d88";
    return status;
}
function statusVariant(status) {
    if (status === "error" || status === "cancelled")
        return "destructive";
    if (status === "running" || status === "pending" || status === "warning")
        return "secondary";
    return "outline";
}
function StatusIcon({ status }) {
    if (status === "success")
        return (0, jsx_runtime_1.jsx)(lucide_react_1.CheckCircle2, { size: 14 });
    if (status === "error" || status === "cancelled")
        return (0, jsx_runtime_1.jsx)(lucide_react_1.CircleAlert, { size: 14 });
    return (0, jsx_runtime_1.jsx)(lucide_react_1.CircleDashed, { size: 14 });
}
