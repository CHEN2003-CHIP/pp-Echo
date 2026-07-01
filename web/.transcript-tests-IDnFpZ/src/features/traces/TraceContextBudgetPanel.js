"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.TraceContextBudgetPanel = TraceContextBudgetPanel;
const jsx_runtime_1 = require("react/jsx-runtime");
const trace_utils_1 = require("./trace-utils");
function TraceContextBudgetPanel({ detail }) {
    const record = extractContextBudget(detail);
    if (!record) {
        return (0, jsx_runtime_1.jsxs)("section", { className: "trace-inspect-section", children: [(0, jsx_runtime_1.jsx)("h3", { children: "Context Budget" }), (0, jsx_runtime_1.jsx)("p", { className: "muted", children: "No context budget report." })] });
    }
    const report = record.report;
    const total = report.total_budget || 0;
    const used = report.used || 0;
    const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
    const sections = Object.entries(report.per_section || {});
    const included = report.included_items || [];
    const dropped = report.dropped_items || [];
    const warnings = [...(report.warnings || []), ...(record.coreMemoryBudgetError ? ["Core memory budget warning"] : [])];
    return ((0, jsx_runtime_1.jsxs)("section", { className: "trace-inspect-section trace-context-budget", children: [(0, jsx_runtime_1.jsx)("h3", { children: "Context Budget" }), (0, jsx_runtime_1.jsxs)("div", { className: "trace-budget-overview", children: [(0, jsx_runtime_1.jsxs)("strong", { children: [used.toLocaleString(), " / ", total.toLocaleString()] }), (0, jsx_runtime_1.jsxs)("span", { children: [pct, "% used"] })] }), (0, jsx_runtime_1.jsx)(BudgetBar, { value: used, total: total }), (0, jsx_runtime_1.jsx)("div", { className: "trace-budget-sections", children: sections.map(([name, usage]) => ((0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("strong", { children: name }), (0, jsx_runtime_1.jsxs)("span", { children: [Number(usage.used || 0).toLocaleString(), " / ", Number(usage.budget || 0).toLocaleString()] })] }), (0, jsx_runtime_1.jsx)(BudgetBar, { value: usage.used || 0, total: usage.budget || total }), (0, jsx_runtime_1.jsxs)("small", { children: ["included ", usage.included_count || 0, " | dropped ", usage.dropped_count || 0] })] }, name))) }), sections.length === 0 ? (0, jsx_runtime_1.jsx)("p", { className: "muted", children: "No section usage records." }) : null, (0, jsx_runtime_1.jsx)(SourceTable, { title: "Included Sources", rows: included }), (0, jsx_runtime_1.jsx)(SourceTable, { title: "Dropped Sources", rows: dropped, dropReasons: report.drop_reasons || {} }), report.fallback_reason || warnings.length ? ((0, jsx_runtime_1.jsxs)("div", { className: "trace-budget-warnings", children: [report.fallback_reason ? (0, jsx_runtime_1.jsxs)("p", { children: [(0, jsx_runtime_1.jsx)("strong", { children: "Fallback" }), (0, jsx_runtime_1.jsx)("span", { children: report.fallback_reason })] }) : null, warnings.map((warning) => (0, jsx_runtime_1.jsxs)("p", { children: [(0, jsx_runtime_1.jsx)("strong", { children: "Warning" }), (0, jsx_runtime_1.jsx)("span", { children: warning })] }, warning))] })) : null, (0, jsx_runtime_1.jsxs)("details", { children: [(0, jsx_runtime_1.jsx)("summary", { children: "Raw budget report" }), (0, jsx_runtime_1.jsx)("pre", { children: (0, trace_utils_1.safeJsonStringify)(report) })] })] }));
}
function BudgetBar({ value, total }) {
    const width = total > 0 ? Math.min(100, Math.max(0, (value / total) * 100)) : 0;
    return (0, jsx_runtime_1.jsx)("div", { className: "trace-budget-bar", "aria-label": `${Math.round(width)}%`, children: (0, jsx_runtime_1.jsx)("span", { style: { width: `${width}%` } }) });
}
function SourceTable({ title, rows, dropReasons }) {
    return ((0, jsx_runtime_1.jsxs)("div", { className: "trace-source-table", children: [(0, jsx_runtime_1.jsx)("h4", { children: title }), rows.length ? ((0, jsx_runtime_1.jsxs)("table", { children: [(0, jsx_runtime_1.jsx)("thead", { children: (0, jsx_runtime_1.jsxs)("tr", { children: [(0, jsx_runtime_1.jsx)("th", { children: "Source" }), (0, jsx_runtime_1.jsx)("th", { children: "Section" }), (0, jsx_runtime_1.jsx)("th", { children: "Tokens/Chars" }), (0, jsx_runtime_1.jsx)("th", { children: "Reason" })] }) }), (0, jsx_runtime_1.jsx)("tbody", { children: rows.map((row, index) => {
                            const source = textValue(row.source || row.name || row.path || row.id || `#${index + 1}`);
                            return ((0, jsx_runtime_1.jsxs)("tr", { children: [(0, jsx_runtime_1.jsx)("td", { children: source }), (0, jsx_runtime_1.jsx)("td", { children: textValue(row.section ?? row.kind ?? row.type) }), (0, jsx_runtime_1.jsx)("td", { children: textValue(row.used ?? row.tokens ?? row.chars ?? row.length) }), (0, jsx_runtime_1.jsx)("td", { children: textValue(row.reason ?? dropReasons?.[source]) })] }, `${source}-${index}`));
                        }) })] })) : (0, jsx_runtime_1.jsxs)("p", { className: "muted", children: ["No ", title.toLowerCase(), "."] })] }));
}
function extractContextBudget(detail) {
    const span = [...detail.spans].reverse().find((item) => item.name === "context.build" || item.span_type === "context");
    if (span?.output?.context_payload_version !== 2) {
        return null;
    }
    const context = objectValue(span.output.context);
    const report = objectValue(context?.budget_report);
    if (!context || !report)
        return null;
    return { report: report, coreMemoryBudgetError: Boolean(context.core_memory_budget_error || span.attributes?.core_memory_budget_error) };
}
function objectValue(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : null;
}
function textValue(value) {
    if (value === null || value === undefined || value === "")
        return "-";
    return String(value);
}
