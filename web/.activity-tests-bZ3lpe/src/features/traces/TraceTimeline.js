"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.TraceTimeline = TraceTimeline;
const jsx_runtime_1 = require("react/jsx-runtime");
const trace_utils_1 = require("./trace-utils");
function TraceTimeline({ spans, selectedSpanId, onSelect }) {
    const starts = spans.map((span) => span.started_at).filter(Boolean);
    const ends = spans.map((span) => span.ended_at || (span.duration_ms ? span.started_at + span.duration_ms / 1000 : span.started_at)).filter(Boolean);
    const first = starts.length ? Math.min(...starts) : null;
    const last = ends.length ? Math.max(...ends) : null;
    const totalMs = first && last ? Math.max(1, Math.round((last - first) * 1000)) : 1;
    return ((0, jsx_runtime_1.jsxs)("section", { className: "trace-inspect-section trace-timeline", children: [(0, jsx_runtime_1.jsx)("h3", { children: "Timeline" }), (0, jsx_runtime_1.jsxs)("div", { className: "trace-timeline-head", "aria-hidden": "true", children: [(0, jsx_runtime_1.jsx)("span", { children: "Time" }), (0, jsx_runtime_1.jsx)("span", { children: "Span" }), (0, jsx_runtime_1.jsx)("span", { children: "Status" }), (0, jsx_runtime_1.jsx)("span", { children: "Duration" }), (0, jsx_runtime_1.jsx)("span", { children: "Waterfall" })] }), (0, jsx_runtime_1.jsx)("div", { className: "trace-timeline-list", children: spans.map((span) => {
                    const duration = Math.max(1, span.duration_ms || 0);
                    const offset = first ? Math.max(0, Math.round((span.started_at - first) * 1000)) : 0;
                    const left = Math.min(96, (offset / totalMs) * 100);
                    const width = Math.max(2, Math.min(100 - left, (duration / totalMs) * 100));
                    const tone = (0, trace_utils_1.statusTone)(span.status);
                    return ((0, jsx_runtime_1.jsxs)("button", { className: `${span.span_id === selectedSpanId ? "active" : ""} trace-span-tone-${tone}`, onClick: () => onSelect(span), children: [(0, jsx_runtime_1.jsx)("span", { children: (0, trace_utils_1.formatOffset)(span.started_at, first) }), (0, jsx_runtime_1.jsxs)("strong", { children: [(0, jsx_runtime_1.jsx)("small", { children: (0, trace_utils_1.spanTypeLabel)(span.span_type) }), span.name] }), (0, jsx_runtime_1.jsx)("em", { className: `trace-status-${tone}`, children: (0, trace_utils_1.statusLabel)(span.status) }), (0, jsx_runtime_1.jsx)("span", { children: (0, trace_utils_1.formatDuration)(span.duration_ms) }), (0, jsx_runtime_1.jsx)("i", { className: "trace-waterfall-track", "aria-hidden": "true", children: (0, jsx_runtime_1.jsx)("b", { style: { left: `${left}%`, width: `${width}%` } }) })] }, span.span_id));
                }) }), spans.length === 0 ? (0, jsx_runtime_1.jsx)("p", { className: "muted", children: "No spans." }) : null] }));
}
