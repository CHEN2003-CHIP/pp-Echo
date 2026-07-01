"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.TraceMemoryPanel = TraceMemoryPanel;
const jsx_runtime_1 = require("react/jsx-runtime");
const TraceToolCallsPanel_1 = require("./TraceToolCallsPanel");
function TraceMemoryPanel({ spans }) {
    return (0, jsx_runtime_1.jsx)(TraceToolCallsPanel_1.TraceSpanList, { title: "Memory", spans: spans.filter((span) => span.span_type === "memory"), renderMeta: (span) => `returned ${String(span.output.returned_count || 0)}` });
}
