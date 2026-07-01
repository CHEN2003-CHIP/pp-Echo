"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.spanTypeLabel = spanTypeLabel;
exports.statusLabel = statusLabel;
exports.statusTone = statusTone;
exports.formatDuration = formatDuration;
exports.formatRelativeTime = formatRelativeTime;
exports.formatOffset = formatOffset;
exports.safeJsonStringify = safeJsonStringify;
exports.groupApprovalSpansByDigest = groupApprovalSpansByDigest;
exports.compactId = compactId;
function spanTypeLabel(type) {
    const labels = {
        run: "运行",
        turn: "回合",
        context: "上下文构建",
        llm: "模型调用",
        tool: "工具调用",
        policy: "安全策略",
        approval: "审批",
        memory: "记忆召回",
        checkpoint: "检查点",
        subagent: "子 Agent",
        eval: "评测",
        system: "系统"
    };
    return labels[type] || type;
}
function statusLabel(status) {
    const labels = {
        running: "运行中",
        ok: "成功",
        error: "失败",
        blocked: "已拦截",
        pending: "等待中",
        cancelled: "已取消"
    };
    return labels[status] || status;
}
function statusTone(status) {
    if (status === "error" || status === "blocked")
        return "danger";
    if (status === "pending" || status === "running")
        return "warning";
    if (status === "ok")
        return "success";
    return "muted";
}
function formatDuration(ms) {
    if (ms === undefined || ms === null)
        return "-";
    if (ms < 1000)
        return `${ms}ms`;
    const seconds = ms / 1000;
    if (seconds < 60)
        return `${seconds.toFixed(1)}s`;
    return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}
function formatRelativeTime(timestamp) {
    if (!timestamp)
        return "-";
    return new Date(timestamp * 1000).toLocaleString();
}
function formatOffset(startedAt, baseStartedAt) {
    if (!startedAt || !baseStartedAt)
        return "-";
    return `+${formatDuration(Math.max(0, Math.round((startedAt - baseStartedAt) * 1000)))}`;
}
function safeJsonStringify(value) {
    try {
        return JSON.stringify(value, null, 2);
    }
    catch {
        return String(value);
    }
}
function groupApprovalSpansByDigest(spans) {
    const groups = new Map();
    spans.filter((span) => span.span_type === "approval").forEach((span) => {
        const digest = String(span.attributes.payload_digest || span.output.payload_digest || span.attributes.approval_token || "unknown");
        groups.set(digest, [...(groups.get(digest) || []), span]);
    });
    return Array.from(groups.entries()).map(([digest, items]) => ({ digest, items }));
}
function compactId(value) {
    return value ? value.slice(0, 8) : "-";
}
