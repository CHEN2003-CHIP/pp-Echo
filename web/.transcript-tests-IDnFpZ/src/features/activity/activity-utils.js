"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.eventStableKey = eventStableKey;
exports.eventActivityId = eventActivityId;
exports.eventStatus = eventStatus;
exports.eventPhase = eventPhase;
exports.phaseLabel = phaseLabel;
exports.statusLabel = statusLabel;
exports.formatDurationMs = formatDurationMs;
exports.eventStartedAt = eventStartedAt;
exports.eventEndedAt = eventEndedAt;
exports.truncateText = truncateText;
exports.safeRawEvent = safeRawEvent;
exports.firstString = firstString;
exports.firstNumber = firstNumber;
function eventStableKey(event, index = 0) {
    const details = event.details || {};
    const activity = details.activity && typeof details.activity === "object" ? details.activity : {};
    const trace = details.trace && typeof details.trace === "object" ? details.trace : {};
    const eventId = firstString(event.event_id, activity.event_id, trace.event_id);
    if (eventId)
        return eventId;
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
function eventActivityId(event, index = 0) {
    const details = event.details || {};
    const activity = details.activity && typeof details.activity === "object" ? details.activity : {};
    const id = firstString(event.activity_id, activity.activity_id);
    if (id)
        return id;
    const runId = firstString(event.run_id, activity.run_id) || `run:${event.turn_id ?? "unknown"}`;
    const callId = firstString(details.tool_call_id);
    if (event.type.startsWith("tool_") || event.type.startsWith("sandbox_"))
        return `${runId}:tool:${callId || event.tool_name || firstString(details.token) || index}`;
    if (event.type.startsWith("planner_"))
        return `${runId}:planner:${firstString(details.token) || event.turn_id || "turnless"}`;
    if (event.type.startsWith("reasoning_") || event.type === "before_provider_request" || event.type === "provider_response" || event.type === "provider_error")
        return `${runId}:analysis:${event.turn_id ?? index}`;
    if (event.type.startsWith("subagent_"))
        return `${runId}:subagent:${firstString(details.child_session_id, details.session_id, details.spec_name) || event.turn_id || "turnless"}`;
    if (event.type.startsWith("checkpoint_") || event.type.startsWith("session_safe_rewind"))
        return `${runId}:checkpoint:${firstString(details.checkpoint_id, details.id, details.token) || event.turn_id || "turnless"}`;
    if (event.type === "approval_result" || event.type.includes("approval"))
        return `${runId}:approval:${firstString(details.token, details.approval_token) || event.turn_id || "turnless"}`;
    return `${runId}:${eventPhase(event)}:${event.type}:${event.turn_id ?? index}`;
}
function eventStatus(event) {
    const details = event.details || {};
    const activity = details.activity && typeof details.activity === "object" ? details.activity : {};
    const status = firstString(event.status, activity.status, details.status);
    if (status === "pending" || status === "running" || status === "success" || status === "warning" || status === "error" || status === "cancelled")
        return status;
    if (event.is_error || event.type === "error" || event.type === "tool_error" || event.type === "provider_error" || event.type.endsWith("_failed") || event.type.endsWith("_fail"))
        return "error";
    if (event.type.includes("rejected"))
        return "warning";
    if (event.type.includes("pending"))
        return "pending";
    if (event.type.endsWith("_start") || event.type === "tool_call" || event.type === "sandbox_preflight" || event.type === "before_provider_request" || event.type === "reasoning_delta" || event.type === "turn_phase_changed")
        return "running";
    return "success";
}
function eventPhase(event) {
    const details = event.details || {};
    const activity = details.activity && typeof details.activity === "object" ? details.activity : {};
    const phase = firstString(activity.phase);
    if (isActivityPhase(phase))
        return phase;
    if (event.type === "before_provider_request" || event.type === "reasoning_start")
        return "preparing";
    if (event.type === "provider_response" || event.type === "reasoning_end")
        return "finalizing";
    if (event.type.startsWith("reasoning_") || event.type === "provider_error")
        return "analyzing";
    if (event.type.startsWith("planner_"))
        return event.type.includes("gate") ? "approval" : "planning";
    if (event.type.startsWith("tool_") || event.type.startsWith("sandbox_"))
        return "tool";
    if (event.type === "approval_result" || event.type.includes("approval"))
        return "approval";
    if (event.type.includes("artifact"))
        return "artifact";
    if (event.type.startsWith("checkpoint_") || event.type.startsWith("session_safe_rewind"))
        return "checkpoint";
    if (event.type.startsWith("subagent_"))
        return "subagent";
    if (event.type.startsWith("queue_"))
        return "queue";
    if (event.type === "compaction" || event.type.startsWith("learning_"))
        return "memory";
    return "system";
}
function phaseLabel(phase) {
    const labels = {
        preparing: "Preparing",
        analyzing: "Analyzing",
        planning: "Planning",
        tool: "Tool call",
        approval: "Approval",
        artifact: "Artifact",
        checkpoint: "Checkpoint",
        subagent: "Subagent",
        message: "Message",
        finalizing: "Finalizing",
        queue: "Queue",
        memory: "Memory",
        system: "System",
        event: "Event"
    };
    return labels[phase] || "Activity";
}
function statusLabel(status) {
    if (status === "running")
        return "Running";
    if (status === "pending")
        return "Pending";
    if (status === "success")
        return "Done";
    if (status === "warning")
        return "Needs attention";
    if (status === "error")
        return "Failed";
    if (status === "cancelled")
        return "Cancelled";
    return status;
}
function formatDurationMs(elapsedMs) {
    const totalSeconds = Math.max(1, Math.round(elapsedMs / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return minutes ? `${minutes}m ${seconds}s` : `${seconds}s`;
}
function eventStartedAt(event) {
    const details = event.details || {};
    const activity = details.activity && typeof details.activity === "object" ? details.activity : {};
    return firstNumber(event.started_at, activity.started_at, event.timestamp);
}
function eventEndedAt(event) {
    const details = event.details || {};
    const activity = details.activity && typeof details.activity === "object" ? details.activity : {};
    return firstNumber(event.ended_at, activity.ended_at);
}
function truncateText(value, limit) {
    const clean = value.replace(/\s+/g, " ").trim();
    return clean.length <= limit ? clean : `${clean.slice(0, Math.max(0, limit - 1))}...`;
}
const SENSITIVE_KEY_RE = /(chain[_-]?of[_-]?thought|(^|[_-])cot($|[_-])|reasoning|scratchpad|hidden|system[_-]?prompt|developer[_-]?prompt|internal[_-]?prompt|deliberation|private)/i;
function safeRawEvent(value, fieldLimit = 1200, totalLimit = 4000) {
    const safe = redactValue(value, fieldLimit, new WeakSet());
    const text = JSON.stringify(safe, null, 2);
    return text.length <= totalLimit ? text : `${text.slice(0, Math.max(0, totalLimit - 1))}...`;
}
function redactValue(value, fieldLimit, seen) {
    if (typeof value === "string")
        return value.length <= fieldLimit ? value : `${value.slice(0, Math.max(0, fieldLimit - 1))}...`;
    if (typeof value !== "object" || value === null)
        return value;
    if (seen.has(value))
        return "[Circular]";
    seen.add(value);
    if (Array.isArray(value))
        return value.slice(0, 80).map((item) => redactValue(item, fieldLimit, seen));
    const output = {};
    Object.entries(value).forEach(([key, item]) => {
        output[key] = SENSITIVE_KEY_RE.test(key) ? "[redacted]" : redactValue(item, fieldLimit, seen);
    });
    return output;
}
function firstString(...values) {
    for (const value of values) {
        if (typeof value === "string" && value.trim())
            return value.trim();
        if (typeof value === "number")
            return String(value);
    }
    return "";
}
function firstNumber(...values) {
    for (const value of values) {
        if (typeof value === "number" && Number.isFinite(value))
            return value;
    }
    return undefined;
}
function isActivityPhase(value) {
    return ["preparing", "analyzing", "planning", "tool", "approval", "artifact", "checkpoint", "subagent", "message", "finalizing", "queue", "memory", "system", "event"].includes(value);
}
