"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildActivityRuns = buildActivityRuns;
exports.buildActivitySummary = buildActivitySummary;
exports.isActivityRuntimeEvent = isActivityRuntimeEvent;
const rich_text_1 = require("../../rich-text");
const activity_utils_1 = require("./activity-utils");
function buildActivityRuns(events = [], snapshot, approvals) {
    const unique = [];
    const seen = new Set();
    events.forEach((event, index) => {
        const key = (0, activity_utils_1.eventStableKey)(event, index);
        if (seen.has(key))
            return;
        seen.add(key);
        unique.push(event);
    });
    const groups = new Map();
    unique.forEach((event, index) => {
        if (!isActivityRuntimeEvent(event))
            return;
        const id = (0, activity_utils_1.eventActivityId)(event, index);
        const bucket = groups.get(id) || [];
        bucket.push(event);
        groups.set(id, bucket);
    });
    const items = Array.from(groups.entries())
        .map(([id, group]) => buildActivityItem(id, group))
        .filter((item) => Boolean(item))
        .sort((left, right) => (left.startedAt || left.timestamp || 0) - (right.startedAt || right.timestamp || 0));
    appendPendingApprovals(items, snapshot, approvals);
    appendPendingArtifacts(items, snapshot);
    return items;
}
function buildActivitySummary(items = []) {
    const eventCount = items.reduce((total, item) => total + item.eventCount, 0);
    const toolCount = items.reduce((total, item) => total + item.toolCount, 0);
    const approvalCount = items.reduce((total, item) => total + item.approvalCount, 0);
    const errorCount = items.reduce((total, item) => total + item.errorCount, 0);
    const startedAt = (0, activity_utils_1.firstNumber)(...items.map((item) => item.startedAt || item.timestamp));
    const endedCandidates = items.map((item) => item.endedAt).filter((value) => typeof value === "number");
    const endedAt = endedCandidates.length ? Math.max(...endedCandidates) : undefined;
    const running = items.some((item) => item.status === "running" || item.status === "pending");
    const status = errorCount ? "error" : running ? "running" : items.length ? "success" : "pending";
    const end = running ? Date.now() / 1000 : endedAt;
    return {
        status,
        eventCount,
        activityCount: items.length,
        toolCount,
        approvalCount,
        errorCount,
        startedAt,
        endedAt,
        durationLabel: startedAt && end ? (0, activity_utils_1.formatDurationMs)(Math.max(0, (end - startedAt) * 1000)) : ""
    };
}
function isActivityRuntimeEvent(event) {
    return (event.type.startsWith("reasoning_") ||
        event.type.startsWith("planner_") ||
        event.type.startsWith("tool_") ||
        event.type.startsWith("subagent_") ||
        event.type.startsWith("sandbox_") ||
        event.type.startsWith("checkpoint_") ||
        event.type.startsWith("session_safe_rewind") ||
        event.type.startsWith("queue_") ||
        event.type.startsWith("learning_") ||
        event.type === "approval_result" ||
        event.type === "before_provider_request" ||
        event.type === "provider_response" ||
        event.type === "provider_error" ||
        event.type === "cancel_requested" ||
        event.type === "compaction" ||
        event.type === "error");
}
function buildActivityItem(id, events) {
    if (events.length === 0)
        return null;
    const sorted = [...events].sort((left, right) => (left.timestamp || 0) - (right.timestamp || 0));
    const first = sorted[0];
    const last = sorted[sorted.length - 1];
    const phase = (0, activity_utils_1.eventPhase)(first);
    const statuses = sorted.map(activity_utils_1.eventStatus);
    const lastStatus = statuses[statuses.length - 1] || "success";
    const status = statuses.includes("error")
        ? "error"
        : statuses.includes("cancelled")
            ? "cancelled"
            : lastStatus === "success" || lastStatus === "warning"
                ? lastStatus
                : statuses.includes("running")
                    ? "running"
                    : statuses.includes("pending")
                        ? "pending"
                        : "success";
    const startedAt = (0, activity_utils_1.eventStartedAt)(first) || first.timestamp;
    const endedAt = status === "running" || status === "pending" ? undefined : (0, activity_utils_1.eventEndedAt)(last) || last.timestamp;
    const endForDuration = endedAt || Date.now() / 1000;
    const durationLabel = startedAt && endForDuration ? (0, activity_utils_1.formatDurationMs)(Math.max(0, (endForDuration - startedAt) * 1000)) : "";
    const entries = sorted.map((event, index) => buildStep(event, index, startedAt));
    const detail = entries.map((entry) => [entry.label, entry.detail].filter(Boolean).join("\n")).filter(Boolean).join("\n\n");
    const toolCount = phase === "tool" ? 1 : entries.filter((entry) => entry.kind === "tool" || entry.kind === "command").length;
    const approvalCount = phase === "approval" ? 1 : entries.filter((entry) => entry.kind === "approval").length;
    const errorCount = entries.filter((entry) => entry.status === "error").length;
    const attachments = entries.flatMap((entry) => entry.attachments || []);
    return {
        id,
        runId: first.run_id || stringDetail(first, "run_id"),
        activityId: first.activity_id || stringDetail(first, "activity_id") || id,
        parentActivityId: first.parent_activity_id || stringDetail(first, "parent_activity_id"),
        phase,
        status,
        tone: status,
        title: activityTitle(phase, status, first, last, durationLabel),
        summary: activitySummary(phase, sorted, entries),
        detail,
        timestamp: startedAt || first.timestamp,
        startedAt,
        endedAt,
        durationMs: typeof last.duration_ms === "number" ? last.duration_ms : undefined,
        durationLabel,
        running: status === "running" || status === "pending",
        entries,
        attachments,
        eventCount: sorted.length,
        toolCount,
        approvalCount,
        errorCount
    };
}
function buildStep(event, index, fallbackStartedAt) {
    const status = (0, activity_utils_1.eventStatus)(event);
    const terminal = status === "success" || status === "error" || status === "cancelled";
    const startedAt = (terminal ? fallbackStartedAt : undefined) || (0, activity_utils_1.eventStartedAt)(event) || event.timestamp;
    const endedAt = (0, activity_utils_1.eventEndedAt)(event);
    const terminalEndedAt = endedAt || (terminal ? event.timestamp : undefined);
    const durationMs = typeof event.duration_ms === "number" ? event.duration_ms : startedAt && terminalEndedAt ? Math.max(0, (terminalEndedAt - startedAt) * 1000) : 0;
    const durationLabel = durationMs ? (0, activity_utils_1.formatDurationMs)(durationMs) : "";
    const kind = stepKind(event);
    return {
        id: (0, activity_utils_1.eventStableKey)(event, index),
        kind,
        label: stepLabel(event),
        detail: stepDetail(event),
        timestamp: event.timestamp,
        startedAt,
        endedAt: terminalEndedAt,
        durationLabel,
        status,
        tone: status,
        attachments: toolResultAttachments(event.details || {}),
        rawType: event.type,
        safeRaw: (0, activity_utils_1.safeRawEvent)(event)
    };
}
function stepKind(event) {
    if (event.type.startsWith("reasoning_") || event.type === "before_provider_request" || event.type === "provider_response" || event.type === "provider_error")
        return "progress";
    if (event.type.startsWith("planner_"))
        return "planner";
    if (event.type.startsWith("subagent_"))
        return "subagent";
    if (event.type.startsWith("sandbox_"))
        return "tool";
    if (event.type.startsWith("checkpoint_") || event.type.startsWith("session_safe_rewind"))
        return "checkpoint";
    if (event.type === "approval_result" || event.type.includes("approval"))
        return "approval";
    if (event.type.startsWith("tool_")) {
        const command = event.details?.command ?? event.tool_args?.command;
        return event.tool_name === "run_shell" || typeof command === "string" ? "command" : "tool";
    }
    if (event.type === "compaction" || event.type.startsWith("learning_"))
        return "memory";
    if (event.type.startsWith("queue_"))
        return "system";
    return "event";
}
function stepLabel(event) {
    if (event.plan_step?.title)
        return event.plan_step.title;
    if (event.tool_name)
        return event.tool_name;
    const specName = event.details?.spec_name;
    if (typeof specName === "string" && specName.trim())
        return specName;
    if (event.type === "before_provider_request")
        return "Preparing model request";
    if (event.type === "provider_response")
        return "Response received";
    if (event.type === "reasoning_start")
        return "Preparing context";
    if (event.type === "reasoning_delta")
        return "Progress update";
    if (event.type === "reasoning_summary")
        return "Public summary";
    if (event.type === "reasoning_end")
        return "Ready to respond";
    return event.type.replace(/_/g, " ");
}
function stepDetail(event) {
    const details = event.details || {};
    const lines = [];
    const summaryItems = listStrings(details.summary);
    summaryItems.slice(0, 6).forEach((item) => lines.push(`- ${item}`));
    const summary = (0, activity_utils_1.firstString)(details.summary, details.preview);
    if (summary && summaryItems.length === 0)
        lines.push((0, activity_utils_1.truncateText)(summary, 600));
    if (event.message && event.message.trim() && event.message !== summary)
        lines.push(truncateMultiline(event.message.trim(), 1200));
    if (event.delta && event.type.startsWith("reasoning_"))
        lines.push((0, activity_utils_1.truncateText)(event.delta, 360));
    if (event.plan_step?.tool_name)
        lines.push(`Tool: ${event.plan_step.tool_name}`);
    if (event.plan_step?.status)
        lines.push(`Step status: ${event.plan_step.status}`);
    const command = (0, activity_utils_1.firstString)(details.command, event.tool_args?.command);
    if (command)
        lines.push(`Command: ${truncateMultiline(command, 1200)}`);
    const path = (0, activity_utils_1.firstString)(details.path, details.absolute_path, details.target_path);
    if (path)
        lines.push(`Path: ${path}`);
    const changed = listStrings(details.changed_paths || details.affected_paths);
    if (changed.length)
        lines.push(`Changed: ${changed.slice(0, 8).join(", ")}`);
    const returncode = details.returncode ?? details.exit_code;
    if (typeof returncode === "number")
        lines.push(`Exit: ${returncode}`);
    const token = (0, activity_utils_1.firstString)(details.token, details.approval_token, details.artifact_token);
    if (token)
        lines.push(`Token: ${token.slice(0, 24)}`);
    const child = (0, activity_utils_1.firstString)(details.child_session_id, details.session_id);
    if (event.type.startsWith("subagent_") && child)
        lines.push(`Child session: ${child.slice(0, 12)}`);
    const eventStatusValue = (0, activity_utils_1.eventStatus)(event);
    if (!lines.length)
        lines.push(`${(0, activity_utils_1.statusLabel)(eventStatusValue)} · ${event.type.replace(/_/g, " ")}`);
    return lines.join("\n");
}
function activityTitle(phase, status, first, last, durationLabel) {
    const subject = first.tool_name || first.plan_step?.title || stringDetail(first, "spec_name") || (0, activity_utils_1.phaseLabel)(phase);
    const suffix = durationLabel ? ` · ${durationLabel}` : "";
    if (phase === "preparing")
        return `${status === "running" ? "Preparing context" : "Context prepared"}${suffix}`;
    if (phase === "analyzing")
        return `${status === "running" ? "Analyzing request" : "Analysis summary"}${suffix}`;
    if (phase === "finalizing")
        return `${status === "running" ? "Finalizing response" : "Response finalized"}${suffix}`;
    if (phase === "planning")
        return `${status === "running" ? "Planning" : "Plan ready"}${suffix}`;
    if (phase === "tool")
        return `${(0, activity_utils_1.statusLabel)(status)} · ${subject}${suffix}`;
    if (phase === "approval")
        return `${status === "pending" ? "Waiting for approval" : "Approval updated"}${suffix}`;
    if (phase === "subagent")
        return `${(0, activity_utils_1.statusLabel)(status)} · ${subject}${suffix}`;
    if (phase === "checkpoint")
        return `${(0, activity_utils_1.statusLabel)(status)} · Checkpoint${suffix}`;
    return `${(0, activity_utils_1.statusLabel)(status)} · ${(0, activity_utils_1.phaseLabel)(phase)}${last.type ? ` · ${last.type.replace(/_/g, " ")}` : ""}${suffix}`;
}
function activitySummary(phase, events, entries) {
    if (phase === "tool") {
        const tool = events.find((event) => event.tool_name)?.tool_name || "tool";
        const terminal = [...events].reverse().find((event) => event.type === "tool_end" || event.type === "tool_result" || event.type === "tool_error");
        const output = terminal?.message ? (0, activity_utils_1.truncateText)(terminal.message, 140) : "";
        return output ? `${tool}: ${output}` : `${tool} ${entries.some((entry) => entry.status === "running") ? "is running" : "completed"}`;
    }
    if (phase === "preparing" || phase === "analyzing" || phase === "finalizing") {
        const summary = [...events].reverse().map((event) => (0, activity_utils_1.firstString)(event.details?.summary, event.message)).find(Boolean);
        return summary || "Public progress from the agent runtime.";
    }
    const summary = [...events].reverse().map((event) => (0, activity_utils_1.firstString)(event.details?.summary, event.message, event.details?.preview)).find(Boolean);
    if (summary)
        return (0, activity_utils_1.truncateText)(summary, 180);
    return `${entries.length} event${entries.length === 1 ? "" : "s"}`;
}
function appendPendingApprovals(items, snapshot, approvals) {
    const token = snapshot?.pending_plan_token;
    if (!token)
        return;
    const exists = items.some((item) => item.phase === "approval" && item.detail.includes(token.slice(0, 12)));
    if (exists)
        return;
    const pending = (approvals?.active_items || approvals?.items || []).find((item) => item.token === token);
    const now = Date.now() / 1000;
    items.push({
        id: `pending-approval:${token}`,
        phase: "approval",
        status: "pending",
        tone: "pending",
        title: "Waiting for approval",
        summary: pending?.action_type ? `${pending.action_type} requires approval` : "Planner gate requires approval",
        detail: `Token: ${token}`,
        timestamp: typeof pending?.created_at === "number" ? pending.created_at : now,
        startedAt: typeof pending?.created_at === "number" ? pending.created_at : now,
        running: true,
        entries: [],
        eventCount: 0,
        toolCount: 0,
        approvalCount: 1,
        errorCount: 0
    });
}
function appendPendingArtifacts(items, snapshot) {
    for (const artifact of snapshot?.pending_artifacts || []) {
        const token = artifact.token;
        if (!token || items.some((item) => item.detail.includes(token.slice(0, 12))))
            continue;
        const changed = Array.isArray(artifact.changed_paths) ? artifact.changed_paths.join(", ") : "";
        items.push({
            id: `pending-artifact:${token}`,
            phase: "artifact",
            status: "pending",
            tone: "pending",
            title: "Patch artifact pending",
            summary: changed || artifact.workflow || "Pending patch artifact",
            detail: [`Token: ${token}`, changed ? `Changed: ${changed}` : ""].filter(Boolean).join("\n"),
            timestamp: Date.now() / 1000,
            startedAt: Date.now() / 1000,
            running: true,
            entries: [],
            eventCount: 0,
            toolCount: 0,
            approvalCount: 0,
            errorCount: 0
        });
    }
}
function toolResultAttachments(details) {
    const attachments = [];
    const seen = new Set();
    const push = (item, rawUrl) => {
        if (typeof rawUrl !== "string")
            return;
        const url = (0, rich_text_1.sanitizeMediaUrl)(rawUrl, { allowRelative: false });
        if (!url || seen.has(url) || looksDecorative(url, (0, activity_utils_1.firstString)(item.title, item.alt)))
            return;
        seen.add(url);
        attachments.push({ url, title: (0, activity_utils_1.firstString)(item.title), alt: (0, activity_utils_1.firstString)(item.alt, item.title), name: (0, activity_utils_1.firstString)(item.url) });
    };
    for (const result of Array.isArray(details.results) ? details.results : []) {
        if (!result || typeof result !== "object")
            continue;
        const item = result;
        push(item, item.image_url || item.image || item.thumbnail || item.thumbnail_url);
        if (attachments.length >= 3)
            break;
    }
    for (const image of Array.isArray(details.images) ? details.images : []) {
        if (!image || typeof image !== "object")
            continue;
        const item = image;
        push(item, item.url || item.src || item.image_url);
        if (attachments.length >= 3)
            break;
    }
    return attachments;
}
function looksDecorative(url, label) {
    const value = `${url} ${label}`.toLowerCase();
    return ["logo", "favicon", "icon", "sprite", "placeholder", "blank", "loading", "avatar", "qrcode", "qr-code"].some((word) => value.includes(word));
}
function stringDetail(event, key) {
    const details = event.details || {};
    const activity = details.activity && typeof details.activity === "object" ? details.activity : {};
    return (0, activity_utils_1.firstString)(event[key], details[key], activity[key]);
}
function listStrings(value) {
    return Array.isArray(value) ? value.filter((item) => typeof item === "string" && item.trim().length > 0) : [];
}
function truncateMultiline(value, limit) {
    const clean = value.trim();
    return clean.length <= limit ? clean : `${clean.slice(0, Math.max(0, limit - 1))}...`;
}
