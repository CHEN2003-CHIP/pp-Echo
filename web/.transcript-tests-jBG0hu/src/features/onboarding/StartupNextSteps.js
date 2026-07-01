"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.StartupNextSteps = StartupNextSteps;
const jsx_runtime_1 = require("react/jsx-runtime");
function StartupNextSteps({ status, onOpenChat, onOpenTrace }) {
    return ((0, jsx_runtime_1.jsxs)("section", { className: "startup-guide-section", children: [(0, jsx_runtime_1.jsx)("div", { className: "startup-guide-section-head", children: (0, jsx_runtime_1.jsx)("h2", { children: "\u4E0B\u4E00\u6B65" }) }), (0, jsx_runtime_1.jsx)("div", { className: "startup-next-steps", children: (status?.next_steps || []).map((step) => ((0, jsx_runtime_1.jsxs)("article", { children: [(0, jsx_runtime_1.jsx)("strong", { children: step.title }), (0, jsx_runtime_1.jsx)("p", { children: step.description }), step.target_view === "chat" ? (0, jsx_runtime_1.jsx)("button", { onClick: onOpenChat, children: step.action_label || "返回会话" }) : null, step.target_view === "traceInspect" ? (0, jsx_runtime_1.jsx)("button", { onClick: onOpenTrace, children: step.action_label || "打开 TraceInspect" }) : null] }, step.title))) })] }));
}
