"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.StartupChecklist = StartupChecklist;
const jsx_runtime_1 = require("react/jsx-runtime");
const lucide_react_1 = require("lucide-react");
const onboarding_utils_1 = require("./onboarding-utils");
const statusIcon = {
    ok: lucide_react_1.CheckCircle2,
    warning: lucide_react_1.TriangleAlert,
    error: lucide_react_1.XCircle,
    skipped: lucide_react_1.HelpCircle
};
function StartupChecklist({ checks }) {
    return ((0, jsx_runtime_1.jsxs)("section", { className: "startup-guide-section", children: [(0, jsx_runtime_1.jsx)("div", { className: "startup-guide-section-head", children: (0, jsx_runtime_1.jsx)("h2", { children: "\u542F\u52A8\u68C0\u67E5" }) }), (0, jsx_runtime_1.jsx)("div", { className: "startup-checklist", children: checks.map((check) => {
                    const Icon = statusIcon[check.status];
                    return ((0, jsx_runtime_1.jsxs)("article", { className: "startup-check-item", children: [(0, jsx_runtime_1.jsx)("div", { className: `startup-check-icon ${(0, onboarding_utils_1.statusTone)(check.status)}`, children: (0, jsx_runtime_1.jsx)(Icon, { size: 18 }) }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsxs)("div", { className: "startup-check-title", children: [(0, jsx_runtime_1.jsx)("strong", { children: check.title }), (0, jsx_runtime_1.jsx)("span", { className: (0, onboarding_utils_1.statusTone)(check.status), children: onboarding_utils_1.statusLabel[check.status] })] }), (0, jsx_runtime_1.jsx)("p", { children: check.summary }), check.detail ? (0, jsx_runtime_1.jsx)("small", { children: check.detail }) : null, check.action_command ? ((0, jsx_runtime_1.jsxs)("button", { className: "startup-copy-command", onClick: () => (0, onboarding_utils_1.copyText)(check.action_command || ""), children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Copy, { size: 14 }), (0, jsx_runtime_1.jsx)("span", { children: check.action_label || "复制命令" })] })) : null] })] }, check.id));
                }) })] }));
}
