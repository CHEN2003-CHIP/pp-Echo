import type { RuntimeEvent } from "../../api";

export type ActivityFinding = {
  id: string;
  title: string;
  summary: string;
  evidence?: string[];
  relatedEvents: RuntimeEvent[];
  status: "done" | "partial" | "error";
};

export function buildActivityFindings(events: RuntimeEvent[] = []): ActivityFinding[] {
  const haystack = events.map(eventSearchText).join("\n").toLowerCase();
  const findings: ActivityFinding[] = [];

  if (matchesAny(haystack, ["activitycard.tsx", "activity-normalizer.ts", "activity-utils.ts", "buildtranscript", "buildactivityruns"])) {
    findings.push({
      id: "finding:activity-display-chain",
      title: "已确认 activity 展示链路",
      summary: "聊天页中的运行流程不是直接展示 RuntimeEvent，而是经过 transcript 和 activity normalizer 整理后，再由 ActivityCard 渲染。",
      evidence: evidenceFor(events, ["ActivityCard.tsx", "activity-normalizer.ts", "activity-utils.ts", "buildTranscript", "buildActivityRuns"]),
      relatedEvents: events,
      status: "done",
    });
  }

  if (matchesAny(haystack, ["timeline", "hydratesession", "/api/sessions", "events", "snapshot"])) {
    findings.push({
      id: "finding:history-reasoning-restore",
      title: "已确认历史 reasoning 的恢复方向",
      summary: "历史 snapshot 只恢复 messages 时 activity 会缺失；需要从 timeline API 读取历史事件，再转换成 RuntimeEvent 交给现有 transcript 链路处理。",
      evidence: evidenceFor(events, ["timeline", "hydrateSession", "events", "snapshot", "/api/sessions"]),
      relatedEvents: events,
      status: "done",
    });
  }

  if (matchesAny(haystack, ["board", "openview", "observer", "canvas-body-board"])) {
    findings.push({
      id: "finding:board-entry",
      title: "已确认看板入口位置",
      summary: "看板是 Web 侧的独立 view，可以先隐藏导航入口和视图切换逻辑，不需要深删底层 observer 或 timeline 组件。",
      evidence: evidenceFor(events, ["board", "openView", "observer", "timeline"]),
      relatedEvents: events,
      status: "done",
    });
  }

  const commandText = haystack;
  if (matchesAny(commandText, ["npx tsc --noemit", "activity-normalizer.tests", "activity-presenter.tests", "activity-finding.tests", "transcript.tests"])) {
    const failed = events.some((event) => event.is_error || event.type.includes("error"));
    findings.push({
      id: failed ? "finding:verification-failed" : "finding:verification-passed",
      title: failed ? "验证发现问题" : "验证通过",
      summary: failed ? "测试或类型检查发现了需要修正的地方，我会根据错误信息继续调整。" : "类型检查或测试已经通过，本次展示层调整没有引入对应范围内的回归。",
      evidence: evidenceFor(events, ["npx tsc --noEmit", "activity-normalizer.tests", "activity-presenter.tests", "activity-finding.tests", "transcript.tests"]),
      relatedEvents: events,
      status: failed ? "error" : "done",
    });
  }

  return findings;
}

function eventSearchText(event: RuntimeEvent) {
  const details = event.details || {};
  const values = [
    event.type,
    event.tool_name,
    event.message,
    event.delta,
    details.path,
    details.absolute_path,
    details.target_path,
    details.command,
    details.query,
    details.pattern,
    details.summary,
  ];
  return values.map((value) => Array.isArray(value) ? value.join(" ") : String(value || "")).join(" ");
}

function matchesAny(value: string, needles: string[]) {
  return needles.some((needle) => value.includes(needle.toLowerCase()));
}

function evidenceFor(events: RuntimeEvent[], needles: string[]) {
  const evidence: string[] = [];
  for (const event of events) {
    const text = eventSearchText(event);
    const matched = needles.find((needle) => text.toLowerCase().includes(needle.toLowerCase()));
    if (!matched) continue;
    const label = eventLabel(event, matched);
    if (!evidence.includes(label)) evidence.push(label);
    if (evidence.length >= 5) break;
  }
  return evidence;
}

function eventLabel(event: RuntimeEvent, matched: string) {
  if (event.type.startsWith("tool_") && event.tool_name) return `${event.tool_name}: ${matched}`;
  if (event.type) return `${event.type}: ${matched}`;
  return matched;
}
