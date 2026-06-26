import type { TraceSpan } from "../../api";

export function spanTypeLabel(type: string) {
  const labels: Record<string, string> = {
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

export function statusLabel(status: string) {
  const labels: Record<string, string> = {
    running: "运行中",
    ok: "成功",
    error: "失败",
    blocked: "已拦截",
    pending: "等待中",
    cancelled: "已取消"
  };
  return labels[status] || status;
}

export function statusTone(status: string) {
  if (status === "error" || status === "blocked") return "danger";
  if (status === "pending" || status === "running") return "warning";
  if (status === "ok") return "success";
  return "muted";
}

export function formatDuration(ms?: number | null) {
  if (ms === undefined || ms === null) return "-";
  if (ms < 1000) return `${ms}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

export function formatRelativeTime(timestamp?: number | null) {
  if (!timestamp) return "-";
  return new Date(timestamp * 1000).toLocaleString();
}

export function formatOffset(startedAt?: number | null, baseStartedAt?: number | null) {
  if (!startedAt || !baseStartedAt) return "-";
  return `+${formatDuration(Math.max(0, Math.round((startedAt - baseStartedAt) * 1000)))}`;
}

export function safeJsonStringify(value: unknown) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function groupApprovalSpansByDigest(spans: TraceSpan[]) {
  const groups = new Map<string, TraceSpan[]>();
  spans.filter((span) => span.span_type === "approval").forEach((span) => {
    const digest = String(span.attributes.payload_digest || span.output.payload_digest || span.attributes.approval_token || "unknown");
    groups.set(digest, [...(groups.get(digest) || []), span]);
  });
  return Array.from(groups.entries()).map(([digest, items]) => ({ digest, items }));
}

export function compactId(value: string) {
  return value ? value.slice(0, 8) : "-";
}
