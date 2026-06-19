import type { BotSummary, CapabilityInventory, AttachmentRecord, MemoryStatus, WorkspaceStatus } from "../../api";

export type ResourceKind = "tools" | "mcp" | "skills" | "plugins" | "bots" | "workspaces" | "attachments" | "memory" | "artifacts";
export type ResourceStatus = "healthy" | "warning" | "error" | "disabled" | "unknown";

export type ResourceItem = {
  id: string;
  kind: ResourceKind;
  name: string;
  subtitle: string;
  status: ResourceStatus;
  statusText: string;
  description?: string;
  metrics?: Array<{ label: string; value: string | number }>;
  actions?: Array<{ label: string; tone?: "primary" | "danger" | "neutral" }>;
  raw?: Record<string, unknown>;
};

export type ResourceSnapshot = {
  inventory?: CapabilityInventory | null;
  bots?: BotSummary[];
  memory?: MemoryStatus | null;
  attachments?: AttachmentRecord[];
  workspace?: WorkspaceStatus | null;
};
