"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.TraceToolCallsPanel = TraceToolCallsPanel;
exports.TraceSpanList = TraceSpanList;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
const trace_utils_1 = require("./trace-utils");
function dedupeToolSpans(spans) {
    const selected = new Map();
    const anonymous = [];
    for (const span of spans.filter((item) => item.span_type === "tool")) {
        const id = String(span.attributes.tool_call_id || "");
        if (!id) {
            anonymous.push(span);
            continue;
        }
        const current = selected.get(id);
        if (!current || (span.attributes.source === "tool_registry_middleware" && current.attributes.source !== "tool_registry_middleware")) {
            selected.set(id, span);
        }
    }
    return [...selected.values(), ...anonymous];
}
function TraceToolCallsPanel({ spans, selectedSpanId, onSelectSpan }) {
    const [filter, setFilter] = (0, react_1.useState)("all");
    const tools = (0, react_1.useMemo)(() => dedupeToolSpans(spans), [spans]);
    const filtered = tools.filter((span) => matchesFilter(span, filter));
    const filters = [["all", "All"], ["errors", "Errors"], ["changed", "Changed files"], ["approval", "Approval required"], ["shell", "Shell"]];
    return ((0, jsx_runtime_1.jsxs)("section", { className: "trace-inspect-section trace-tool-panel", children: [(0, jsx_runtime_1.jsxs)("div", { className: "trace-section-title", children: [(0, jsx_runtime_1.jsx)("h3", { children: "Tool Calls" }), (0, jsx_runtime_1.jsx)("div", { className: "trace-filter-pills", role: "tablist", "aria-label": "Tool call filters", children: filters.map(([value, label]) => ((0, jsx_runtime_1.jsx)("button", { className: filter === value ? "active" : "", onClick: () => setFilter(value), children: label }, value))) })] }), (0, jsx_runtime_1.jsx)("div", { className: "trace-tool-table-wrap", children: (0, jsx_runtime_1.jsxs)("table", { className: "trace-tool-table", children: [(0, jsx_runtime_1.jsx)("thead", { children: (0, jsx_runtime_1.jsxs)("tr", { children: [(0, jsx_runtime_1.jsx)("th", { children: "Tool" }), (0, jsx_runtime_1.jsx)("th", { children: "Status" }), (0, jsx_runtime_1.jsx)("th", { children: "Duration" }), (0, jsx_runtime_1.jsx)("th", { children: "Permission" }), (0, jsx_runtime_1.jsx)("th", { children: "Requires approval" }), (0, jsx_runtime_1.jsx)("th", { children: "Changed paths" }), (0, jsx_runtime_1.jsx)("th", { children: "Source" }), (0, jsx_runtime_1.jsx)("th", { children: "Error" })] }) }), (0, jsx_runtime_1.jsx)("tbody", { children: filtered.map((span) => {
                                const changed = changedPaths(span);
                                return ((0, jsx_runtime_1.jsxs)("tr", { className: span.span_id === selectedSpanId ? "active" : "", onClick: () => onSelectSpan?.(span), children: [(0, jsx_runtime_1.jsx)("td", { children: String(span.attributes.tool_name ?? span.name ?? "-") }), (0, jsx_runtime_1.jsx)("td", { children: (0, jsx_runtime_1.jsx)("em", { className: `trace-status-${(0, trace_utils_1.statusTone)(span.status)}`, children: (0, trace_utils_1.statusLabel)(span.status) }) }), (0, jsx_runtime_1.jsx)("td", { children: (0, trace_utils_1.formatDuration)(span.duration_ms) }), (0, jsx_runtime_1.jsx)("td", { children: textValue(span.attributes.permission ?? span.attributes.permission_level ?? span.attributes.risk_level) }), (0, jsx_runtime_1.jsx)("td", { children: requiresApproval(span) ? "Yes" : "No" }), (0, jsx_runtime_1.jsx)("td", { title: changed.join("\n"), children: changed.length ? changed.join(", ") : "-" }), (0, jsx_runtime_1.jsx)("td", { children: textValue(span.attributes.source) }), (0, jsx_runtime_1.jsx)("td", { children: span.error_message || textValue(span.output.error ?? span.output.error_message) })] }, span.span_id));
                            }) })] }) }), filtered.length === 0 ? (0, jsx_runtime_1.jsx)("p", { className: "muted", children: "No tool calls for this filter." }) : null] }));
}
function TraceSpanList({ title, spans, renderMeta, selectedSpanId, onSelectSpan }) {
    return ((0, jsx_runtime_1.jsxs)("section", { className: "trace-inspect-section trace-span-list", children: [(0, jsx_runtime_1.jsx)("h3", { children: title }), spans.map((span) => ((0, jsx_runtime_1.jsxs)("details", { className: span.span_id === selectedSpanId ? "active" : "", children: [(0, jsx_runtime_1.jsx)("summary", { onClick: () => onSelectSpan?.(span), children: renderMeta(span) }), (0, jsx_runtime_1.jsx)("pre", { children: (0, trace_utils_1.safeJsonStringify)({ input: span.input, output: span.output, attributes: span.attributes }) })] }, span.span_id))), spans.length === 0 ? (0, jsx_runtime_1.jsx)("p", { className: "muted", children: "No records." }) : null] }));
}
function matchesFilter(span, filter) {
    if (filter === "errors")
        return span.status === "error" || Boolean(span.error_message || span.output.error || span.output.error_message);
    if (filter === "changed")
        return changedPaths(span).length > 0;
    if (filter === "approval")
        return requiresApproval(span);
    if (filter === "shell")
        return String(span.attributes.tool_name ?? span.name ?? "").toLowerCase().includes("shell");
    return true;
}
function changedPaths(span) {
    const raw = span.output.changed_paths || span.attributes.changed_paths;
    return Array.isArray(raw) ? raw.map((item) => String(item)).filter(Boolean) : [];
}
function requiresApproval(span) {
    return Boolean(span.attributes.requires_approval || span.attributes.approval_required || span.output.requires_approval || span.output.approval_required);
}
function textValue(value) {
    if (value === null || value === undefined || value === "")
        return "-";
    return String(value);
}
