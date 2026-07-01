"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.TraceRawJsonPanel = TraceRawJsonPanel;
const jsx_runtime_1 = require("react/jsx-runtime");
const trace_utils_1 = require("./trace-utils");
function TraceRawJsonPanel({ detail }) {
    return (0, jsx_runtime_1.jsx)("section", { className: "trace-inspect-section", children: (0, jsx_runtime_1.jsxs)("details", { children: [(0, jsx_runtime_1.jsx)("summary", { children: "Raw JSON" }), (0, jsx_runtime_1.jsx)("pre", { children: (0, trace_utils_1.safeJsonStringify)(detail) })] }) });
}
