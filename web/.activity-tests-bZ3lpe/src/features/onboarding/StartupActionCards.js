"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.StartupActionCards = StartupActionCards;
const jsx_runtime_1 = require("react/jsx-runtime");
const lucide_react_1 = require("lucide-react");
const onboarding_utils_1 = require("./onboarding-utils");
function StartupActionCards({ status, onOpenTrace }) {
    const hints = status?.command_hints || [];
    return ((0, jsx_runtime_1.jsxs)("section", { className: "startup-guide-section", children: [(0, jsx_runtime_1.jsx)("div", { className: "startup-guide-section-head", children: (0, jsx_runtime_1.jsx)("h2", { children: "\u5E38\u7528\u52A8\u4F5C" }) }), (0, jsx_runtime_1.jsxs)("div", { className: "startup-action-grid", children: [hints.map((hint, index) => {
                        const Icon = index === 0 ? lucide_react_1.KeyRound : index === 1 ? lucide_react_1.TerminalSquare : lucide_react_1.MonitorPlay;
                        return ((0, jsx_runtime_1.jsxs)("article", { className: "startup-action-card", children: [(0, jsx_runtime_1.jsx)(Icon, { size: 18 }), (0, jsx_runtime_1.jsx)("strong", { children: hint.title }), (0, jsx_runtime_1.jsx)("p", { children: hint.description }), (0, jsx_runtime_1.jsx)("code", { children: hint.command }), (0, jsx_runtime_1.jsxs)("button", { onClick: () => (0, onboarding_utils_1.copyText)(hint.command), children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Copy, { size: 14 }), (0, jsx_runtime_1.jsx)("span", { children: "\u590D\u5236\u547D\u4EE4" })] })] }, hint.title));
                    }), (0, jsx_runtime_1.jsxs)("article", { className: "startup-action-card", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Activity, { size: 18 }), (0, jsx_runtime_1.jsx)("strong", { children: "\u67E5\u770B Agent Trace \u5BA1\u8BA1" }), (0, jsx_runtime_1.jsx)("p", { children: "\u8FD0\u884C\u4E00\u6B21\u4EFB\u52A1\u540E\uFF0C\u5728 TraceInspect \u4E2D\u67E5\u770B LLM token/cost\u3001\u5DE5\u5177\u8C03\u7528\u3001\u5BA1\u6279\u3001Memory\u3001Checkpoint \u548C\u9519\u8BEF\u8BCA\u65AD\u3002" }), (0, jsx_runtime_1.jsx)("button", { onClick: onOpenTrace, children: (0, jsx_runtime_1.jsx)("span", { children: "\u6253\u5F00 TraceInspect" }) })] })] })] }));
}
