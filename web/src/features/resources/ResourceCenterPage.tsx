import { useEffect, useMemo, useState } from "react";
import { Bot, Boxes, Database, FileText, FolderOpen, HardDrive, PlugZap, RefreshCw, Search, ShieldCheck, Sparkles, Wrench } from "lucide-react";
import { api, type AttachmentRecord, type BotSummary, type CapabilityInventory, type MemoryStatus, type WorkspaceStatus } from "../../api";
import { buildResourceItems, resourceKinds } from "./resource-catalog";
import type { ResourceItem, ResourceKind, ResourceStatus } from "./resource-types";

export function ResourceCenterPage({
  activeSessionId,
  workspaceStatus,
  attachments,
  onOpenBots,
  onOpenCapabilities,
  onOpenAttachments
}: {
  activeSessionId?: string;
  workspaceStatus?: WorkspaceStatus | null;
  attachments?: AttachmentRecord[];
  onOpenBots?: () => void;
  onOpenCapabilities?: (kind: ResourceKind) => void;
  onOpenAttachments?: () => void;
}) {
  const [inventory, setInventory] = useState<CapabilityInventory | null>(null);
  const [bots, setBots] = useState<BotSummary[]>([]);
  const [memory, setMemory] = useState<MemoryStatus | null>(null);
  const [kind, setKind] = useState<ResourceKind>("bots");
  const [selectedId, setSelectedId] = useState("");
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    refresh().catch((error) => setNotice(errorMessage(error)));
  }, []);

  async function refresh() {
    setLoading(true);
    setNotice("");
    try {
      const [nextInventory, nextBots, nextMemory] = await Promise.all([
        api.capabilityConfig().catch(() => null),
        api.bots().catch(() => ({ bots: [] })),
        api.memoryStatus().catch(() => null)
      ]);
      setInventory(nextInventory);
      setBots(nextBots?.bots || []);
      setMemory(nextMemory);
    } finally {
      setLoading(false);
    }
  }

  const items = useMemo(() => buildResourceItems({ inventory, bots, memory, attachments, workspace: workspaceStatus || null }), [inventory, bots, memory, attachments, workspaceStatus]);
  const filtered = useMemo(() => {
    const text = query.trim().toLowerCase();
    return items.filter((item) => item.kind === kind && (!text || `${item.name} ${item.subtitle} ${item.description || ""} ${item.statusText}`.toLowerCase().includes(text)));
  }, [items, kind, query]);
  const selected = filtered.find((item) => item.id === selectedId) || filtered[0] || null;
  const summary = resourceSummary(items);

  useEffect(() => {
    setSelectedId(filtered[0]?.id || "");
  }, [kind, query, filtered[0]?.id]);

  return (
    <section className="resource-center-page">
      <aside className="resource-rail">
        <div className="resource-rail-head">
          <small>RESOURCES</small>
          <h2>Resource Center</h2>
        </div>
        {resourceKinds.map((entry) => {
          const count = items.filter((item) => item.kind === entry.id).length;
          const Icon = kindIcon(entry.id);
          return (
            <button className={kind === entry.id ? "active" : ""} key={entry.id} onClick={() => setKind(entry.id)} type="button">
              <Icon size={15} />
              <span>{entry.label}</span>
              <em>{count}</em>
            </button>
          );
        })}
      </aside>

      <main className="resource-main">
        <header className="resource-topbar">
          <div>
            <small>{resourceKinds.find((entry) => entry.id === kind)?.label || "Resources"}</small>
            <h2>{resourceKinds.find((entry) => entry.id === kind)?.description || "Manage runtime resources."}</h2>
          </div>
          <div className="resource-search">
            <Search size={14} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search resources" />
          </div>
          <button onClick={() => refresh()} disabled={loading} type="button"><RefreshCw size={14} /> Refresh</button>
        </header>

        <div className="resource-health-row">
          <HealthCard label="Total" value={summary.total} tone="unknown" />
          <HealthCard label="Healthy" value={summary.healthy} tone="healthy" />
          <HealthCard label="Needs Review" value={summary.warning} tone="warning" />
          <HealthCard label="Errors" value={summary.error} tone="error" />
        </div>
        {notice ? <div className="resource-notice">{notice}</div> : null}

        <div className="resource-content">
          <ResourceList items={filtered} selectedId={selected?.id || ""} onSelect={(item) => setSelectedId(item.id)} />
          <ResourceDetail
            item={selected}
            activeSessionId={activeSessionId}
            onOpenBots={onOpenBots}
            onOpenCapabilities={onOpenCapabilities}
            onOpenAttachments={onOpenAttachments}
          />
        </div>
      </main>
    </section>
  );
}

function ResourceList({ items, selectedId, onSelect }: { items: ResourceItem[]; selectedId: string; onSelect: (item: ResourceItem) => void }) {
  if (!items.length) return <div className="resource-empty">No resources in this category yet.</div>;
  return (
    <div className="resource-list">
      {items.map((item) => (
        <button className={selectedId === item.id ? `resource-row active ${item.status}` : `resource-row ${item.status}`} key={item.id} onClick={() => onSelect(item)} type="button">
          <span className={`resource-dot ${item.status}`} />
          <span>
            <strong>{item.name}</strong>
            <small>{item.subtitle}</small>
          </span>
          <em>{item.statusText}</em>
        </button>
      ))}
    </div>
  );
}

function ResourceDetail({
  item,
  activeSessionId,
  onOpenBots,
  onOpenCapabilities,
  onOpenAttachments
}: {
  item: ResourceItem | null;
  activeSessionId?: string;
  onOpenBots?: () => void;
  onOpenCapabilities?: (kind: ResourceKind) => void;
  onOpenAttachments?: () => void;
}) {
  if (!item) return <aside className="resource-detail"><div className="resource-empty">Select a resource.</div></aside>;
  return (
    <aside className="resource-detail">
      <div className="resource-detail-head">
        <span className={`resource-dot ${item.status}`} />
        <div>
          <small>{item.kind.toUpperCase()}</small>
          <h3>{item.name}</h3>
          <p>{item.description || item.subtitle}</p>
        </div>
      </div>
      <div className="resource-metric-grid">
        {(item.metrics || []).map((metric) => (
          <div key={metric.label}>
            <span>{metric.label}</span>
            <strong>{metric.value}</strong>
          </div>
        ))}
        <div>
          <span>Status</span>
          <strong>{item.statusText}</strong>
        </div>
        {activeSessionId ? <div><span>Session</span><strong>{activeSessionId.slice(0, 12)}</strong></div> : null}
      </div>
      <div className="resource-action-bar">
        {item.kind === "bots" ? <button onClick={onOpenBots} type="button">Open Bot Center</button> : null}
        {item.kind === "attachments" ? <button onClick={onOpenAttachments} type="button">Open Attachments</button> : null}
        {["mcp", "skills", "plugins"].includes(item.kind) ? <button onClick={() => onOpenCapabilities?.(item.kind)} type="button">Edit capability</button> : null}
      </div>
      <details className="resource-raw" open>
        <summary>Configuration preview</summary>
        <pre>{JSON.stringify(redactResourceRaw(item.raw || { id: item.id, status: item.status }), null, 2)}</pre>
      </details>
    </aside>
  );
}

function HealthCard({ label, value, tone }: { label: string; value: number; tone: ResourceStatus }) {
  return (
    <div className={`resource-health-card ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function resourceSummary(items: ResourceItem[]) {
  return {
    total: items.length,
    healthy: items.filter((item) => item.status === "healthy").length,
    warning: items.filter((item) => item.status === "warning" || item.status === "disabled" || item.status === "unknown").length,
    error: items.filter((item) => item.status === "error").length
  };
}

function kindIcon(kind: ResourceKind) {
  if (kind === "tools") return Wrench;
  if (kind === "mcp") return PlugZap;
  if (kind === "skills") return ShieldCheck;
  if (kind === "plugins") return Sparkles;
  if (kind === "bots") return Bot;
  if (kind === "workspaces") return FolderOpen;
  if (kind === "attachments") return FileText;
  if (kind === "memory") return Database;
  if (kind === "artifacts") return HardDrive;
  return Boxes;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function redactResourceRaw(value: unknown, seen = new WeakSet<object>()): unknown {
  if (!value || typeof value !== "object") return value;
  if (seen.has(value)) return "[Circular]";
  seen.add(value);
  if (Array.isArray(value)) return value.map((item) => redactResourceRaw(item, seen));
  const output: Record<string, unknown> = {};
  Object.entries(value as Record<string, unknown>).forEach(([key, item]) => {
    output[key] = /(api[_-]?key|secret|token|password|authorization|signature|app[_-]?secret)/i.test(key)
      ? "[masked]"
      : redactResourceRaw(item, seen);
  });
  return output;
}
