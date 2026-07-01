"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.TraceApprovalPanel = TraceApprovalPanel;
const jsx_runtime_1 = require("react/jsx-runtime");
const trace_utils_1 = require("./trace-utils");
function TraceApprovalPanel({ spans }) {
    const groups = (0, trace_utils_1.groupApprovalSpansByDigest)(spans);
    return ((0, jsx_runtime_1.jsxs)("section", { className: "trace-inspect-section trace-span-list", children: [(0, jsx_runtime_1.jsx)("h3", { children: "Approvals" }), groups.map((group) => (0, jsx_runtime_1.jsxs)("details", { children: [(0, jsx_runtime_1.jsx)("summary", { children: group.digest }), group.items.map((span) => (0, jsx_runtime_1.jsxs)("p", { children: [span.name, " \u00B7 ", (0, trace_utils_1.statusLabel)(span.status), " \u00B7 ", String(span.attributes.decision || "")] }, span.span_id))] }, group.digest)), groups.length === 0 ? (0, jsx_runtime_1.jsx)("p", { className: "muted", children: "No approvals." }) : null] }));
}
