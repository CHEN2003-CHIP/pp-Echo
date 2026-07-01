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
        return naturalToolLabel(event);
    const specName = event.details?.spec_name;
    if (typeof specName === "string" && specName.trim())
        return specName;
    if (event.type === "before_provider_request")
        return "\u51c6\u5907\u6a21\u578b\u8bf7\u6c42";
    if (event.type === "provider_response")
        return "\u6536\u5230\u6a21\u578b\u54cd\u5e94";
    if (event.type === "reasoning_start")
        return "\u51c6\u5907\u4e0a\u4e0b\u6587";
    if (event.type === "reasoning_delta")
        return "\u66f4\u65b0\u8fdb\u5ea6";
    if (event.type === "reasoning_summary")
        return "\u6574\u7406\u516c\u5f00\u6458\u8981";
    if (event.type === "reasoning_end")
        return "\u51c6\u5907\u56de\u590d";
    if (event.type.startsWith("planner_"))
        return "\u89c4\u5212\u4efb\u52a1";
    if (event.type.startsWith("checkpoint_"))
        return "\u8bb0\u5f55\u68c0\u67e5\u70b9";
    if (event.type.startsWith("queue_"))
        return "\u66f4\u65b0\u8fd0\u884c\u961f\u5217";
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
        lines.push(`\u5de5\u5177: ${event.plan_step.tool_name}`);
    if (event.plan_step?.status)
        lines.push(`\u6b65\u9aa4\u72b6\u6001: ${event.plan_step.status}`);
    const command = (0, activity_utils_1.firstString)(details.command, event.tool_args?.command);
    if (command)
        lines.push(`\u547d\u4ee4: ${truncateMultiline(command, 1200)}`);
    const path = (0, activity_utils_1.firstString)(details.path, details.absolute_path, details.target_path);
    if (path)
        lines.push(`\u8def\u5f84: ${path}`);
    const changed = listStrings(details.changed_paths || details.affected_paths);
    if (changed.length)
        lines.push(`\u53d8\u66f4: ${changed.slice(0, 8).join(", ")}`);
    const returncode = details.returncode ?? details.exit_code;
    if (typeof returncode === "number")
        lines.push(`\u9000\u51fa\u7801: ${returncode}`);
    const token = (0, activity_utils_1.firstString)(details.token, details.approval_token, details.artifact_token);
    if (token)
        lines.push(`\u5ba1\u6279\u6807\u8bc6: ${token.slice(0, 24)}`);
    const child = (0, activity_utils_1.firstString)(details.child_session_id, details.session_id);
    if (event.type.startsWith("subagent_") && child)
        lines.push(`\u5b50\u4f1a\u8bdd: ${child.slice(0, 12)}`);
    const eventStatusValue = (0, activity_utils_1.eventStatus)(event);
    if (!lines.length)
        lines.push(`${naturalStatusLabel(eventStatusValue)} \u00b7 ${event.type.replace(/_/g, " ")}`);
    return lines.join("\n");
}
function activityTitle(phase, status, first, last, durationLabel) {
    const subject = first.tool_name ? naturalToolLabel(first) : first.plan_step?.title || stringDetail(first, "spec_name") || naturalPhaseLabel(phase);
    const suffix = durationLabel ? ` \u00b7 ${durationLabel}` : "";
    if (phase === "preparing")
        return `${status === "running" ? "\u6b63\u5728\u51c6\u5907\u4e0a\u4e0b\u6587" : "\u5df2\u51c6\u5907\u597d\u4e0a\u4e0b\u6587"}${suffix}`;
    if (phase === "analyzing")
        return `${status === "running" ? "\u6b63\u5728\u5206\u6790\u4efb\u52a1" : "\u5df2\u5b8c\u6210\u5206\u6790"}${suffix}`;
    if (phase === "finalizing")
        return `${status === "running" ? "\u6b63\u5728\u6574\u7406\u56de\u590d" : "\u5df2\u6574\u7406\u56de\u590d"}${suffix}`;
    if (phase === "planning")
        return `${status === "running" ? "\u6b63\u5728\u89c4\u5212\u6267\u884c\u6b65\u9aa4" : "\u5df2\u751f\u6210\u6267\u884c\u8ba1\u5212"}${suffix}`;
    if (phase === "tool")
        return `${naturalStatusPrefix(status)}${subject}${suffix}`;
    if (phase === "approval")
        return `${status === "pending" ? "\u7b49\u5f85\u4f60\u786e\u8ba4\u64cd\u4f5c" : "\u5ba1\u6279\u7ed3\u679c\u5df2\u8bb0\u5f55"}${suffix}`;
    if (phase === "subagent")
        return `${naturalStatusPrefix(status)}${subject}${suffix}`;
    if (phase === "checkpoint")
        return `${naturalStatusPrefix(status)}\u68c0\u67e5\u70b9${suffix}`;
    if (phase === "artifact")
        return `${status === "pending" ? "\u6709\u5f85\u5904\u7406\u7684\u53d8\u66f4" : "\u53d8\u66f4\u4ea7\u7269\u5df2\u66f4\u65b0"}${suffix}`;
    return `${naturalStatusPrefix(status)}${naturalPhaseLabel(phase)}${last.type ? ` \u00b7 ${last.type.replace(/_/g, " ")}` : ""}${suffix}`;
}
function activitySummary(phase, events, entries) {
    if (phase === "tool") {
        const toolEvent = events.find((event) => event.tool_name);
        const terminal = [...events].reverse().find((event) => event.type === "tool_end" || event.type === "tool_result" || event.type === "tool_error");
        const output = terminal?.message ? (0, activity_utils_1.truncateText)(terminal.message, 140) : "";
        const label = naturalToolLabel(toolEvent || { type: "tool", tool_name: "tool" });
        return output ? `${label}: ${output}` : `${label}${entries.some((entry) => entry.status === "running") ? "\u8fdb\u884c\u4e2d" : "\u5df2\u5b8c\u6210"}`;
    }
    if (phase === "preparing" || phase === "analyzing" || phase === "finalizing") {
        const summary = [...events].reverse().map((event) => (0, activity_utils_1.firstString)(event.details?.summary, event.message)).find(Boolean);
        return summary || "Agent \u6b63\u5728\u63a8\u8fdb\u5f53\u524d\u4efb\u52a1\u3002";
    }
    const summary = [...events].reverse().map((event) => (0, activity_utils_1.firstString)(event.details?.summary, event.message, event.details?.preview)).find(Boolean);
    if (summary)
        return (0, activity_utils_1.truncateText)(summary, 180);
    return `${entries.length} \u4e2a\u8fd0\u884c\u6b65\u9aa4`;
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
        title: "\u7b49\u5f85\u4f60\u786e\u8ba4\u64cd\u4f5c",
        summary: pending?.action_type ? `${pending.action_type} \u9700\u8981\u5ba1\u6279` : "\u6267\u884c\u524d\u9700\u8981\u5ba1\u6279",
        detail: `\u5ba1\u6279\u6807\u8bc6: ${token}`,
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
            title: "\u6709\u5f85\u5904\u7406\u7684\u53d8\u66f4",
            summary: changed || artifact.workflow || "\u53d8\u66f4\u4ea7\u7269\u7b49\u5f85\u5904\u7406",
            detail: [`\u5ba1\u6279\u6807\u8bc6: ${token}`, changed ? `\u53d8\u66f4: ${changed}` : ""].filter(Boolean).join("\n"),
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
function naturalToolLabel(event) {
    const toolName = String(event.tool_name || "");
    const details = event.details || {};
    const command = (0, activity_utils_1.firstString)(details.command, event.tool_args?.command);
    const path = (0, activity_utils_1.firstString)(details.path, details.absolute_path, details.target_path);
    const lowered = `${toolName} ${command || ""}`.toLowerCase();
    if (toolName === "run_shell" || command) {
        if (/\b(test|pytest|vitest|jest|npm test|pnpm test|yarn test)\b/.test(lowered))
            return "\u8fd0\u884c\u6d4b\u8bd5";
        if (/\b(build|tsc|vite build|npm run build|pnpm build|yarn build)\b/.test(lowered))
            return "\u8fd0\u884c\u6784\u5efa";
        if (/\b(git status|git diff|git log)\b/.test(lowered))
            return "\u68c0\u67e5\u5de5\u4f5c\u533a";
        return "\u8fd0\u884c\u547d\u4ee4";
    }
    if (/(read|cat|open|get_file|file_read)/i.test(toolName))
        return path ? `\u67e5\u770b ${shortPath(path)}` : "\u67e5\u770b\u6587\u4ef6";
    if (/(list|ls|tree|glob)/i.test(toolName))
        return "\u67e5\u770b\u9879\u76ee\u7ed3\u6784";
    if (/(search|grep|rg|find)/i.test(toolName))
        return "\u641c\u7d22\u9879\u76ee\u5185\u5bb9";
    if (/(patch|apply_patch|edit|write|replace|create)/i.test(toolName))
        return path ? `\u4fee\u6539 ${shortPath(path)}` : "\u4fee\u6539\u6587\u4ef6";
    if (/web\.(news|search)/i.test(toolName))
        return "\u641c\u7d22\u7f51\u9875";
    if (/web\.(fetch|open)/i.test(toolName))
        return "\u8bfb\u53d6\u7f51\u9875";
    return toolName || "\u8c03\u7528\u5de5\u5177";
}
function shortPath(value) {
    const clean = value.replace(/\\/g, "/");
    const parts = clean.split("/").filter(Boolean);
    return parts.slice(-2).join("/") || value;
}
function naturalStatusPrefix(status) {
    if (status === "running")
        return "\u6b63\u5728";
    if (status === "pending")
        return "\u7b49\u5f85";
    if (status === "success")
        return "\u5df2\u5b8c\u6210";
    if (status === "warning")
        return "\u9700\u8981\u68c0\u67e5";
    if (status === "error")
        return "\u6267\u884c\u5931\u8d25\uff1a";
    if (status === "cancelled")
        return "\u5df2\u53d6\u6d88";
    return "";
}
function naturalStatusLabel(status) {
    if (status === "running")
        return "\u8fdb\u884c\u4e2d";
    if (status === "pending")
        return "\u5f85\u786e\u8ba4";
    if (status === "success")
        return "\u5b8c\u6210";
    if (status === "warning")
        return "\u9700\u68c0\u67e5";
    if (status === "error")
        return "\u5931\u8d25";
    if (status === "cancelled")
        return "\u5df2\u53d6\u6d88";
    return status;
}
function naturalPhaseLabel(phase) {
    if (phase === "preparing")
        return "\u51c6\u5907\u4e0a\u4e0b\u6587";
    if (phase === "analyzing")
        return "\u5206\u6790\u4efb\u52a1";
    if (phase === "planning")
        return "\u89c4\u5212\u4efb\u52a1";
    if (phase === "tool")
        return "\u6267\u884c\u5de5\u5177";
    if (phase === "approval")
        return "\u7b49\u5f85\u5ba1\u6279";
    if (phase === "artifact")
        return "\u5904\u7406\u53d8\u66f4";
    if (phase === "checkpoint")
        return "\u8bb0\u5f55\u68c0\u67e5\u70b9";
    if (phase === "subagent")
        return "\u8fd0\u884c\u5b50\u4efb\u52a1";
    if (phase === "memory")
        return "\u6574\u7406\u8bb0\u5fc6";
    if (phase === "queue")
        return "\u66f4\u65b0\u961f\u5217";
    if (phase === "finalizing")
        return "\u6574\u7406\u56de\u590d";
    return (0, activity_utils_1.phaseLabel)(phase);
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
