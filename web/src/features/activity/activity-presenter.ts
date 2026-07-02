import type { RuntimeEvent } from "../../api";
import type { ActivityItem, ActivityPhase, ActivityStatus, ActivityStep } from "./activity-types";
import { buildActivityFindings } from "./activity-findings";
import { firstString, phaseLabel, truncateText } from "./activity-utils";

export type ActivityDisplayKind =
  | "thinking"
  | "planning"
  | "reading"
  | "searching"
  | "editing"
  | "running"
  | "checking"
  | "waiting"
  | "found"
  | "done"
  | "error";

export type ActivityDisplayStatus = "running" | "done" | "waiting" | "error";

export type ActivityDisplayItem = {
  id: string;
  kind: ActivityDisplayKind;
  title: string;
  summary?: string;
  detail?: string;
  status: ActivityDisplayStatus;
  timestamp?: number;
  raw?: RuntimeEvent[];
};

export type PresentedActivity = {
  title: string;
  summary: string;
  narrative: string;
  detail: string;
  display?: ActivityDisplayItem;
};

export type PresentedStep = {
  title: string;
  detail: string;
  body: string;
  kind: ActivityDisplayKind;
};

export function presentActivityStep(event: RuntimeEvent): PresentedStep {
  const details = event.details || {};
  const toolName = String(event.tool_name || "");
  const command = firstString(details.command, event.tool_args?.command);
  const path = firstString(details.path, details.absolute_path, details.target_path, details.file_path);
  const query = firstString(details.query, details.pattern, details.search_query, details.q);

  if (event.is_error || event.type === "tool_error" || event.type.endsWith("_error")) {
    const text = command ? `这条命令执行时遇到问题：${command}` : firstString(event.message, "这一步执行时遇到问题。");
    return { title: "执行遇到问题", detail: text, body: text, kind: "error" };
  }

  if (event.type === "before_provider_request") return step("准备模型请求", "我先整理上下文，再发出下一次模型请求。", "thinking");
  if (event.type === "provider_response") return step("收到模型回应", "模型已经返回结果，我正在整理成最终回复。", "thinking");
  if (event.type === "reasoning_start") return step("开始分析", "我先判断这次任务该怎么推进。", "thinking");
  if (event.type === "reasoning_delta") return step("分析进展", publicReasoningText(event), "thinking");
  if (event.type === "reasoning_summary") return step("分析进展", publicSummaryText(event), "thinking");
  if (event.type === "reasoning_end") return step("准备回复", "我已经把分析收束到一个可执行的结论。", "done");

  if (event.type.startsWith("planner_")) {
    const steps = listStrings(details.summary || details.plan_steps).slice(0, 3);
    const text = steps.length ? `我把接下来的工作拆成了 ${steps.length} 步：${steps.join("，")}。` : "我已经列好接下来的执行顺序。";
    return { title: "形成执行计划", detail: text, body: text, kind: "planning" };
  }

  if (event.type.startsWith("tool_") || event.type.startsWith("sandbox_")) {
    return presentToolEvent(event, toolName, command, path, query);
  }

  if (event.type === "approval_result" || event.type.includes("approval")) {
    const text = approvalText(event);
    return { title: "处理审批结果", detail: text, body: text, kind: "waiting" };
  }

  if (event.type.startsWith("checkpoint_") || event.type.startsWith("session_safe_rewind")) {
    return step("记录检查点", "我保留了一个安全的中间状态，方便后续继续或回退。", "done");
  }

  if (event.type.startsWith("subagent_")) {
    const child = firstString(details.child_session_id, details.session_id);
    const text = child ? `我把部分工作交给子任务 ${child.slice(0, 12)} 处理。` : "我把部分工作交给了子任务处理。";
    return { title: "运行子任务", detail: text, body: text, kind: "running" };
  }

  if (event.type === "cancel_requested") return step("收到取消请求", "当前任务准备停下来。", "waiting");
  if (event.is_error) return step("发生错误", truncateText(firstString(event.message, "这一步出了问题。"), 220), "error");
  return step(event.type.replace(/_/g, " "), truncateText(firstString(event.message, "我在继续推进这个任务。"), 220), "thinking");
}

export function presentActivityRun(id: string, phase: ActivityPhase, status: ActivityStatus, events: RuntimeEvent[], entries: ActivityStep[]): PresentedActivity {
  const finding = buildActivityFindings(events)[0];
  if (finding) {
    const detail = [
      finding.evidence?.length ? `依据:\n${finding.evidence.map((item) => `- ${item}`).join("\n")}` : "",
      entries.length ? `过程细节:\n${entries.map(formatEntryDetail).join("\n\n")}` : "",
    ].filter(Boolean).join("\n\n");
    return {
      title: finding.title,
      summary: truncateText(finding.summary, 180),
      narrative: finding.summary,
      detail,
      display: {
        id: finding.id,
        kind: finding.status === "error" ? "error" : "found",
        title: finding.title,
        summary: finding.summary,
        detail,
        status: finding.status === "error" ? "error" : finding.status === "partial" ? "running" : "done",
        timestamp: firstTimestamp(events),
        raw: finding.relatedEvents,
      },
    };
  }

  const latest = [...events].reverse().find((event) => event.type !== "turn_end" && event.type !== "agent_end");
  const title = activityTitle(phase, latest);
  const lead = activityLead(phase, latest);
  const entryNarrative = entries.map((entry) => entry.narrative).filter((value): value is string => Boolean(value)).slice(0, 2).join(" ");
  const narrative = [lead, entryNarrative].filter(Boolean).join(" ").trim() || title;
  const detail = entries.map(formatEntryDetail).filter(Boolean).join("\n\n");
  return {
    title,
    summary: truncateText(narrative, 180),
    narrative,
    detail,
    display: {
      id,
      kind: displayKindForPhase(phase, latest),
      title,
      summary: narrative,
      detail,
      status: status === "error" || status === "cancelled" ? "error" : status === "running" || status === "pending" ? "running" : "done",
      timestamp: firstTimestamp(events),
      raw: events,
    },
  };
}

function presentToolEvent(event: RuntimeEvent, toolName: string, command: string, path: string, query: string): PresentedStep {
  const details = event.details || {};
  const output = truncateMultiline(firstString(event.message, details.summary, details.result, details.output, details.stdout), 320);
  const resultSuffix = output ? `\n${output}` : "";
  const lowerTool = toolName.toLowerCase();
  const lowerCommand = command.toLowerCase();

  if (toolName === "run_shell" || toolName.includes("shell_command") || command) {
    const purpose = shellPurpose(command);
    const text = command ? `${purpose}\n我在用命令结果确认当前修改是否可靠。` : "正在运行验证命令\n我在用命令结果确认当前判断是否可靠。";
    return { title: purpose, detail: `${text}${resultSuffix}`.trim(), body: `${text}${resultSuffix}`.trim(), kind: commandKind(lowerCommand) };
  }

  if (isReadTool(lowerTool)) {
    const target = path ? shortPath(path) : "相关文件";
    const text = path ? `正在查看 ${target}\n${filePurpose(path)}` : "正在查看相关文件\n我在确认这个文件与当前任务的关系。";
    return { title: `正在查看 ${target}`, detail: `${text}${resultSuffix}`.trim(), body: `${text}${resultSuffix}`.trim(), kind: "reading" };
  }

  if (isListTool(lowerTool)) {
    const target = path || firstString(details.cwd) || "项目";
    const text = `正在浏览 ${target} 的目录结构\n${directoryPurpose(target)}`;
    return { title: `正在浏览 ${target} 的目录结构`, detail: `${text}${resultSuffix}`.trim(), body: `${text}${resultSuffix}`.trim(), kind: "reading" };
  }

  if (isSearchTool(lowerTool)) {
    const target = query || command || firstString(details.pattern) || "相关内容";
    const text = `正在搜索 ${target}\n${searchPurpose(target)}`;
    return { title: `正在搜索 ${target}`, detail: `${text}${resultSuffix}`.trim(), body: `${text}${resultSuffix}`.trim(), kind: "searching" };
  }

  if (isWriteTool(lowerTool)) {
    const target = path ? shortPath(path) : "相关文件";
    const text = `正在更新 ${target}\n我在应用前端展示层调整，同时保留可展开的结构化细节。`;
    return { title: `正在更新 ${target}`, detail: `${text}${resultSuffix}`.trim(), body: `${text}${resultSuffix}`.trim(), kind: "editing" };
  }

  if (/web\.(news|search)|browser_search|web_search/i.test(toolName)) {
    const target = query || firstString(details.q) || "外部资料";
    const text = `正在查找 ${target}\n我在补充当前任务需要的外部资料。`;
    return { title: `正在查找 ${target}`, detail: `${text}${resultSuffix}`.trim(), body: `${text}${resultSuffix}`.trim(), kind: "searching" };
  }

  if (/web\.(fetch|open)|browser_open/i.test(toolName)) {
    const text = "正在读取网页内容\n我在确认外部资料里与当前任务相关的信息。";
    return { title: "正在读取网页内容", detail: `${text}${resultSuffix}`.trim(), body: `${text}${resultSuffix}`.trim(), kind: "reading" };
  }

  const body = `正在调用 ${toolName || "一个工具"}\n我在用工具结果推进当前任务。${resultSuffix}`.trim();
  return { title: toolName || "调用工具", detail: body, body, kind: "running" };
}

function activityTitle(phase: ActivityPhase, event: RuntimeEvent | undefined) {
  if (phase === "tool") return presentActivityStep(event || { type: "tool_start", session_id: "" }).title;
  if (phase === "preparing" || phase === "analyzing" || phase === "finalizing") return "分析进展";
  if (phase === "planning") return "形成执行计划";
  if (phase === "approval") return "等待你确认关键操作";
  if (phase === "artifact") return "整理变更结果";
  if (phase === "checkpoint") return "记录检查点";
  if (phase === "subagent") return "子任务正在运行";
  if (phase === "memory") return "整理记忆";
  if (phase === "queue") return "调整执行队列";
  return phaseLabel(phase);
}

function activityLead(phase: ActivityPhase, event: RuntimeEvent | undefined) {
  if (phase === "tool" && event) return presentActivityStep(event).body;
  if (phase === "planning") return "我已经把接下来要做的事情排好了顺序。";
  if (phase === "preparing") return "我先整理上下文，确认现在能安全处理哪些内容。";
  if (phase === "analyzing") return "我在根据当前上下文整理可执行方案。";
  if (phase === "finalizing") return "我在收尾，把结果整理成更容易理解的回答。";
  if (phase === "approval") return event ? approvalText(event) : "我在等你确认一个需要授权的动作。";
  if (phase === "checkpoint") return "我保留了一个检查点，方便后续继续或回退。";
  if (phase === "subagent") return "我把部分工作交给了子任务处理。";
  if (phase === "memory") return "我在整理可复用的信息，避免后续重复判断。";
  return "我正在推进当前任务。";
}

function publicReasoningText(event: RuntimeEvent) {
  const text = firstString(event.message, event.delta, event.details?.summary);
  return text ? truncateText(text, 220) : "我在继续分析当前问题。";
}

function publicSummaryText(event: RuntimeEvent) {
  const summary = event.details?.summary;
  const text = Array.isArray(summary) ? summary.join(" ") : firstString(summary, event.message);
  return text ? truncateText(text, 240) : "我把当前分析整理成了简短摘要。";
}

function approvalText(event: RuntimeEvent) {
  const details = event.details || {};
  const command = firstString(details.command, event.tool_args?.command);
  const path = firstString(details.path, details.absolute_path, details.target_path);
  if (command) return `等待确认运行命令\n这个操作会执行本地命令，所以需要你确认后再继续。`;
  if (path) return `等待确认修改 ${shortPath(path)}\n这个操作会更新文件，所以需要你确认后再继续。`;
  return truncateMultiline(firstString(event.message, details.result, details.summary, "我已经处理了这次审批。"), 320);
}

function displayKindForPhase(phase: ActivityPhase, event: RuntimeEvent | undefined): ActivityDisplayKind {
  if (phase === "planning") return "planning";
  if (phase === "approval") return "waiting";
  if (phase === "checkpoint" || phase === "artifact") return "done";
  if (phase === "tool" && event) return presentActivityStep(event).kind;
  return "thinking";
}

function commandKind(command: string): ActivityDisplayKind {
  if (/\b(test|pytest|vitest|jest|npm test|pnpm test|yarn test|tsc)\b/.test(command)) return "checking";
  return "running";
}

function shellPurpose(command: string) {
  const lower = command.toLowerCase();
  if (/\bnpx tsc\b|tsc --noemit/.test(lower)) return "正在运行 TypeScript 类型检查";
  if (/activity-normalizer\.tests/.test(lower)) return "正在运行 activity normalizer 测试";
  if (/activity-presenter\.tests/.test(lower)) return "正在运行 activity presenter 测试";
  if (/activity-finding\.tests/.test(lower)) return "正在运行 activity finding 测试";
  if (/transcript\.tests/.test(lower)) return "正在运行 transcript 测试";
  if (/\b(npm|pnpm|yarn)\s+test\b|vitest|jest|pytest/.test(lower)) return "正在运行测试";
  if (/\b(git status|git diff|git log)\b/.test(lower)) return "正在检查工作区状态";
  return command ? "正在运行命令" : "正在运行验证命令";
}

function filePurpose(path: string) {
  const normalized = path.replace(/\\/g, "/");
  const name = shortPath(path);
  if (/ActivityCard\.tsx$/.test(normalized)) return "我在确认 activity/reasoning 是如何渲染到聊天页面中的。";
  if (/activity-normalizer\.ts$/.test(normalized)) return "我在确认 runtime events 是如何被整理成 activity item 的。";
  if (/activity-presenter\.ts$/.test(normalized)) return "我在确认自然执行旁白是如何生成的。";
  if (/activity-findings\.ts$/.test(normalized)) return "我在确认阶段性发现是如何合并出来的。";
  if (/App\.tsx$/.test(normalized)) return "我在确认 Web 会话事件、导航入口和视图切换逻辑。";
  if (/transcript|buildTranscript/i.test(normalized)) return "我在确认历史消息和运行流程是如何合成聊天记录的。";
  if (/eval\.py$/.test(normalized)) return "我在了解当前评测脚本的入口、参数和执行流程。";
  return `我在确认 ${name} 与当前任务的关系。`;
}

function directoryPurpose(path: string) {
  const normalized = path.replace(/\\/g, "/");
  if (normalized === "." || normalized === "") return "我在快速确认前后端模块和测试脚本的分布。";
  if (normalized === "web/src") return "我在定位聊天页、导航和 activity 展示相关代码。";
  if (normalized.includes("web/src/features/activity")) return "我在确认 activity/reasoning 相关组件是如何组织的。";
  return "我在确认当前任务相关代码的位置。";
}

function searchPurpose(query: string) {
  if (/buildTranscript/i.test(query)) return "我在确认运行流程消息是在什么阶段生成的。";
  if (/reasoning_summary/i.test(query)) return "我在确认公开 reasoning summary 是如何进入 activity 展示链路的。";
  if (/openView\(\"board\"\)|board/i.test(query)) return "我在定位看板入口和视图切换逻辑。";
  if (/timeline/i.test(query)) return "我在确认历史运行事件是否已有可复用的数据源。";
  return "我在定位与当前任务相关的代码位置。";
}

function formatEntryDetail(entry: ActivityStep) {
  const meta = [entry.rawType ? `type: ${entry.rawType}` : "", entry.durationLabel ? `duration: ${entry.durationLabel}` : "", entry.status ? `status: ${entry.status}` : ""].filter(Boolean).join("\n");
  return [entry.label, entry.detail, meta].filter(Boolean).join("\n");
}

function step(title: string, text: string, kind: ActivityDisplayKind): PresentedStep {
  return { title, detail: text, body: text, kind };
}

function isReadTool(value: string) {
  return /(read|cat|open|get_file|file_read)/i.test(value);
}

function isListTool(value: string) {
  return /(list|ls|tree|glob|directory)/i.test(value);
}

function isSearchTool(value: string) {
  return /(search|grep|rg|find)/i.test(value);
}

function isWriteTool(value: string) {
  return /(patch|apply_patch|edit|write|replace|create)/i.test(value);
}

function shortPath(value: string) {
  const clean = value.replace(/\\/g, "/");
  const parts = clean.split("/").filter(Boolean);
  return parts.slice(-2).join("/") || value;
}

function firstTimestamp(events: RuntimeEvent[]) {
  return events.find((event) => typeof event.timestamp === "number")?.timestamp;
}

function listStrings(value: unknown) {
  const raw = Array.isArray(value) ? value : typeof value === "string" ? [value] : [];
  return raw.map((item) => String(item || "").trim()).filter((item) => item.length > 0);
}

function truncateMultiline(value: string, limit: number) {
  const clean = String(value || "").trim();
  return clean.length <= limit ? clean : `${clean.slice(0, Math.max(0, limit - 1))}...`;
}
