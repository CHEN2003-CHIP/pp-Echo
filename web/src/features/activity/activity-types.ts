import type { RichAttachment } from "../../rich-text";
import type { ActivityDisplayItem } from "./activity-presenter";

export type ActivityPhase =
  | "preparing"
  | "analyzing"
  | "planning"
  | "tool"
  | "approval"
  | "artifact"
  | "checkpoint"
  | "subagent"
  | "message"
  | "finalizing"
  | "queue"
  | "memory"
  | "system"
  | "event";

export type ActivityStatus = "pending" | "running" | "success" | "warning" | "error" | "cancelled";

export type ActivityStep = {
  id: string;
  kind: "progress" | "tool" | "command" | "planner" | "subagent" | "checkpoint" | "approval" | "artifact" | "memory" | "system" | "message" | "event";
  label: string;
  detail: string;
  narrative?: string;
  timestamp?: number;
  startedAt?: number;
  endedAt?: number;
  durationLabel?: string;
  status: ActivityStatus;
  tone?: ActivityStatus;
  attachments?: RichAttachment[];
  rawType?: string;
  safeRaw?: string;
};

export type ActivityItem = {
  id: string;
  runId?: string;
  activityId?: string;
  parentActivityId?: string;
  phase: ActivityPhase;
  status: ActivityStatus;
  tone?: ActivityStatus;
  title: string;
  summary: string;
  narrative?: string;
  display?: ActivityDisplayItem;
  detail: string;
  timestamp?: number;
  startedAt?: number;
  endedAt?: number;
  durationMs?: number;
  durationLabel?: string;
  running?: boolean;
  entries: ActivityStep[];
  attachments?: RichAttachment[];
  eventCount: number;
  toolCount: number;
  approvalCount: number;
  errorCount: number;
};

export type ActivityRunSummary = {
  status: ActivityStatus;
  eventCount: number;
  activityCount: number;
  toolCount: number;
  approvalCount: number;
  errorCount: number;
  startedAt?: number;
  endedAt?: number;
  durationLabel?: string;
};
