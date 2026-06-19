import type { ResourceItem, ResourceKind, ResourceSnapshot, ResourceStatus } from "./resource-types";

export const resourceKinds: Array<{ id: ResourceKind; label: string; description: string }> = [
  { id: "tools", label: "Tools", description: "Built-in capabilities and tool policy." },
  { id: "mcp", label: "MCP Servers", description: "External model-context servers." },
  { id: "skills", label: "Skills", description: "Agent instructions and reusable workflows." },
  { id: "plugins", label: "Plugins", description: "Installed extensions and bundled capabilities." },
  { id: "bots", label: "Bots", description: "QQBot and external message entry points." },
  { id: "workspaces", label: "Workspaces", description: "Current project and git status." },
  { id: "attachments", label: "Attachments", description: "Uploaded files and extracted context." },
  { id: "memory", label: "Memory", description: "File memory, search index, and learned context." },
  { id: "artifacts", label: "Artifacts", description: "Pending outputs and checkpoints." }
];

export function buildResourceItems(snapshot: ResourceSnapshot): ResourceItem[] {
  return [
    ...toolItems(snapshot),
    ...mcpItems(snapshot),
    ...skillItems(snapshot),
    ...pluginItems(snapshot),
    ...botItems(snapshot),
    ...workspaceItems(snapshot),
    ...attachmentItems(snapshot),
    ...memoryItems(snapshot),
    ...artifactItems()
  ];
}

function toolItems(snapshot: ResourceSnapshot): ResourceItem[] {
  const settings: Record<string, unknown> = snapshot.inventory?.settings || {};
  const builtin = settings.mcp || {};
  return [{
    id: "tools:builtin",
    kind: "tools",
    name: "Built-in tools",
    subtitle: "Runtime tool registry",
    status: "healthy",
    statusText: "Available",
    description: "Core pp-Echo tools exposed through the existing ToolRegistry.",
    metrics: [
      { label: "MCP enabled", value: String(Boolean(snapshot.inventory?.mcp?.enabled)) },
      { label: "Config groups", value: Object.keys(settings).length }
    ],
    raw: { settings: builtin }
  }];
}

function mcpItems(snapshot: ResourceSnapshot): ResourceItem[] {
  const mcp = snapshot.inventory?.mcp;
  if (!mcp) return [];
  const servers = Array.isArray(mcp.servers) ? mcp.servers : [];
  const items = servers.map((server, index): ResourceItem => {
    const name = stringValue(server.name) || `server-${index + 1}`;
    const enabled = server.enabled !== false;
    const errors = Array.isArray(server.errors) ? server.errors.length : 0;
    return {
      id: `mcp:${name}`,
      kind: "mcp",
      name,
      subtitle: stringValue(server.transport) || "MCP server",
      status: errors ? "error" : enabled ? "healthy" : "disabled",
      statusText: errors ? `${errors} error${errors === 1 ? "" : "s"}` : enabled ? "Enabled" : "Disabled",
      description: stringValue(server.description, server.command, server.url),
      metrics: [
        { label: "Protocol", value: stringValue(server.protocol) || "auto" },
        { label: "Transport", value: stringValue(server.transport) || "auto" }
      ],
      raw: server
    };
  });
  if (!items.length) {
    items.push({
      id: "mcp:empty",
      kind: "mcp",
      name: "No MCP servers",
      subtitle: "Configure an MCP server to extend the runtime.",
      status: mcp.enabled ? "warning" : "disabled",
      statusText: mcp.enabled ? "Empty" : "Disabled",
      raw: mcp as unknown as Record<string, unknown>
    });
  }
  return items;
}

function skillItems(snapshot: ResourceSnapshot): ResourceItem[] {
  return collectionItems("skills", snapshot.inventory?.skills?.items || [], "Skill");
}

function pluginItems(snapshot: ResourceSnapshot): ResourceItem[] {
  return collectionItems("plugins", snapshot.inventory?.plugins?.items || [], "Plugin");
}

function botItems(snapshot: ResourceSnapshot): ResourceItem[] {
  return (snapshot.bots || []).map((bot): ResourceItem => ({
    id: `bots:${bot.id}`,
    kind: "bots",
    name: bot.name,
    subtitle: `${bot.platform} / ${bot.type}`,
    status: botStatus(bot),
    statusText: bot.status_text || bot.bot_state || bot.agent_state || "Unknown",
    description: "External gateway that can safely trigger local pp-Echo runs.",
    metrics: [
      { label: "Agent", value: bot.agent_state || bot.bot_state || "unknown" },
      { label: "Ingress", value: bot.ingress_state || "unknown" },
      { label: "QQ", value: bot.qq_state || (bot.configured ? "configured" : "not configured") }
    ],
    actions: [
      { label: "Open Bot Center", tone: "primary" },
      { label: bot.enabled ? "Stop" : "Start", tone: bot.enabled ? "danger" : "neutral" }
    ],
    raw: bot as unknown as Record<string, unknown>
  }));
}

function workspaceItems(snapshot: ResourceSnapshot): ResourceItem[] {
  const workspace = snapshot.workspace;
  if (!workspace) return [];
  return [{
    id: "workspaces:active",
    kind: "workspaces",
    name: workspace.name || "Active workspace",
    subtitle: workspace.path || "No path",
    status: workspace.path ? "healthy" : "warning",
    statusText: workspace.git_branch ? `Git ${workspace.git_branch}` : "Active",
    metrics: [
      { label: "Branch", value: workspace.git_branch || "unknown" },
      { label: "Path", value: workspace.path || "not set" }
    ],
    raw: workspace as unknown as Record<string, unknown>
  }];
}

function attachmentItems(snapshot: ResourceSnapshot): ResourceItem[] {
  return (snapshot.attachments || []).map((attachment): ResourceItem => ({
    id: `attachments:${attachment.attachment_id}`,
    kind: "attachments",
    name: attachment.original_filename,
    subtitle: `${attachment.kind} / ${formatBytes(attachment.size_bytes)}`,
    status: attachment.status === "error" ? "error" : attachment.status === "ready" ? "healthy" : "warning",
    statusText: attachment.status,
    description: attachment.text_preview || attachment.content_type || "",
    metrics: [
      { label: "Size", value: formatBytes(attachment.size_bytes) },
      { label: "Hash", value: attachment.sha256.slice(0, 10) }
    ],
    raw: attachment as unknown as Record<string, unknown>
  }));
}

function memoryItems(snapshot: ResourceSnapshot): ResourceItem[] {
  const memory = snapshot.memory;
  if (!memory) return [];
  return [{
    id: "memory:file",
    kind: "memory",
    name: "File memory",
    subtitle: memory.memory_root || "Memory store",
    status: memory.enabled ? "healthy" : "disabled",
    statusText: memory.enabled ? "Enabled" : "Disabled",
    metrics: [
      { label: "Files", value: memory.file_count },
      { label: "Indexed", value: memory.indexed_file_count },
      { label: "Search", value: String(memory.search_enabled) }
    ],
    raw: memory as unknown as Record<string, unknown>
  }];
}

function artifactItems(): ResourceItem[] {
  return [{
    id: "artifacts:runtime",
    kind: "artifacts",
    name: "Artifacts and checkpoints",
    subtitle: "Runtime-controlled outputs",
    status: "unknown",
    statusText: "Session scoped",
    description: "Open the Activity inspector to review pending artifacts, checkpoint activity, and restore events."
  }];
}

function collectionItems(kind: "skills" | "plugins", items: Array<Record<string, unknown>>, fallback: string): ResourceItem[] {
  return items.map((item, index): ResourceItem => {
    const name = stringValue(item.name, item.id) || `${fallback} ${index + 1}`;
    const enabled = item.enabled !== false;
    return {
      id: `${kind}:${name}`,
      kind,
      name,
      subtitle: stringValue(item.description, item.path) || fallback,
      status: enabled ? "healthy" : "disabled",
      statusText: enabled ? "Enabled" : "Disabled",
      description: stringValue(item.body, item.entrypoint, item.path),
      metrics: [
        { label: "Source", value: stringValue(item.source, item.root, item.path) || "workspace" }
      ],
      raw: item
    };
  });
}

function botStatus(bot: { process_state?: string; bot_state?: string; enabled?: boolean }): ResourceStatus {
  if (bot.process_state === "crashed" || bot.bot_state === "error") return "error";
  if (bot.bot_state === "running_agent" || bot.bot_state === "waiting_approval") return "warning";
  if (bot.process_state === "running") return "healthy";
  return bot.enabled ? "warning" : "disabled";
}

function stringValue(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number") return String(value);
  }
  return "";
}

function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
