"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.TraceSpanInspector = TraceSpanInspector;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
const trace_utils_1 = require("./trace-utils");
function TraceSpanInspector({ span }) {
    if (!span)
        return (0, jsx_runtime_1.jsxs)("section", { className: "trace-inspect-section", children: [(0, jsx_runtime_1.jsx)("h3", { children: "Span" }), (0, jsx_runtime_1.jsx)("p", { className: "muted", children: "Select a timeline span." })] });
    const rows = summaryRows(span);
    return ((0, jsx_runtime_1.jsxs)("section", { className: "trace-inspect-section trace-span-inspector", children: [(0, jsx_runtime_1.jsx)("h3", { children: span.name }), (0, jsx_runtime_1.jsxs)("dl", { children: [(0, jsx_runtime_1.jsx)("dt", { children: "Type" }), (0, jsx_runtime_1.jsx)("dd", { children: (0, trace_utils_1.spanTypeLabel)(span.span_type) }), (0, jsx_runtime_1.jsx)("dt", { children: "Status" }), (0, jsx_runtime_1.jsx)("dd", { children: (0, trace_utils_1.statusLabel)(span.status) }), (0, jsx_runtime_1.jsx)("dt", { children: "Duration" }), (0, jsx_runtime_1.jsx)("dd", { children: (0, trace_utils_1.formatDuration)(span.duration_ms) }), (0, jsx_runtime_1.jsx)("dt", { children: "Error" }), (0, jsx_runtime_1.jsx)("dd", { children: span.error_message || "-" }), rows.map(([label, value]) => ((0, jsx_runtime_1.jsxs)(react_1.Fragment, { children: [(0, jsx_runtime_1.jsx)("dt", { children: label }), (0, jsx_runtime_1.jsx)("dd", { children: formatValue(value) })] }, label)))] }), (0, jsx_runtime_1.jsxs)("details", { children: [(0, jsx_runtime_1.jsx)("summary", { children: "Attributes" }), (0, jsx_runtime_1.jsx)("pre", { children: (0, trace_utils_1.safeJsonStringify)(span.attributes) })] }), (0, jsx_runtime_1.jsxs)("details", { children: [(0, jsx_runtime_1.jsx)("summary", { children: "Input" }), (0, jsx_runtime_1.jsx)("pre", { children: (0, trace_utils_1.safeJsonStringify)(span.input) })] }), (0, jsx_runtime_1.jsxs)("details", { children: [(0, jsx_runtime_1.jsx)("summary", { children: "Output" }), (0, jsx_runtime_1.jsx)("pre", { children: (0, trace_utils_1.safeJsonStringify)(span.output) })] })] }));
}
function summaryRows(span) {
    if (span.span_type === "llm" || span.name === "llm.call") {
        return [
            ["Provider", span.attributes.provider],
            ["Model", span.attributes.model],
            ["Input Tokens", span.attributes.input_tokens ?? span.output.input_tokens],
            ["Output Tokens", span.attributes.output_tokens ?? span.output.output_tokens],
            ["Total Tokens", span.attributes.total_tokens ?? span.output.total_tokens],
            ["Cost", moneyValue(span.attributes.cost_usd ?? span.output.cost_usd)],
            ["Retries", span.attributes.retry_count],
            ["Request ID", span.attributes.request_id]
        ];
    }
    if (span.span_type === "tool" || span.name === "tool.call") {
        return [
            ["Tool", span.attributes.tool_name ?? span.name],
            ["Tool Call ID", span.attributes.tool_call_id],
            ["Source", span.attributes.source],
            ["Permission", span.attributes.permission ?? span.attributes.permission_level ?? span.attributes.risk_level],
            ["Requires Approval", boolText(span.attributes.requires_approval ?? span.attributes.approval_required ?? span.output.requires_approval)],
            ["Changed Paths", changedPaths(span).join(", ")]
        ];
    }
    if (span.span_type === "context" || span.name === "context.build") {
        const context = objectValue(span.output.context);
        const report = objectValue(context?.budget_report);
        return [
            ["Payload Version", span.output.context_payload_version],
            ["Used", report?.used],
            ["Total Budget", report?.total_budget],
            ["Included Sources", arrayLength(report?.included_items)],
            ["Dropped Sources", arrayLength(report?.dropped_items)],
            ["Fallback", report?.fallback_reason]
        ];
    }
    if (span.span_type === "approval" || span.name === "approval.decision") {
        return [
            ["Decision", span.attributes.decision ?? span.output.decision],
            ["Token", span.attributes.approval_token ?? span.output.approval_token],
            ["Payload Digest", span.attributes.payload_digest ?? span.output.payload_digest],
            ["Reason", span.attributes.reason ?? span.output.reason]
        ];
    }
    if (span.span_type === "checkpoint" || span.name.startsWith("checkpoint.")) {
        return [
            ["Checkpoint", span.attributes.checkpoint_id ?? span.output.checkpoint_id],
            ["Reason", span.attributes.reason ?? span.output.reason],
            ["Passed", boolText(span.attributes.passed ?? span.output.passed)],
            ["Changed Paths", changedPaths(span).join(", ")]
        ];
    }
    return [];
}
function changedPaths(span) {
    const raw = span.output.changed_paths || span.attributes.changed_paths;
    return Array.isArray(raw) ? raw.map((item) => String(item)).filter(Boolean) : [];
}
function objectValue(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : null;
}
function arrayLength(value) {
    return Array.isArray(value) ? value.length : undefined;
}
function moneyValue(value) {
    return typeof value === "number" ? `$${value.toFixed(6)}` : value;
}
function boolText(value) {
    if (value === true)
        return "Yes";
    if (value === false)
        return "No";
    return value;
}
function formatValue(value) {
    if (value === null || value === undefined || value === "")
        return "-";
    return String(value);
}
