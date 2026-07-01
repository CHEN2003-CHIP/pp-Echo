"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.ActivityCard = ActivityCard;
exports.ProgressBlock = ProgressBlock;
exports.StatusIcon = StatusIcon;
const jsx_runtime_1 = require("react/jsx-runtime");
const lucide_react_1 = require("lucide-react");
const badge_1 = require("@/components/ui/badge");
const button_1 = require("@/components/ui/button");
const card_1 = require("@/components/ui/card");
const collapsible_1 = require("@/components/ui/collapsible");
const separator_1 = require("@/components/ui/separator");
const rich_text_1 = require("../../rich-text");
function ActivityCard({ item }) {
    const Icon = phaseIcon(item.phase);
    const open = item.running || item.status === "error" || item.status === "pending";
    const narrative = item.narrative || item.summary;
    return ((0, jsx_runtime_1.jsx)(collapsible_1.Collapsible, { defaultOpen: open, className: "activity-card", children: (0, jsx_runtime_1.jsxs)(card_1.Card, { className: `activity-card-shell ${item.phase} ${item.status}`, children: [(0, jsx_runtime_1.jsx)(collapsible_1.CollapsibleTrigger, { asChild: true, children: (0, jsx_runtime_1.jsxs)("button", { type: "button", className: "activity-card-trigger", children: [(0, jsx_runtime_1.jsx)("span", { className: "activity-card-icon", children: (0, jsx_runtime_1.jsx)(Icon, { size: 15 }) }), (0, jsx_runtime_1.jsxs)("span", { className: "activity-card-main", children: [(0, jsx_runtime_1.jsx)("strong", { children: item.title }), (0, jsx_runtime_1.jsx)("small", { children: narrative })] }), (0, jsx_runtime_1.jsx)(badge_1.Badge, { className: `activity-status ${item.status}`, variant: statusVariant(item.status), children: statusCopy(item.status) }), (0, jsx_runtime_1.jsx)(lucide_react_1.ChevronDown, { className: "activity-chevron", size: 15 })] }) }), (0, jsx_runtime_1.jsx)(collapsible_1.CollapsibleContent, { children: (0, jsx_runtime_1.jsxs)(card_1.CardContent, { className: "activity-card-body", children: [(0, jsx_runtime_1.jsxs)("section", { className: "activity-narrative", children: [(0, jsx_runtime_1.jsx)("p", { children: narrative }), item.summary !== narrative ? (0, jsx_runtime_1.jsx)("small", { children: item.summary }) : null] }), item.entries.length > 0 ? (0, jsx_runtime_1.jsx)(separator_1.Separator, { className: "activity-separator" }) : null, item.entries.length > 0 ? ((0, jsx_runtime_1.jsx)("div", { className: "activity-step-rail", children: item.entries.map((entry) => ((0, jsx_runtime_1.jsxs)("article", { className: `activity-step ${entry.status}`, children: [(0, jsx_runtime_1.jsxs)("div", { className: "activity-step-head", children: [(0, jsx_runtime_1.jsx)("span", { className: "activity-step-icon", children: (0, jsx_runtime_1.jsx)(StepIcon, { kind: entry.kind }) }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("strong", { children: entry.label }), (0, jsx_runtime_1.jsx)("small", { children: [entry.rawType, entry.durationLabel].filter(Boolean).join(" · ") })] })] }), entry.narrative ? (0, jsx_runtime_1.jsx)("p", { className: "activity-step-narrative", children: entry.narrative }) : null, entry.attachments?.length ? (0, jsx_runtime_1.jsx)(rich_text_1.RichMessageAttachments, { attachments: entry.attachments }) : null] }, entry.id))) })) : null, item.attachments?.length ? (0, jsx_runtime_1.jsx)(rich_text_1.RichMessageAttachments, { attachments: item.attachments }) : null, (0, jsx_runtime_1.jsx)("div", { className: "activity-card-footer", children: (0, jsx_runtime_1.jsxs)(button_1.Button, { variant: "ghost", size: "sm", type: "button", className: "pointer-events-none opacity-60", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.TerminalSquare, { size: 14 }), "\u5B89\u5168\u7EC6\u8282\u5C55\u5F00\u4E2D"] }) })] }) })] }) }));
}
function ProgressBlock({ item }) {
    return ((0, jsx_runtime_1.jsxs)("section", { className: `progress-block ${item.running ? "live" : ""}`, children: [(0, jsx_runtime_1.jsx)("div", { className: "progress-pulse", children: (0, jsx_runtime_1.jsx)(lucide_react_1.Sparkles, { size: 14 }) }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("strong", { children: item.running ? "正在分析下一步" : "运行进度" }), (0, jsx_runtime_1.jsx)("p", { children: item.narrative || item.summary || "Agent 正在推进当前任务。" })] })] }));
}
function StepIcon({ kind }) {
    if (kind === "progress")
        return (0, jsx_runtime_1.jsx)(lucide_react_1.Sparkles, { size: 14 });
    if (kind === "planner")
        return (0, jsx_runtime_1.jsx)(lucide_react_1.Layers3, { size: 14 });
    if (kind === "tool")
        return (0, jsx_runtime_1.jsx)(lucide_react_1.Code2, { size: 14 });
    if (kind === "command")
        return (0, jsx_runtime_1.jsx)(lucide_react_1.TerminalSquare, { size: 14 });
    if (kind === "approval")
        return (0, jsx_runtime_1.jsx)(lucide_react_1.ShieldCheck, { size: 14 });
    if (kind === "artifact")
        return (0, jsx_runtime_1.jsx)(lucide_react_1.FileWarning, { size: 14 });
    if (kind === "checkpoint")
        return (0, jsx_runtime_1.jsx)(lucide_react_1.GitBranch, { size: 14 });
    if (kind === "subagent")
        return (0, jsx_runtime_1.jsx)(lucide_react_1.Bot, { size: 14 });
    if (kind === "memory")
        return (0, jsx_runtime_1.jsx)(lucide_react_1.CircleDashed, { size: 14 });
    if (kind === "system")
        return (0, jsx_runtime_1.jsx)(lucide_react_1.Clock3, { size: 14 });
    return (0, jsx_runtime_1.jsx)(lucide_react_1.PlayCircle, { size: 14 });
}
function phaseIcon(phase) {
    if (phase === "preparing" || phase === "analyzing" || phase === "finalizing")
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
function statusCopy(status) {
    if (status === "running")
        return "进行中";
    if (status === "pending")
        return "待确认";
    if (status === "success")
        return "完成";
    if (status === "warning")
        return "需留意";
    if (status === "error")
        return "失败";
    if (status === "cancelled")
        return "已取消";
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
