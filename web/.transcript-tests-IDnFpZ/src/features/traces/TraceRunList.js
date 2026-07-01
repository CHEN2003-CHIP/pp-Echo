"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.TraceRunList = TraceRunList;
const jsx_runtime_1 = require("react/jsx-runtime");
const trace_utils_1 = require("./trace-utils");
function TraceRunList({ runs, selectedRunId, onSelect, search, onSearch, statusFilter, onStatusFilter }) {
    const filtered = runs.filter((run) => {
        const matchesStatus = statusFilter === "all" || run.status === statusFilter;
        const haystack = `${run.run_id} ${run.session_id || ""} ${run.user_goal_preview}`.toLowerCase();
        return matchesStatus && haystack.includes(search.toLowerCase());
    });
    return ((0, jsx_runtime_1.jsxs)("aside", { className: "trace-inspect-sidebar", children: [(0, jsx_runtime_1.jsxs)("div", { className: "trace-inspect-filters", children: [(0, jsx_runtime_1.jsx)("input", { value: search, onChange: (event) => onSearch(event.target.value), placeholder: "Search traces" }), (0, jsx_runtime_1.jsx)("select", { value: statusFilter, onChange: (event) => onStatusFilter(event.target.value), children: ["all", "ok", "error", "pending", "blocked", "running", "cancelled"].map((item) => (0, jsx_runtime_1.jsx)("option", { value: item, children: item }, item)) })] }), (0, jsx_runtime_1.jsx)("div", { className: "trace-inspect-run-list", children: filtered.map((run) => ((0, jsx_runtime_1.jsxs)("button", { className: run.run_id === selectedRunId ? "active" : "", onClick: () => onSelect(run.run_id), children: [(0, jsx_runtime_1.jsxs)("strong", { children: [(0, trace_utils_1.compactId)(run.run_id), " ", (0, jsx_runtime_1.jsx)("em", { className: `trace-status-${(0, trace_utils_1.statusTone)(run.status)}`, children: (0, trace_utils_1.statusLabel)(run.status) })] }), (0, jsx_runtime_1.jsx)("span", { children: run.user_goal_preview || run.session_id || "trace run" }), (0, jsx_runtime_1.jsxs)("small", { children: [(0, trace_utils_1.formatRelativeTime)(run.started_at), " \u00B7 ", (0, trace_utils_1.formatDuration)(run.duration_ms)] })] }, run.run_id))) })] }));
}
