import type { ApprovalsSummary, RuntimeEvent, SessionSnapshot } from "../../api";
import { sanitizeMediaUrl, type RichAttachment } from "../../rich-text";
import type { ActivityItem, ActivityRunSummary, ActivityStatus, ActivityStep } from "./activity-types";
import { eventActivityId, eventEndedAt, eventPhase, eventStableKey, eventStartedAt, eventStatus, firstNumber, firstString, formatDurationMs, phaseLabel, safeRawEvent, truncateText } from "./activity-utils";

export function buildActivityRuns(events: RuntimeEvent[] = [], snapshot?: SessionSnapshot, approvals?: ApprovalsSummary): ActivityItem[] {
  const unique: RuntimeEvent[] = [];
  const seen = new Set<string>();
  events.forEach((event, index) => {
    const key = eventStableKey(event, index);
    if (seen.has(key)) return;
    seen.add(key);
    unique.push(event);
  });

  const groups = new Map<string, RuntimeEvent[]>();
  unique.forEach((event, index) => {
    if (!isActivityRuntimeEvent(event)) return;
    const id = eventActivityId(event, index);
    const bucket = groups.get(id) || [];
    bucket.push(event);
    groups.set(id, bucket);
  });

  const items = Array.from(groups.entries())
    .map(([id, group]) => buildActivityItem(id, group))
    .filter((item): item is ActivityItem => Boolean(item))
    .sort((left, right) => (left.startedAt || left.timestamp || 0) - (right.startedAt || right.timestamp || 0));

  appendPendingApprovals(items, snapshot, approvals);
  appendPendingArtifacts(items, snapshot);
  return items;
}

export function buildActivitySummary(items: ActivityItem[] = []): ActivityRunSummary {
  const eventCount = items.reduce((total, item) => total + item.eventCount, 0);
  const toolCount = items.reduce((total, item) => total + item.toolCount, 0);
  const approvalCount = items.reduce((total, item) => total + item.approvalCount, 0);
  const errorCount = items.reduce((total, item) => total + item.errorCount, 0);
  const startedAt = firstNumber(...items.map((item) => item.startedAt || item.timestamp));
  const endedCandidates = items.map((item) => item.endedAt).filter((value): value is number => typeof value === "number");
  const endedAt = endedCandidates.length ? Math.max(...endedCandidates) : undefined;
  const running = items.some((item) => item.status === "running" || item.status === "pending");
  const status: ActivityStatus = errorCount ? "error" : running ? "running" : items.length ? "success" : "pending";
  const end = running ? Date.now() / 1000 : endedAt;
  return { status, eventCount, activityCount: items.length, toolCount, approvalCount, errorCount, startedAt, endedAt, durationLabel: startedAt && end ? formatDurationMs(Math.max(0, (end - startedAt) * 1000)) : "" };
}

export function isActivityRuntimeEvent(event: RuntimeEvent) {
  return event.type.startsWith("reasoning_") || event.type.startsWith("planner_") || event.type.startsWith("tool_") || event.type.startsWith("subagent_") || event.type.startsWith("sandbox_") || event.type.startsWith("checkpoint_") || event.type.startsWith("session_safe_rewind") || event.type.startsWith("queue_") || event.type.startsWith("learning_") || event.type === "approval_result" || event.type === "before_provider_request" || event.type === "provider_response" || event.type === "provider_error" || event.type === "cancel_requested" || event.type === "compaction" || event.type === "error";
}

function buildActivityItem(id: string, events: RuntimeEvent[]): ActivityItem | null {
  if (events.length === 0) return null;
  const sorted = [...events].sort((left, right) => (left.timestamp || 0) - (right.timestamp || 0));
  const first = sorted[0];
  const last = sorted[sorted.length - 1];
  const phase = eventPhase(first);
  const statuses = sorted.map(eventStatus);
  const lastStatus = statuses[statuses.length - 1] || "success";
  const status: ActivityStatus = statuses.includes("error") ? "error" : statuses.includes("cancelled") ? "cancelled" : lastStatus === "success" || lastStatus === "warning" ? lastStatus : statuses.includes("running") ? "running" : statuses.includes("pending") ? "pending" : "success";
  const startedAt = eventStartedAt(first) || first.timestamp;
  const endedAt = status === "running" || status === "pending" ? undefined : eventEndedAt(last) || last.timestamp;
  const endForDuration = endedAt || Date.now() / 1000;
  const durationLabel = startedAt && endForDuration ? formatDurationMs(Math.max(0, (endForDuration - startedAt) * 1000)) : "";
  const entries = sorted.map((event, index) => buildStep(event, index, startedAt));
  const narrative = summarizeActivity(phase, sorted, entries);
  const detail = entries.map((entry) => entry.detail).filter(Boolean).join("\n\n");
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
    title: narrative.title,
    summary: narrative.summary,
    narrative: narrative.narrative,
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

function buildStep(event: RuntimeEvent, index: number, fallbackStartedAt?: number): ActivityStep {
  const status = eventStatus(event);
  const terminal = status === "success" || status === "error" || status === "cancelled";
  const startedAt = (terminal ? fallbackStartedAt : undefined) || eventStartedAt(event) || event.timestamp;
  const endedAt = eventEndedAt(event);
  const terminalEndedAt = endedAt || (terminal ? event.timestamp : undefined);
  const durationMs = typeof event.duration_ms === "number" ? event.duration_ms : startedAt && terminalEndedAt ? Math.max(0, (terminalEndedAt - startedAt) * 1000) : 0;
  const durationLabel = durationMs ? formatDurationMs(durationMs) : "";
  const kind = stepKind(event);
  const narrative = naturalStepNarrative(event);
  return { id: eventStableKey(event, index), kind, label: narrative.title, detail: narrative.detail, narrative: narrative.body, timestamp: event.timestamp, startedAt, endedAt: terminalEndedAt, durationLabel, status, tone: status, attachments: toolResultAttachments(event.details || {}), rawType: event.type, safeRaw: safeRawEvent(event) };
}

function stepKind(event: RuntimeEvent): ActivityStep["kind"] {
  if (event.type.startsWith("reasoning_") || event.type === "before_provider_request" || event.type === "provider_response" || event.type === "provider_error") return "progress";
  if (event.type.startsWith("planner_")) return "planner";
  if (event.type.startsWith("subagent_")) return "subagent";
  if (event.type.startsWith("sandbox_")) return "tool";
  if (event.type.startsWith("checkpoint_") || event.type.startsWith("session_safe_rewind")) return "checkpoint";
  if (event.type === "approval_result" || event.type.includes("approval")) return "approval";
  if (event.type.startsWith("tool_")) {
    const command = event.details?.command ?? event.tool_args?.command;
    return event.tool_name === "run_shell" || typeof command === "string" ? "command" : "tool";
  }
  if (event.type === "compaction" || event.type.startsWith("learning_")) return "memory";
  if (event.type.startsWith("queue_")) return "system";
  return "event";
}

function summarizeActivity(phase: ActivityItem["phase"], events: RuntimeEvent[], entries: ActivityStep[]) {
  const latest = [...events].reverse()[0];
  const title = narrativeHeadline(phase, latest);
  const body = [phaseNarrative(phase, events), entries.map((entry) => entry.narrative).filter((value): value is string => Boolean(value)).slice(0, 3).join(" ")].filter(Boolean).join(" ").trim();
  return { title, summary: truncateText(body || title, 180), narrative: body || title };
}

function narrativeHeadline(phase: ActivityItem["phase"], last: RuntimeEvent | undefined) {
  if (phase === "preparing" || phase === "analyzing" || phase === "finalizing") return "正在推进这一步";
  if (phase === "planning") return "已经形成下一步计划";
  if (phase === "tool") return naturalToolLabel(last);
  if (phase === "approval") return "等待你确认关键操作";
  if (phase === "artifact") return "正在整理变更结果";
  if (phase === "checkpoint") return "已经记录检查点";
  if (phase === "subagent") return "子任务正在运行";
  if (phase === "memory") return "正在整理记忆";
  if (phase === "queue") return "正在调整执行队列";
  return phaseLabel(phase);
}

function phaseNarrative(phase: ActivityItem["phase"], events: RuntimeEvent[]) {
  const latest = [...events].reverse()[0];
  if (phase === "tool") return toolNarrative(latest);
  if (phase === "approval") return approvalNarrative(latest);
  if (phase === "planning") return "我已经把接下来要做的事情排好了顺序。";
  if (phase === "preparing") return "我先整理上下文，确认现在能安全处理哪些内容。";
  if (phase === "analyzing") return "我在看任务本身和当前工作区，尽量把方向摸清楚。";
  if (phase === "finalizing") return "我在收尾，把结果整理成更容易理解的回答。";
  if (phase === "checkpoint") return "我保留了一个检查点，方便后续回退或继续。";
  if (phase === "artifact") return "我把变更产物整理好了，等你确认下一步。";
  if (phase === "subagent") return "我把部分工作交给了子任务处理。";
  if (phase === "memory") return "我在整理可复用的信息，避免下次重复判断。";
  if (phase === "queue") return "我在调整接下来的执行顺序。";
  return "我正在推进这个任务。";
}

function naturalStepNarrative(event: RuntimeEvent) {
  const details = event.details || {};
  const toolName = String(event.tool_name || "");
  const command = firstString(details.command, event.tool_args?.command);
  const path = firstString(details.path, details.absolute_path, details.target_path);
  if (event.is_error || event.type === "tool_error" || event.type.endsWith("_error")) {
    const text = command ? `这条命令出了问题：${command}` : firstString(event.message, "这一步出了问题。");
    return { title: "运行失败", detail: text, body: text };
  }
  if (event.type === "before_provider_request") return { title: "准备模型请求", detail: "我先整理上下文，再发出下一次模型请求。", body: "我先整理上下文，再发出下一次模型请求。" };
  if (event.type === "provider_response") return { title: "收到模型回应", detail: "模型已经返回结果，我正在把它纳入当前过程。", body: "模型已经返回结果，我正在把它纳入当前过程。" };
  if (event.type === "reasoning_start") return { title: "开始分析", detail: "我先判断这次任务该怎么推进。", body: "我先判断这次任务该怎么推进。" };
  if (event.type === "reasoning_delta") return { title: "继续分析", detail: truncateText(String(event.delta || "我在继续思考下一步。"), 220), body: truncateText(String(event.delta || "我在继续思考下一步。"), 220) };
  if (event.type === "reasoning_summary") return { title: "整理结论", detail: truncateText(firstString(details.summary, event.message, "我把当前想法整理了一下。"), 240), body: truncateText(firstString(details.summary, event.message, "我把当前想法整理了一下。"), 240) };
  if (event.type === "reasoning_end") return { title: "准备回复", detail: "我已经把分析收束到一个可执行的结论。", body: "我已经把分析收束到一个可执行的结论。" };
  if (event.type.startsWith("planner_")) {
    const steps = listStrings(details.summary || details.plan_steps).slice(0, 3);
    const text = steps.length ? `我把事情拆成了 ${steps.length} 步：${steps.join("，")}。` : "我已经列好了执行顺序。";
    return { title: "形成计划", detail: text, body: text };
  }
  if (event.type.startsWith("tool_")) {
    const output = truncateMultiline(firstString(event.message, details.result, details.output, details.stdout), 320);
    const resultSuffix = output ? `\n${output}` : "";
    if (toolName === "run_shell" || command) {
      const shellText = command ? `我在运行命令：${command}` : "我在运行一条命令。";
      const body = `${shellText}${resultSuffix}`.trim();
      return { title: "运行命令", detail: body, body };
    }
    if (/(read|cat|open|get_file|file_read)/i.test(toolName)) {
      const text = path ? `我在查看 ${shortPath(path)}。` : "我在查看一个文件。";
      const body = `${text}${resultSuffix}`.trim();
      return { title: "查看文件", detail: body, body };
    }
    if (/(list|ls|tree|glob)/i.test(toolName)) {
      const body = `我先看一下项目结构，确认文件分布。${resultSuffix}`.trim();
      return { title: "查看结构", detail: body, body };
    }
    if (/(search|grep|rg|find)/i.test(toolName)) {
      const body = `我在项目里搜索相关内容，尽量缩小范围。${resultSuffix}`.trim();
      return { title: "搜索内容", detail: body, body };
    }
    if (/(patch|apply_patch|edit|write|replace|create)/i.test(toolName)) {
      const text = path ? `我准备修改 ${shortPath(path)}。` : "我准备修改一些文件。";
      const body = `${text}${resultSuffix}`.trim();
      return { title: "修改文件", detail: body, body };
    }
    if (/web\.(news|search)/i.test(toolName)) {
      const body = `我在网页上找补充信息。${resultSuffix}`.trim();
      return { title: "搜索网页", detail: body, body };
    }
    if (/web\.(fetch|open)/i.test(toolName)) {
      const body = `我打开了一个网页内容。${resultSuffix}`.trim();
      return { title: "读取网页", detail: body, body };
    }
    const body = `我调用了 ${toolName || "一个工具"}。${resultSuffix}`.trim();
    return { title: "调用工具", detail: body, body };
  }
  if (event.type === "approval_result" || event.type.includes("approval")) {
    const approvalText = firstString(event.message, details.result, details.summary, "我已经处理了这次审批。");
    return { title: "审批结果", detail: truncateMultiline(approvalText, 320), body: truncateMultiline(approvalText, 320) };
  }
  if (event.type.startsWith("checkpoint_") || event.type.startsWith("session_safe_rewind")) return { title: "记录检查点", detail: "我保留了一个安全的中间状态。", body: "我保留了一个安全的中间状态。" };
  if (event.type.startsWith("subagent_")) {
    const child = firstString(details.child_session_id, details.session_id);
    return { title: "运行子任务", detail: child ? `我把部分工作交给子任务 ${child.slice(0, 12)}。` : "我把部分工作交给了子任务。", body: child ? `我把部分工作交给子任务 ${child.slice(0, 12)}。` : "我把部分工作交给了子任务。" };
  }
  if (event.type === "cancel_requested") return { title: "收到取消请求", detail: "当前任务准备停下来。", body: "当前任务准备停下来。" };
  if (event.is_error) return { title: "发生错误", detail: truncateText(firstString(event.message, "这一步出了问题。"), 220), body: truncateText(firstString(event.message, "这一步出了问题。"), 220) };
  return { title: event.type.replace(/_/g, " "), detail: truncateText(firstString(event.message, "我在继续推进这个任务。"), 220), body: truncateText(firstString(event.message, "我在继续推进这个任务。"), 220) };
}

function naturalToolLabel(event: RuntimeEvent | undefined) {
  const details = event?.details || {};
  const toolName = String(event?.tool_name || "");
  const command = firstString(details.command, event?.tool_args?.command);
  const path = firstString(details.path, details.absolute_path, details.target_path);
  const lowered = `${toolName} ${command || ""}`.toLowerCase();
  if (toolName === "run_shell" || command) {
    if (/\b(test|pytest|vitest|jest|npm test|pnpm test|yarn test)\b/.test(lowered)) return "运行测试";
    if (/\b(build|tsc|vite build|npm run build|pnpm build|yarn build)\b/.test(lowered)) return "运行构建";
    if (/\b(git status|git diff|git log)\b/.test(lowered)) return "检查工作区";
    return "运行命令";
  }
  if (/(read|cat|open|get_file|file_read)/i.test(toolName)) return path ? `查看 ${shortPath(path)}` : "查看文件";
  if (/(list|ls|tree|glob)/i.test(toolName)) return "查看项目结构";
  if (/(search|grep|rg|find)/i.test(toolName)) return "搜索项目内容";
  if (/(patch|apply_patch|edit|write|replace|create)/i.test(toolName)) return path ? `修改 ${shortPath(path)}` : "修改文件";
  if (/web\.(news|search)/i.test(toolName)) return "搜索网页";
  if (/web\.(fetch|open)/i.test(toolName)) return "读取网页";
  return toolName || "调用工具";
}

function shortPath(value: string) {
  const clean = value.replace(/\\/g, "/");
  const parts = clean.split("/").filter(Boolean);
  return parts.slice(-2).join("/") || value;
}

function approvalNarrative(event: RuntimeEvent) {
  const details = event.details || {};
  const actionType = firstString(details.action_type, event.tool_name);
  const command = firstString(details.command, event.tool_args?.command);
  const path = firstString(details.path, details.absolute_path, details.target_path);
  if (actionType === "run_shell" && command) return { title: "等待确认命令", detail: `我在等你确认这条命令：${command}`, body: `我在等你确认这条命令：${command}` };
  if ((actionType === "write_file" || actionType === "edit_file") && path) return { title: "等待确认修改", detail: `我已经准备好修改 ${shortPath(path)}，等你确认。`, body: `我已经准备好修改 ${shortPath(path)}，等你确认。` };
  if (actionType === "apply_patch_artifact") {
    const changed = listStrings(details.changed_paths);
    const text = changed.length ? `我准备应用这些变更：${changed.slice(0, 3).join("，")}。` : "我准备应用一组变更。";
    return { title: "等待确认变更", detail: text, body: text };
  }
  return { title: "等待确认", detail: "我在等你确认一个需要授权的动作。", body: "我在等你确认一个需要授权的动作。" };
}

function toolNarrative(event: RuntimeEvent | undefined) {
  const details = event?.details || {};
  const toolName = String(event?.tool_name || "");
  const command = firstString(details.command, event?.tool_args?.command);
  const path = firstString(details.path, details.absolute_path, details.target_path);
  if (toolName === "run_shell" || command) return command ? `我正在运行命令：${command}` : "我正在运行一条命令。";
  if (/(read|cat|open|get_file|file_read)/i.test(toolName)) return path ? `我正在查看 ${shortPath(path)}。` : "我正在查看一个文件。";
  if (/(list|ls|tree|glob)/i.test(toolName)) return "我正在查看项目结构。";
  if (/(search|grep|rg|find)/i.test(toolName)) return "我正在搜索相关内容。";
  if (/(patch|apply_patch|edit|write|replace|create)/i.test(toolName)) return path ? `我正在修改 ${shortPath(path)}。` : "我正在修改文件。";
  return `我正在调用 ${toolName || "一个工具"}。`;
}

function appendPendingApprovals(items: ActivityItem[], snapshot?: SessionSnapshot, approvals?: ApprovalsSummary) {
  const token = snapshot?.pending_plan_token;
  if (!token) return;
  const exists = items.some((item) => item.phase === "approval" && item.detail.includes(token.slice(0, 12)));
  if (exists) return;
  const pending = (approvals?.active_items || approvals?.items || []).find((item) => item.token === token);
  const now = Date.now() / 1000;
  items.push({ id: `pending-approval:${token}`, phase: "approval", status: "pending", tone: "pending", title: "等待你确认操作", summary: pending?.action_type ? `${pending.action_type} 需要审批` : "执行前需要审批", narrative: pending?.action_type ? `我已经准备好了 ${pending.action_type}，等你确认后继续。` : "我已经准备好了下一步动作，等你确认后继续。", detail: `审批标识: ${token}`, timestamp: typeof pending?.created_at === "number" ? pending.created_at : now, startedAt: typeof pending?.created_at === "number" ? pending.created_at : now, running: true, entries: [], eventCount: 0, toolCount: 0, approvalCount: 1, errorCount: 0 });
}

function appendPendingArtifacts(items: ActivityItem[], snapshot?: SessionSnapshot) {
  for (const artifact of snapshot?.pending_artifacts || []) {
    const token = artifact.token;
    if (!token || items.some((item) => item.detail.includes(token.slice(0, 12)))) continue;
    const changed = Array.isArray(artifact.changed_paths) ? artifact.changed_paths.join(", ") : "";
    items.push({ id: `pending-artifact:${token}`, phase: "artifact", status: "pending", tone: "pending", title: "等待处理变更", summary: changed || artifact.workflow || "变更产物等待处理", narrative: changed ? `我已经整理出这些变更：${changed}。` : "我已经整理好变更产物，等你确认下一步。", detail: [`审批标识: ${token}`, changed ? `变更: ${changed}` : ""].filter(Boolean).join("\n"), timestamp: Date.now() / 1000, startedAt: Date.now() / 1000, running: true, entries: [], eventCount: 0, toolCount: 0, approvalCount: 0, errorCount: 0 });
  }
}

function stringDetail(event: RuntimeEvent, key: string) {
  const details = event.details || {};
  const activity = details.activity && typeof details.activity === "object" ? (details.activity as Record<string, unknown>) : {};
  return firstString((event as unknown as Record<string, unknown>)[key], details[key], activity[key]);
}

function listStrings(value: unknown) {
  const raw = Array.isArray(value) ? value : typeof value === "string" ? [value] : [];
  return raw.map((item) => String(item || "").trim()).filter((item) => item.length > 0);
}

function toolResultAttachments(details: Record<string, unknown>): RichAttachment[] {
  const attachments: RichAttachment[] = [];
  const seen = new Set<string>();
  const push = (item: Record<string, unknown>, rawUrl: unknown) => {
    if (typeof rawUrl !== "string") return;
    const url = sanitizeMediaUrl(rawUrl, { allowRelative: false });
    if (!url || seen.has(url) || looksDecorative(url, firstString(item.title, item.alt))) return;
    seen.add(url);
    attachments.push({ url, title: firstString(item.title), alt: firstString(item.alt, item.title), name: firstString(item.url) });
  };
  for (const result of Array.isArray(details.results) ? details.results : []) {
    if (!result || typeof result !== "object") continue;
    const item = result as Record<string, unknown>;
    push(item, item.image_url || item.image || item.thumbnail || item.thumbnail_url);
    if (attachments.length >= 3) break;
  }
  for (const image of Array.isArray(details.images) ? details.images : []) {
    if (!image || typeof image !== "object") continue;
    const item = image as Record<string, unknown>;
    push(item, item.url || item.src || item.image_url);
    if (attachments.length >= 3) break;
  }
  return attachments;
}

function looksDecorative(url: string, label: string) {
  const value = `${url} ${label}`.toLowerCase();
  return ["logo", "favicon", "icon", "sprite", "placeholder", "blank", "loading", "avatar", "qrcode", "qr-code"].some((word) => value.includes(word));
}

function truncateMultiline(value: string, limit: number) {
  const clean = String(value || "").trim();
  return clean.length <= limit ? clean : `${clean.slice(0, limit - 1)}...`;
}
