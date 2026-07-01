"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.TraceInspectPage = TraceInspectPage;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
const lucide_react_1 = require("lucide-react");
const api_1 = require("../../api");
const TraceRunDetail_1 = require("./TraceRunDetail");
const TraceRunList_1 = require("./TraceRunList");
const trace_utils_1 = require("./trace-utils");
function TraceInspectPage({ activeSessionId, initialRunId, onBack }) {
    const [runs, setRuns] = (0, react_1.useState)([]);
    const [selectedRunId, setSelectedRunId] = (0, react_1.useState)(initialRunId || null);
    const [detail, setDetail] = (0, react_1.useState)(null);
    const [selectedSpan, setSelectedSpan] = (0, react_1.useState)(null);
    const [search, setSearch] = (0, react_1.useState)("");
    const [statusFilter, setStatusFilter] = (0, react_1.useState)("all");
    const [error, setError] = (0, react_1.useState)("");
    const [isRunListCollapsed, setIsRunListCollapsed] = (0, react_1.useState)(false);
    const currentStatus = detail?.summary?.status || runs.find((run) => run.run_id === selectedRunId)?.status;
    const shouldPoll = currentStatus === "running" || currentStatus === "pending";
    (0, react_1.useEffect)(() => { refresh().catch((err) => setError(errorMessage(err))); }, [activeSessionId]);
    (0, react_1.useEffect)(() => {
        if (!selectedRunId)
            return;
        loadDetail(selectedRunId).catch((err) => setError(errorMessage(err)));
    }, [selectedRunId]);
    (0, react_1.useEffect)(() => {
        if (!shouldPoll || !selectedRunId)
            return;
        const timer = window.setInterval(() => loadDetail(selectedRunId).catch((err) => setError(errorMessage(err))), 1500);
        return () => window.clearInterval(timer);
    }, [shouldPoll, selectedRunId]);
    const headerRun = (0, react_1.useMemo)(() => runs.find((run) => run.run_id === selectedRunId), [runs, selectedRunId]);
    async function refresh() {
        setError("");
        let payload = await api_1.api.traces({ limit: 80, sessionId: activeSessionId || undefined }).catch(async () => api_1.api.traces({ limit: 80 }));
        setRuns(payload.runs);
        const nextRunId = selectedRunId || initialRunId || payload.runs[0]?.run_id || null;
        setSelectedRunId(nextRunId);
        if (nextRunId)
            await loadDetail(nextRunId);
    }
    async function loadDetail(runId) {
        const loaded = await api_1.api.traceDetail(runId);
        setDetail(loaded);
        setSelectedSpan((current) => loaded.spans.find((span) => span.span_id === current?.span_id) || loaded.spans[0] || null);
    }
    function copyJson() {
        navigator.clipboard?.writeText(JSON.stringify(detail, null, 2)).catch(() => undefined);
    }
    return ((0, jsx_runtime_1.jsxs)("div", { className: "trace-inspect-page", children: [(0, jsx_runtime_1.jsxs)("header", { className: "trace-inspect-toolbar", children: [(0, jsx_runtime_1.jsxs)("button", { onClick: onBack, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.ArrowLeft, { size: 16 }), "\u8FD4\u56DE\u4F1A\u8BDD"] }), (0, jsx_runtime_1.jsxs)("button", { onClick: () => refresh().catch((err) => setError(errorMessage(err))), children: [(0, jsx_runtime_1.jsx)(lucide_react_1.RefreshCw, { size: 16 }), "\u5237\u65B0"] }), (0, jsx_runtime_1.jsxs)("button", { onClick: () => setIsRunListCollapsed((value) => !value), title: isRunListCollapsed ? "Show run list" : "Collapse run list", children: [isRunListCollapsed ? (0, jsx_runtime_1.jsx)(lucide_react_1.PanelLeftOpen, { size: 16 }) : (0, jsx_runtime_1.jsx)(lucide_react_1.PanelLeftClose, { size: 16 }), isRunListCollapsed ? "Runs" : "Hide runs"] }), (0, jsx_runtime_1.jsxs)("span", { children: ["run ", selectedRunId ? (0, trace_utils_1.compactId)(selectedRunId) : "-"] }), (0, jsx_runtime_1.jsx)("span", { children: currentStatus ? (0, trace_utils_1.statusLabel)(currentStatus) : "-" }), (0, jsx_runtime_1.jsxs)("button", { onClick: copyJson, disabled: !detail, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Copy, { size: 16 }), "\u590D\u5236 JSON"] })] }), error ? (0, jsx_runtime_1.jsx)("div", { className: "trace-inspect-error", children: error }) : null, (0, jsx_runtime_1.jsxs)("div", { className: `trace-inspect-layout ${isRunListCollapsed ? "trace-inspect-layout-collapsed" : ""}`, children: [(0, jsx_runtime_1.jsx)(TraceRunList_1.TraceRunList, { runs: runs, selectedRunId: selectedRunId, onSelect: setSelectedRunId, search: search, onSearch: setSearch, statusFilter: statusFilter, onStatusFilter: setStatusFilter }), (0, jsx_runtime_1.jsx)(TraceRunDetail_1.TraceRunDetail, { detail: detail || (headerRun ? null : null), selectedSpan: selectedSpan, onSelectSpan: setSelectedSpan })] })] }));
}
function errorMessage(error) {
    return error instanceof Error ? error.message : String(error);
}
