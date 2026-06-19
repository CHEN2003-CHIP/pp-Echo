import type { RuntimeEvent } from "../../api";
import type { ActivityPhase, ActivityStatus } from "./activity-types";

export function eventStableKey(event: RuntimeEvent, index = 0) {
  const details = event.details || {};
  const activity = details.activity && typeof details.activity === "object" ? details.activity as Record<string, unknown> : {};
  const trace = details.trace && typeof details.trace === "object" ? details.trace as Record<string, unknown> : {};
  const eventId = firstString(event.event_id, activity.event_id, trace.event_id);
  if (eventId) return eventId;
  const detailKey = firstString(details.event_id, details.id, details.tool_call_id, details.token, details.artifact_id);
  return [
    event.type,
    event.turn_id ?? "",
    event.phase ?? "",
    event.timestamp ?? index,
    event.tool_name ?? "",
    event.message ?? "",
    detailKey ?? ""
  ].join("\u001f");
}

export function eventActivityId(event: RuntimeEvent, index = 0) {
  const details = event.details || {};
  const activity = details.activity && typeof details.activity === "object" ? details.activity as Record<string, unknown> : {};
  const id = firstString(event.activity_id, activity.activity_id);
  if (id) return id;
  const runId = firstString(event.run_id, activity.run_id) || `run:${event.turn_id ?? "unknown"}`;
  const callId = firstString(details.tool_call_id);
  if (event.type.startsWith("tool_")) return `${runId}:tool:${callId || event.tool_name || index}`;
  if (event.type.startsWith("planner_")) return `${runId}:planner:${firstString(details.token) || event.turn_id || "turnless"}`;
  if (event.type.startsWith("reasoning_") || event.type === "before_provider_request" || event.type === "provider_response" || event.type === "provider_error") return `${runId}:reasoning:${event.turn_id ?? index}`;
  if (event.type.startsWith("subagent_")) return `${runId}:subagent:${firstString(details.child_session_id, details.session_id, details.spec_name) || event.turn_id || "turnless"}`;
  if (event.type.startsWith("checkpoint_") || event.type.startsWith("session_safe_rewind")) return `${runId}:checkpoint:${firstString(details.checkpoint_id, details.id, details.token) || event.turn_id || "turnless"}`;
  if (event.type === "approval_result" || event.type.includes("approval")) return `${runId}:approval:${firstString(details.token, details.approval_token) || event.turn_id || "turnless"}`;
  return `${runId}:${eventPhase(event)}:${event.type}:${event.turn_id ?? index}`;
}

export function eventStatus(event: RuntimeEvent): ActivityStatus {
  const details = event.details || {};
  const activity = details.activity && typeof details.activity === "object" ? details.activity as Record<string, unknown> : {};
  const status = firstString(event.status, activity.status, details.status);
  if (status === "pending" || status === "running" || status === "success" || status === "warning" || status === "error" || status === "cancelled") return status;
  if (event.is_error || event.type === "error" || event.type === "tool_error" || event.type === "provider_error" || event.type.endsWith("_failed") || event.type.endsWith("_fail")) return "error";
  if (event.type.includes("rejected")) return "warning";
  if (event.type.includes("pending")) return "pending";
  if (event.type.endsWith("_start") || event.type === "tool_call" || event.type === "before_provider_request" || event.type === "reasoning_delta" || event.type === "turn_phase_changed") return "running";
  return "success";
}

export function eventPhase(event: RuntimeEvent): ActivityPhase {
  const details = event.details || {};
  const activity = details.activity && typeof details.activity === "object" ? details.activity as Record<string, unknown> : {};
  const phase = firstString(activity.phase);
  if (isActivityPhase(phase)) return phase;
  if (event.type.startsWith("reasoning_") || event.type === "before_provider_request" || event.type === "provider_response" || event.type === "provider_error") return "reasoning";
  if (event.type.startsWith("planner_")) return event.type.includes("gate") ? "approval" : "planning";
  if (event.type.startsWith("tool_")) return "tool";
  if (event.type === "approval_result" || event.type.includes("approval")) return "approval";
  if (event.type.includes("artifact")) return "artifact";
  if (event.type.startsWith("checkpoint_") || event.type.startsWith("session_safe_rewind")) return "checkpoint";
  if (event.type.startsWith("subagent_")) return "subagent";
  if (event.type.startsWith("queue_")) return "queue";
  if (event.type === "compaction" || event.type.startsWith("learning_")) return "memory";
  return "system";
}

export function phaseLabel(phase: ActivityPhase) {
  const labels: Record<ActivityPhase, string> = {
    reasoning: "Thinking",
    planning: "Planning",
    tool: "Tool call",
    approval: "Approval",
    artifact: "Artifact",
    checkpoint: "Checkpoint",
    subagent: "Subagent",
    queue: "Queue",
    memory: "Memory",
    system: "System",
    event: "Event"
  };
  return labels[phase] || "Activity";
}

export function statusLabel(status: ActivityStatus) {
  if (status === "running") return "Running";
  if (status === "pending") return "Pending";
  if (status === "success") return "Done";
  if (status === "warning") return "Needs attention";
  if (status === "error") return "Failed";
  if (status === "cancelled") return "Cancelled";
  return status;
}

export function formatDurationMs(elapsedMs: number) {
  const totalSeconds = Math.max(1, Math.round(elapsedMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes ? `${minutes}m ${seconds}s` : `${seconds}s`;
}

export function eventStartedAt(event: RuntimeEvent) {
  const details = event.details || {};
  const activity = details.activity && typeof details.activity === "object" ? details.activity as Record<string, unknown> : {};
  return firstNumber(event.started_at, activity.started_at, event.timestamp);
}

export function eventEndedAt(event: RuntimeEvent) {
  const details = event.details || {};
  const activity = details.activity && typeof details.activity === "object" ? details.activity as Record<string, unknown> : {};
  return firstNumber(event.ended_at, activity.ended_at);
}

export function truncateText(value: string, limit: number) {
  const clean = value.replace(/\s+/g, " ").trim();
  return clean.length <= limit ? clean : `${clean.slice(0, Math.max(0, limit - 1))}...`;
}

export function firstString(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number") return String(value);
  }
  return "";
}

export function firstNumber(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return undefined;
}

function isActivityPhase(value: string): value is ActivityPhase {
  return ["reasoning", "planning", "tool", "approval", "artifact", "checkpoint", "subagent", "queue", "memory", "system", "event"].includes(value);
}
