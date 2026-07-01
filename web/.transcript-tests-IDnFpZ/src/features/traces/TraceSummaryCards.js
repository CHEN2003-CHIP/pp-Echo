"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.TraceSummaryCards = TraceSummaryCards;
const jsx_runtime_1 = require("react/jsx-runtime");
const trace_utils_1 = require("./trace-utils");
function TraceSummaryCards({ summary }) {
    const cost = summary?.total_cost_usd == null ? "N/A" : `$${summary.total_cost_usd.toFixed(6)}`;
    const items = [
        { label: "Status", value: summary ? (0, trace_utils_1.statusLabel)(summary.status) : "-", tone: toneFor("status", summary?.status) },
        { label: "Duration", value: (0, trace_utils_1.formatDuration)(summary?.duration_ms), tone: "neutral" },
        { label: "LLM", value: summary?.llm_calls ?? 0, tone: "neutral" },
        { label: "Tools", value: summary?.tool_calls ?? 0, tone: "neutral" },
        { label: "Approvals", value: summary?.approval_count ?? 0, tone: "neutral" },
        { label: "Memory", value: summary?.memory_recall_count ?? 0, tone: "neutral" },
        { label: "Checkpoints", value: summary?.checkpoint_count ?? 0, tone: "neutral" },
        { label: "Errors", value: summary?.error_count ?? 0, tone: Number(summary?.error_count || 0) > 0 ? "negative" : "positive" },
        { label: "Risk", value: summary?.risk_level ?? "-", tone: toneFor("risk", summary?.risk_level) },
        { label: "Input Tokens", value: summary?.total_input_tokens ?? 0, tone: "neutral" },
        { label: "Output Tokens", value: summary?.total_output_tokens ?? 0, tone: "neutral" },
        { label: "Total Tokens", value: summary?.total_tokens ?? 0, tone: "neutral" },
        { label: "Cost", value: cost, tone: "neutral" },
        { label: "LLM Avg Latency", value: (0, trace_utils_1.formatDuration)(summary?.llm_latency_ms_avg), tone: "neutral" },
        { label: "Retry Count", value: summary?.llm_retry_count ?? 0, tone: Number(summary?.llm_retry_count || 0) > 0 ? "negative" : "positive" }
    ];
    return ((0, jsx_runtime_1.jsx)("dl", { className: "trace-inspect-summary", "aria-label": "Trace summary", children: items.map((item) => ((0, jsx_runtime_1.jsxs)("div", { className: `trace-stat trace-stat-${item.tone}`, children: [(0, jsx_runtime_1.jsx)("dt", { children: item.label }), (0, jsx_runtime_1.jsxs)("dd", { children: [(0, jsx_runtime_1.jsx)("strong", { children: item.value }), item.tone !== "neutral" ? (0, jsx_runtime_1.jsx)("em", { children: item.tone === "positive" ? "OK" : "!" }) : null] })] }, item.label))) }));
}
function toneFor(kind, value) {
    const normalized = String(value || "").toLowerCase();
    if (kind === "status") {
        if (["success", "completed", "ok"].some((item) => normalized.includes(item)))
            return "positive";
        if (["error", "failed", "cancel"].some((item) => normalized.includes(item)))
            return "negative";
    }
    if (kind === "risk" && ["high", "critical"].some((item) => normalized.includes(item)))
        return "negative";
    return "neutral";
}
