"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.TraceCheckpointPanel = TraceCheckpointPanel;
const jsx_runtime_1 = require("react/jsx-runtime");
const TraceToolCallsPanel_1 = require("./TraceToolCallsPanel");
function TraceCheckpointPanel({ spans }) {
    return (0, jsx_runtime_1.jsx)(TraceToolCallsPanel_1.TraceSpanList, { title: "Checkpoints", spans: spans.filter((span) => span.span_type === "checkpoint"), renderMeta: (span) => `${span.name} · ${String(span.attributes.checkpoint_id || span.attributes.reason || "")}` });
}
