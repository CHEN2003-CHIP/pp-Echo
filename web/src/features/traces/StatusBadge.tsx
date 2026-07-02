import type { TraceStatus } from "../../api";

export function StatusBadge({ status, label }: { status?: TraceStatus | string | null; label?: string }) {
  const tone = badgeTone(status);
  return (
    <span className={`trace-badge trace-badge-${tone}`}>
      <span className="trace-badge-dot" />
      {label || statusLabel(status)}
    </span>
  );
}

export function badgeTone(status?: string | null) {
  if (status === "ok" || status === "success") return "success";
  if (status === "error" || status === "blocked" || status === "failed") return "danger";
  if (status === "running" || status === "pending" || status === "warning") return "warn";
  if (status === "low" || status === "medium" || status === "high") return status === "low" ? "success" : status === "medium" ? "warn" : "danger";
  return "neutral";
}

function statusLabel(status?: string | null) {
  const labels: Record<string, string> = {
    ok: "Success",
    success: "Success",
    error: "Error",
    blocked: "Blocked",
    pending: "Pending",
    running: "Running",
    cancelled: "Cancelled"
  };
  return status ? labels[status] || status : "Not captured";
}
