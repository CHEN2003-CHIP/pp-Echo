import { useEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode, type RefObject } from "react";
import { CheckCircle2, Filter, Info, Plus, RefreshCw, Search, Settings, ShieldCheck, SlidersHorizontal, Sparkles, X } from "lucide-react";
import { api, type CapabilityInventory, type ConfigSnapshot, type WorkspaceStatus } from "../../api";

export type CapabilityTab = "mcp" | "skills" | "plugins";
type CapabilityKind = "mcp" | "skill" | "plugin";
type CapabilityFilter = "all" | "installed" | "recommended" | "safe" | "workspace";
type CapabilityDrawerMode = "none" | "detail" | "edit" | "settings";

type CapabilityViewModel = {
  id: string;
  kind: CapabilityKind;
  name: string;
  description?: string;
  provider?: string;
  icon?: string;
  installed: boolean;
  enabled?: boolean;
  recommended?: boolean;
  safe?: boolean;
  scope?: string;
  runtime?: string;
  transport?: string;
  timeout?: string;
  tags: string[];
  status?: string;
  raw: Record<string, unknown>;
};

type CapabilityGroup = {
  id: string;
  title: string;
  description: string;
  items: CapabilityViewModel[];
};

export function CapabilityWorkbench({
  initialTab,
  workspaceStatus,
  activeSessionId
}: {
  initialTab: CapabilityTab;
  workspaceStatus: WorkspaceStatus | null;
  activeSessionId: string;
}) {
  const [tab, setTab] = useState<CapabilityTab>(initialTab);
  const [inventory, setInventory] = useState<CapabilityInventory | null>(null);
  const [snapshot, setSnapshot] = useState<ConfigSnapshot | null>(null);
  const [selectedName, setSelectedName] = useState("");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [settingsDraft, setSettingsDraft] = useState<Record<string, string>>({});
  const [drawerMode, setDrawerMode] = useState<CapabilityDrawerMode>("none");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<CapabilityFilter>("all");
  const [loading, setLoading] = useState(true);
  const [reloading, setReloading] = useState(false);
  const [busyAction, setBusyAction] = useState("");
  const searchRef = useRef<HTMLInputElement | null>(null);

  const items = useMemo(() => capabilityViewModels(inventory, tab), [inventory, tab]);
  const filteredItems = useMemo(() => filterCapabilityItems(items, query, filter), [items, query, filter]);
  const groups = useMemo(() => groupCapabilityItems(filteredItems), [filteredItems]);
  const selected = selectedName ? items.find((item) => item.name === selectedName) : undefined;
  const selectedRaw = selected?.raw;
  const governanceSummary = capabilityGovernanceSummary(inventory, tab);
  const tabCounts = useMemo(() => ({
    mcp: capabilityViewModels(inventory, "mcp").length,
    skills: capabilityViewModels(inventory, "skills").length,
    plugins: capabilityViewModels(inventory, "plugins").length
  }), [inventory]);

  async function reload(options: { quiet?: boolean } = {}) {
    try {
      setError("");
      if (options.quiet) setReloading(true);
      else setLoading(true);
      const [nextInventory, nextSnapshot] = await Promise.all([api.capabilityConfig(), api.config(activeSessionId || undefined)]);
      setInventory(nextInventory);
      setSnapshot(nextSnapshot);
      setSettingsDraft(capabilitySettingsToDraft(nextInventory, tab));
      const nextItems = capabilityViewModels(nextInventory, tab);
      if (selectedName && !nextItems.some((item) => item.name === selectedName)) setSelectedName("");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setLoading(false);
      setReloading(false);
    }
  }

  useEffect(() => {
    setTab(initialTab);
  }, [initialTab]);

  useEffect(() => {
    reload().catch((nextError) => setError(nextError instanceof Error ? nextError.message : String(nextError)));
  }, [tab, activeSessionId]);

  useEffect(() => {
    setDraft(capabilityItemToDraft(selectedRaw, tab));
  }, [selectedName, tab, inventory]);

  useEffect(() => {
    if (tab !== "skills" || !selectedName || !selectedRaw || selectedRaw.body_materialized) return;
    let cancelled = false;
    api.getSkill(selectedName)
      .then((detail) => {
        if (cancelled) return;
        setInventory((current) => current ? {
          ...current,
          skills: {
            ...current.skills,
            items: current.skills.items.map((item) => String(item.name || "") === selectedName ? { ...item, ...detail } : item)
          }
        } : current);
      })
      .catch((nextError) => setError(nextError instanceof Error ? nextError.message : String(nextError)));
    return () => {
      cancelled = true;
    };
  }, [selectedName, tab, selectedRaw]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
      }
      if (event.key === "Escape" && drawerMode !== "none") setDrawerMode("none");
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [drawerMode]);

  async function applySettings() {
    try {
      setBusyAction("settings");
      setError("");
      const patch = capabilitySettingsFromDraft(settingsDraft, tab);
      const response = await api.capabilitySettingsPatch({ [tab]: patch });
      setInventory(response.inventory);
      setSnapshot(response.snapshot);
      setNotice("Settings applied.");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setBusyAction("");
    }
  }

  async function saveItem() {
    try {
      setBusyAction("save");
      setError("");
      const payload = capabilityPayloadFromDraft(draft, tab);
      let nextInventory: CapabilityInventory;
      if (tab === "mcp") {
        nextInventory = selectedRaw ? await api.updateMcpServer(String(selectedRaw.name), payload) : await api.createMcpServer(payload);
      } else if (tab === "skills") {
        nextInventory = selectedRaw ? await api.updateSkill(String(selectedRaw.name), payload) : await api.createSkill(payload);
      } else {
        nextInventory = selectedRaw ? await api.updatePlugin(String(selectedRaw.name), payload) : await api.createPlugin(payload);
      }
      setInventory(nextInventory);
      setSelectedName(String(payload.name || ""));
      setDrawerMode("detail");
      setNotice("Saved.");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setBusyAction("");
    }
  }

  async function deleteMcp() {
    if (tab !== "mcp" || !selectedRaw) return;
    if (!window.confirm(`Delete MCP server "${String(selectedRaw.name)}"? This removes the server from workspace capability configuration.`)) return;
    try {
      setBusyAction("delete");
      setError("");
      const nextInventory = await api.deleteMcpServer(String(selectedRaw.name));
      setInventory(nextInventory);
      setSelectedName("");
      setDrawerMode("none");
      setNotice("Deleted.");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setBusyAction("");
    }
  }

  function newItem() {
    setSelectedName("");
    setDraft(capabilityItemToDraft(null, tab));
    setDrawerMode("edit");
  }

  function openDetail(item: CapabilityViewModel) {
    setSelectedName(item.name);
    setDrawerMode("detail");
  }

  function openEdit(event: MouseEvent, item: CapabilityViewModel) {
    event.stopPropagation();
    setSelectedName(item.name);
    setDraft(capabilityItemToDraft(item.raw, tab));
    setDrawerMode("edit");
  }

  return (
    <section className="capability-workbench">
      <div className="capability-shell">
        <CapabilityHeader
          workspaceStatus={workspaceStatus}
          snapshot={snapshot}
          inventory={inventory}
          governanceSummary={governanceSummary}
          currentCount={items.length}
        />

        <div className="capability-toolbar-sticky">
          <CapabilityTabs active={tab} counts={tabCounts} onChange={(nextTab) => { setTab(nextTab); setSelectedName(""); setFilter("all"); }} />
          <CapabilityToolbar
            tab={tab}
            query={query}
            searchRef={searchRef}
            reloading={reloading}
            onQueryChange={setQuery}
            onReload={() => reload({ quiet: true })}
            onSettings={() => setDrawerMode("settings")}
            onNew={newItem}
          />
          <CapabilityFilters active={filter} onChange={setFilter} />
        </div>

        {error ? <CapabilityError message={error} onRetry={() => reload({ quiet: Boolean(inventory) })} /> : null}
        {notice ? <p className="capability-notice" onAnimationEnd={() => setNotice("")}>{notice}</p> : null}

        <div className="capability-content">
          {loading ? (
            <CapabilityLoadingState />
          ) : (
            <>
              {groups.map((group) => <CapabilitySection key={group.id} group={group} tab={tab} activeName={selectedName} onOpen={openDetail} onEdit={openEdit} busy={Boolean(busyAction)} />)}
              {filteredItems.length === 0 ? <CapabilityEmptyState tab={tab} query={query} filter={filter} total={items.length} /> : null}
            </>
          )}
        </div>
      </div>

      {drawerMode !== "none" ? (
        <CapabilityDetailDrawer
          mode={drawerMode}
          tab={tab}
          item={selected}
          raw={selectedRaw}
          draft={draft}
          settingsDraft={settingsDraft}
          snapshot={snapshot}
          inventory={inventory}
          busyAction={busyAction}
          setDraft={setDraft}
          setSettingsDraft={setSettingsDraft}
          onClose={() => setDrawerMode("none")}
          onEdit={() => setDrawerMode("edit")}
          onRevert={() => setDraft(capabilityItemToDraft(selectedRaw, tab))}
          onRevertSettings={() => inventory ? setSettingsDraft(capabilitySettingsToDraft(inventory, tab)) : undefined}
          onSave={saveItem}
          onApplySettings={applySettings}
          onDeleteMcp={deleteMcp}
        />
      ) : null}
    </section>
  );
}

function CapabilityHeader({
  workspaceStatus,
  snapshot,
  inventory,
  governanceSummary,
  currentCount
}: {
  workspaceStatus: WorkspaceStatus | null;
  snapshot: ConfigSnapshot | null;
  inventory: CapabilityInventory | null;
  governanceSummary: ReturnType<typeof capabilityGovernanceSummary>;
  currentCount: number;
}) {
  return (
    <header className="capability-header">
      <div>
        <p className="capability-eyebrow">Capability Workbench</p>
        <h2>能力中心</h2>
        <p>浏览、安装并管理 MCP、技能与插件。</p>
      </div>
      <div className="capability-status-chips" aria-label="Capability status">
        <span>{workspaceStatus?.git_branch || "no branch"}</span>
        <span>{snapshot?.effective_hash ? snapshot.effective_hash.slice(0, 10) : "hash pending"}</span>
        <span>{runtimeName(snapshot)}</span>
        <span>{governanceSummary.total} governed</span>
        <span>{currentCount} current</span>
        <span>{descriptorStatus(inventory, governanceSummary)}</span>
      </div>
    </header>
  );
}

function CapabilityTabs({ active, counts, onChange }: { active: CapabilityTab; counts: Record<CapabilityTab, number>; onChange: (tab: CapabilityTab) => void }) {
  return (
    <div className="capability-tabs" role="tablist" aria-label="Capability categories">
      {(["mcp", "skills", "plugins"] as CapabilityTab[]).map((item) => (
        <button key={item} className={active === item ? "active" : ""} onClick={() => onChange(item)} role="tab" aria-selected={active === item} type="button">
          <span>{item.toUpperCase()}</span>
          <em>{counts[item]}</em>
        </button>
      ))}
    </div>
  );
}

function CapabilityToolbar({
  tab,
  query,
  searchRef,
  reloading,
  onQueryChange,
  onReload,
  onSettings,
  onNew
}: {
  tab: CapabilityTab;
  query: string;
  searchRef: RefObject<HTMLInputElement>;
  reloading: boolean;
  onQueryChange: (query: string) => void;
  onReload: () => void;
  onSettings: () => void;
  onNew: () => void;
}) {
  return (
    <div className="capability-toolbar">
      <label className="capability-search">
        <Search size={18} />
        <input ref={searchRef} value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder={capabilitySearchPlaceholder(tab)} />
        {query ? <button type="button" onClick={() => onQueryChange("")} aria-label="Clear search"><X size={15} /></button> : <kbd>Ctrl K</kbd>}
      </label>
      <div className="capability-toolbar-actions">
        <button onClick={onReload} disabled={reloading} type="button"><RefreshCw size={16} /> {reloading ? "Reloading" : "Reload"}</button>
        <button onClick={onSettings} type="button"><Settings size={16} /> Settings</button>
        <button className="primary" onClick={onNew} type="button"><Plus size={16} /> New</button>
      </div>
    </div>
  );
}

function CapabilityFilters({ active, onChange }: { active: CapabilityFilter; onChange: (filter: CapabilityFilter) => void }) {
  const filters: Array<{ id: CapabilityFilter; label: string; icon: ReactNode }> = [
    { id: "all", label: "全部", icon: <SlidersHorizontal size={14} /> },
    { id: "installed", label: "已安装", icon: <CheckCircle2 size={14} /> },
    { id: "recommended", label: "推荐", icon: <Sparkles size={14} /> },
    { id: "safe", label: "安全", icon: <ShieldCheck size={14} /> },
    { id: "workspace", label: "工作区", icon: <Filter size={14} /> }
  ];
  return (
    <div className="capability-filters" aria-label="Capability filters">
      {filters.map((item) => (
        <button key={item.id} className={active === item.id ? "active" : ""} onClick={() => onChange(item.id)} type="button">
          {item.icon}
          {item.label}
        </button>
      ))}
    </div>
  );
}

function CapabilitySection({ group, tab, activeName, onOpen, onEdit, busy }: { group: CapabilityGroup; tab: CapabilityTab; activeName: string; onOpen: (item: CapabilityViewModel) => void; onEdit: (event: MouseEvent, item: CapabilityViewModel) => void; busy: boolean }) {
  if (!group.items.length) return null;
  return (
    <section className="capability-section">
      <div className="capability-section-head">
        <div>
          <h3>{group.title}</h3>
          <p>{group.description}</p>
        </div>
        <span>{group.items.length}</span>
      </div>
      <div className="capability-grid">
        {group.items.map((item) => (
          <CapabilityCard key={item.id} item={item} tab={tab} active={item.name === activeName} busy={busy} onOpen={() => onOpen(item)} onEdit={(event) => onEdit(event, item)} />
        ))}
      </div>
    </section>
  );
}

function CapabilityCard({ item, tab, active, busy, onOpen, onEdit }: { item: CapabilityViewModel; tab: CapabilityTab; active: boolean; busy: boolean; onOpen: () => void; onEdit: (event: MouseEvent) => void }) {
  return (
    <article className={active ? "capability-card active" : "capability-card"} onClick={onOpen} title={item.description || item.name}>
      <div className={`capability-card-initials capability-card-initials-${tab}`}>{item.icon || capabilityInitials(item.name, tab)}</div>
      <div className="capability-card-body">
        <div className="capability-card-top">
          <span>{capabilityKindLabel(item.kind)}</span>
          <em className={item.enabled === false ? "muted" : "success"}>{item.status || (item.installed ? "Installed" : "Available")}</em>
        </div>
        <strong>{item.name || "unnamed"}</strong>
        <p>{item.description || "No description yet."}</p>
        <div className="capability-card-meta">
          {[item.provider, item.transport, item.runtime, item.scope, item.timeout, ...item.tags].filter(Boolean).slice(0, 5).map((meta) => <span key={String(meta)}>{String(meta)}</span>)}
        </div>
      </div>
      <button className="capability-card-action" onClick={onEdit} disabled={busy} type="button">{item.installed ? "Configure" : "Install"}</button>
    </article>
  );
}

function CapabilityDetailDrawer({
  mode,
  tab,
  item,
  raw,
  draft,
  settingsDraft,
  snapshot,
  inventory,
  busyAction,
  setDraft,
  setSettingsDraft,
  onClose,
  onEdit,
  onRevert,
  onRevertSettings,
  onSave,
  onApplySettings,
  onDeleteMcp
}: {
  mode: CapabilityDrawerMode;
  tab: CapabilityTab;
  item?: CapabilityViewModel;
  raw?: Record<string, unknown>;
  draft: Record<string, string>;
  settingsDraft: Record<string, string>;
  snapshot: ConfigSnapshot | null;
  inventory: CapabilityInventory | null;
  busyAction: string;
  setDraft: (value: Record<string, string>) => void;
  setSettingsDraft: (value: Record<string, string>) => void;
  onClose: () => void;
  onEdit: () => void;
  onRevert: () => void;
  onRevertSettings: () => void;
  onSave: () => void;
  onApplySettings: () => void;
  onDeleteMcp: () => void;
}) {
  return (
    <div className="capability-drawer-backdrop" onClick={onClose}>
      <aside className="capability-drawer" onClick={(event) => event.stopPropagation()} aria-label="Capability details">
        {mode === "settings" ? (
          <>
            <CapabilityDrawerHead eyebrow="Settings" title={`${tab.toUpperCase()} settings`} subtitle={snapshot?.pending_effects?.slice(0, 3).join(", ") || `${snapshot?.reload_policy || "hot"} reload policy`} onClose={onClose} />
            <div className="capability-drawer-actions">
              <button onClick={onRevertSettings} disabled={!inventory || Boolean(busyAction)} type="button">Revert</button>
              <button className="primary" onClick={onApplySettings} disabled={Boolean(busyAction)} type="button">{busyAction === "settings" ? "Applying" : "Apply"}</button>
            </div>
            <div className="capability-settings-card drawer">{renderCapabilitySettings(settingsDraft, setSettingsDraft, tab)}</div>
          </>
        ) : mode === "edit" ? (
          <>
            <CapabilityDrawerHead eyebrow={raw ? "Configure" : "Create"} title={raw ? String(raw.name || item?.name || "Capability") : `New ${capabilitySingular(tab)}`} subtitle={raw ? capabilityDescription(raw) : "Create a workspace capability entry."} onClose={onClose} />
            <div className="capability-drawer-actions">
              {tab === "mcp" && raw ? <button className="danger" onClick={onDeleteMcp} disabled={Boolean(busyAction)} type="button">Delete</button> : null}
              <button onClick={onRevert} disabled={Boolean(busyAction)} type="button">Revert</button>
              <button className="primary" onClick={onSave} disabled={Boolean(busyAction)} type="button">{busyAction === "save" ? "Saving" : "Apply"}</button>
            </div>
            {renderCapabilityEditor(tab, draft, setDraft)}
          </>
        ) : (
          <>
            <CapabilityDrawerHead eyebrow={item ? capabilityKindLabel(item.kind) : "Capability"} title={item?.name || "Capability details"} subtitle={item?.description || "No description yet."} onClose={onClose} />
            {item ? <CapabilityDetail item={item} /> : null}
            <div className="capability-drawer-actions">
              <button onClick={onEdit} type="button">Configure</button>
              <button className="primary" onClick={onClose} type="button">Done</button>
            </div>
          </>
        )}
      </aside>
    </div>
  );
}

function CapabilityDrawerHead({ eyebrow, title, subtitle, onClose }: { eyebrow: string; title: string; subtitle: string; onClose: () => void }) {
  return (
    <div className="capability-drawer-head">
      <div>
        <small>{eyebrow}</small>
        <h3>{title}</h3>
        <p>{subtitle}</p>
      </div>
      <button className="icon-button" onClick={onClose} type="button" aria-label="Close details"><X size={16} /></button>
    </div>
  );
}

function CapabilityDetail({ item }: { item: CapabilityViewModel }) {
  const rows = [
    ["Provider", item.provider],
    ["Runtime", item.runtime],
    ["Scope", item.scope],
    ["Transport", item.transport],
    ["Timeout", item.timeout],
    ["Approval", item.safe === false ? "Review required" : "No special warning"],
    ["Status", item.status],
    ["Tags", item.tags.join(", ")]
  ].filter(([, value]) => value);
  return (
    <div className="capability-detail">
      {rows.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}
      <details>
        <summary>Raw descriptor</summary>
        <pre>{JSON.stringify(item.raw, null, 2)}</pre>
      </details>
    </div>
  );
}

function CapabilityLoadingState() {
  return (
    <div className="capability-loading-grid" aria-label="Loading capabilities">
      {Array.from({ length: 6 }).map((_, index) => <div key={index} className="capability-skeleton-card" />)}
    </div>
  );
}

function CapabilityEmptyState({ tab, query, filter, total }: { tab: CapabilityTab; query: string; filter: CapabilityFilter; total: number }) {
  const title = total === 0 ? `No ${tab.toUpperCase()} capabilities yet` : query ? "No search results" : "No capabilities match this filter";
  const body = total === 0
    ? "Create a capability or adjust settings to discover workspace resources."
    : query
      ? "Try a different name, provider, description, or tag."
      : `The ${filter} filter has no matching ${tab.toUpperCase()} capabilities.`;
  return (
    <div className="capability-empty">
      <Info size={22} />
      <h3>{title}</h3>
      <p>{body}</p>
    </div>
  );
}

function CapabilityError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="capability-error">
      <div><strong>Capability request failed</strong><span>{message}</span></div>
      <button onClick={onRetry} type="button">Retry</button>
    </div>
  );
}

function capabilityViewModels(inventory: CapabilityInventory | null, tab: CapabilityTab): CapabilityViewModel[] {
  if (!inventory) return [];
  const items = capabilityItems(inventory, tab);
  return items.map((item, index) => capabilityViewModel(item, tab, index, inventory));
}

function capabilityItems(inventory: CapabilityInventory | null, tab: CapabilityTab): Array<Record<string, unknown>> {
  if (!inventory) return [];
  if (tab === "mcp") return inventory.mcp.servers;
  return inventory[tab].items;
}

function capabilityViewModel(item: Record<string, unknown>, tab: CapabilityTab, index: number, inventory: CapabilityInventory): CapabilityViewModel {
  const name = String(item.name || item.id || `${tab}-${index}`);
  const descriptor = findCapabilityDescriptor(inventory, tab, name);
  const kind: CapabilityKind = tab === "mcp" ? "mcp" : tab === "skills" ? "skill" : "plugin";
  const tags = uniqueStrings([
    ...listStrings(item.tags),
    ...listStrings(item.provides),
    stringValue(item.source),
    stringValue(item.protocol),
    stringValue(item.transport),
    stringValue(descriptor?.risk_level)
  ]).slice(0, 8);
  const scope = firstString(item.scope, item.workspace_scope, item.root, item.path, descriptor?.scope, inventory.workspace);
  const safe = Boolean(item.safe ?? descriptor?.safe ?? !["high", "critical"].includes(String(descriptor?.risk_level || "").toLowerCase()));
  return {
    id: `${tab}:${name}`,
    kind,
    name,
    description: capabilityDescription(item) || stringValue(descriptor?.description),
    provider: firstString(item.provider, item.source, item.entrypoint, descriptor?.provider, tab === "mcp" ? "MCP" : tab === "skills" ? "Skill" : "Plugin"),
    icon: stringValue(item.icon),
    installed: item.installed !== false,
    enabled: item.enabled === undefined ? true : Boolean(item.enabled),
    recommended: Boolean(item.recommended ?? descriptor?.recommended),
    safe,
    scope: scope ? compactPath(scope) : undefined,
    runtime: firstString(item.runtime, item.protocol, descriptor?.runtime),
    transport: firstString(item.resolved_transport, item.transport),
    timeout: item.timeout_seconds ? `${item.timeout_seconds}s` : undefined,
    tags,
    status: capabilityStatus(item, tab),
    raw: item
  };
}

function filterCapabilityItems(items: CapabilityViewModel[], query: string, filter: CapabilityFilter) {
  const text = query.trim().toLowerCase();
  return items.filter((item) => {
    const matchesFilter =
      filter === "all" ||
      (filter === "installed" && item.installed) ||
      (filter === "recommended" && item.recommended) ||
      (filter === "safe" && item.safe !== false) ||
      (filter === "workspace" && `${item.scope || ""} ${item.provider || ""} ${item.tags.join(" ")}`.toLowerCase().includes("workspace"));
    if (!matchesFilter) return false;
    if (!text) return true;
    return [
      item.name,
      item.description,
      item.provider,
      item.scope,
      item.runtime,
      item.transport,
      item.timeout,
      item.status,
      item.tags.join(" "),
      item.raw.path,
      item.raw.entrypoint,
      item.raw.command,
      item.raw.url
    ].map((value) => String(value || "")).join(" ").toLowerCase().includes(text);
  });
}

function groupCapabilityItems(items: CapabilityViewModel[]): CapabilityGroup[] {
  const installed = items.filter((item) => item.installed);
  const recommended = items.filter((item) => !item.installed && item.recommended);
  const available = items.filter((item) => !item.installed && !item.recommended);
  return [
    { id: "installed", title: "已安装", description: "当前工作区已经配置或启用的能力。", items: installed },
    { id: "recommended", title: "推荐", description: "由元数据标记为推荐的能力。", items: recommended },
    { id: "available", title: "其他可用能力", description: "可安装或可配置的能力。", items: available }
  ];
}

function capabilityGovernanceSummary(inventory: CapabilityInventory | null, tab: CapabilityTab) {
  const snapshot = inventory?.capabilities;
  const items = snapshot?.items || [];
  const total = Number(snapshot?.count || items.length || 0);
  const kinds = capabilityGovernanceKinds(tab);
  const discoveredCount = kinds.reduce((count, kind) => count + Number(snapshot?.by_kind?.[kind] || 0), 0);
  const staticMcpCount = tab === "mcp" ? Number(inventory?.mcp?.servers?.length || 0) : 0;
  const currentTab = discoveredCount || staticMcpCount;
  const riskCounts = items.reduce<Record<string, number>>((counts, item) => {
    const kind = String(item.kind || "");
    if (!kinds.includes(kind)) return counts;
    const risk = String(item.risk_level || "unknown");
    counts[risk] = (counts[risk] || 0) + 1;
    return counts;
  }, {});
  const risk = Object.entries(riskCounts)
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .slice(0, 2)
    .map(([name, count]) => `${count} ${name}`)
    .join(", ") || (tab === "mcp" && staticMcpCount ? "live descriptors deferred" : "no catalog risk");
  return { total, currentTab, label: capabilityGovernanceLabel(tab), risk };
}

function capabilityGovernanceKinds(tab: CapabilityTab) {
  if (tab === "mcp") return ["mcp_tool", "mcp_resource", "mcp_prompt"];
  if (tab === "skills") return ["skill"];
  return ["runtime_adapter", "extension"];
}

function capabilityGovernanceLabel(tab: CapabilityTab) {
  if (tab === "mcp") return "MCP capabilities";
  if (tab === "skills") return "skill capabilities";
  return "plugin capabilities";
}

function findCapabilityDescriptor(inventory: CapabilityInventory, tab: CapabilityTab, name: string): Record<string, unknown> | undefined {
  const kinds = capabilityGovernanceKinds(tab);
  return (inventory.capabilities?.items || []).find((item) => {
    if (!kinds.includes(String(item.kind || ""))) return false;
    const descriptorName = firstString(item.name, item.id, item.display_name);
    return descriptorName === name || String(descriptorName || "").endsWith(`:${name}`);
  });
}

function capabilityStatus(item: Record<string, unknown>, tab: CapabilityTab) {
  if (item.enabled === false) return "Disabled";
  if (tab === "mcp") return String(item.resolved_transport || item.transport || "Server");
  if (tab === "skills") return String(item.source || "Skill");
  return String(item.entrypoint ? "Configured" : "Plugin");
}

function capabilityInitials(name: string, tab: CapabilityTab) {
  const fallback = tab === "mcp" ? "MC" : tab === "skills" ? "SK" : "PL";
  const clean = name.trim();
  if (!clean) return fallback;
  const parts = clean.split(/[\s._/-]+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  return clean.slice(0, 2).toUpperCase();
}

function capabilityKindLabel(kind: CapabilityKind) {
  if (kind === "mcp") return "MCP";
  if (kind === "skill") return "Skill";
  return "Plugin";
}

function capabilitySingular(tab: CapabilityTab) {
  if (tab === "mcp") return "MCP server";
  if (tab === "skills") return "skill";
  return "plugin";
}

function capabilitySearchPlaceholder(tab: CapabilityTab) {
  if (tab === "mcp") return "Search MCP by name, transport, provider, or tag";
  if (tab === "skills") return "Search skills by name, description, source, or tag";
  return "Search plugins by name, entrypoint, provider, or tag";
}

function capabilityDescription(item: Record<string, unknown>) {
  return firstString(item.description, item.summary, item.path, item.entrypoint, item.command, item.url) || "";
}

function descriptorStatus(inventory: CapabilityInventory | null, governanceSummary: ReturnType<typeof capabilityGovernanceSummary>) {
  if (!inventory?.capabilities) return "descriptors pending";
  return governanceSummary.currentTab ? "live descriptors" : "no descriptors";
}

function runtimeName(snapshot: ConfigSnapshot | null) {
  const runtime = recordValue(snapshot?.runtime_config);
  const effective = recordValue(snapshot?.effective_config);
  return firstString(runtime?.runtime, runtime?.runtime_id, runtime?.name, effective?.runtime, effective?.runtime_id, "runtime");
}

function capabilitySettingsToDraft(inventory: CapabilityInventory, tab: CapabilityTab): Record<string, string> {
  const settings = inventory.settings[tab] || {};
  return {
    enable: String(Boolean(settings.enable ?? settings.enable_project)),
    enable_project: String(Boolean(settings.enable_project ?? true)),
    enable_user: String(Boolean(settings.enable_user ?? true)),
    enable_builtin: String(Boolean(settings.enable_builtin ?? tab === "skills")),
    config_paths: stringifyList(settings.config_paths),
    server_filters: stringifyList(settings.server_filters),
    custom_directories: stringifyList(settings.custom_directories),
    include: stringifyList(settings.include),
    ignored: stringifyList(settings.ignored)
  };
}

function capabilitySettingsFromDraft(draft: Record<string, string>, tab: CapabilityTab): Record<string, unknown> {
  if (tab === "mcp") {
    return {
      enable: draft.enable === "true",
      config_paths: parseLines(draft.config_paths),
      server_filters: parseLines(draft.server_filters)
    };
  }
  return {
    enable_project: draft.enable_project === "true",
    enable_user: draft.enable_user === "true",
    enable_builtin: draft.enable_builtin === "true",
    custom_directories: parseLines(draft.custom_directories),
    include: parseLines(draft.include),
    ignored: parseLines(draft.ignored)
  };
}

function capabilityItemToDraft(item: Record<string, unknown> | undefined | null, tab: CapabilityTab): Record<string, string> {
  if (tab === "mcp") {
    return {
      name: String(item?.name || ""),
      description: String(item?.description || ""),
      transport: String(item?.transport || item?.resolved_transport || "stdio"),
      protocol: String(item?.protocol || "auto"),
      command: String(item?.command || ""),
      args: stringifyList(item?.args),
      url: String(item?.url || ""),
      cwd: String(item?.cwd || ""),
      env: stringifyJson(item?.env || {}),
      headers: stringifyJson(item?.headers || {}),
      bearer_token_env: String(item?.bearer_token_env || ""),
      timeout_seconds: String(item?.timeout_seconds || 30)
    };
  }
  if (tab === "skills") {
    return {
      name: String(item?.name || ""),
      description: String(item?.description || ""),
      body: String(item?.body || "")
    };
  }
  return {
    name: String(item?.name || ""),
    description: String(item?.description || ""),
    entrypoint: String(item?.entrypoint || ""),
    provides: stringifyList(item?.provides)
  };
}

function capabilityPayloadFromDraft(draft: Record<string, string>, tab: CapabilityTab): Record<string, unknown> {
  if (tab === "mcp") {
    return {
      name: draft.name,
      description: draft.description,
      transport: draft.transport,
      protocol: draft.protocol || "auto",
      command: draft.command || null,
      args: parseLines(draft.args),
      url: draft.url || null,
      cwd: draft.cwd || null,
      env: parseJsonObject(draft.env),
      headers: parseJsonObject(draft.headers),
      bearer_token_env: draft.bearer_token_env || null,
      timeout_seconds: Number(draft.timeout_seconds || 30)
    };
  }
  if (tab === "skills") return { name: draft.name, description: draft.description, body: draft.body };
  return { name: draft.name, description: draft.description, entrypoint: draft.entrypoint || null, provides: parseLines(draft.provides) };
}

function renderCapabilitySettings(draft: Record<string, string>, setDraft: (value: Record<string, string>) => void, tab: CapabilityTab) {
  const update = (key: string, value: string) => setDraft({ ...draft, [key]: value });
  if (tab === "mcp") {
    return (
      <div className="capability-settings-fields">
        <label className="settings-toggle"><input type="checkbox" checked={draft.enable === "true"} onChange={(event) => update("enable", String(event.target.checked))} /> Enabled</label>
        <label><span>Config paths</span><textarea value={draft.config_paths || ""} onChange={(event) => update("config_paths", event.target.value)} /></label>
        <label><span>Server filters</span><textarea value={draft.server_filters || ""} onChange={(event) => update("server_filters", event.target.value)} /></label>
      </div>
    );
  }
  return (
    <div className="capability-settings-fields">
      {["enable_project", "enable_user", "enable_builtin"].map((key) => (
        <label key={key} className="settings-toggle"><input type="checkbox" checked={draft[key] === "true"} onChange={(event) => update(key, String(event.target.checked))} /> {key}</label>
      ))}
      <label><span>Custom directories</span><textarea value={draft.custom_directories || ""} onChange={(event) => update("custom_directories", event.target.value)} /></label>
      <label><span>Include</span><textarea value={draft.include || ""} onChange={(event) => update("include", event.target.value)} /></label>
      <label><span>Ignored</span><textarea value={draft.ignored || ""} onChange={(event) => update("ignored", event.target.value)} /></label>
    </div>
  );
}

function renderCapabilityEditor(tab: CapabilityTab, draft: Record<string, string>, setDraft: (value: Record<string, string>) => void) {
  const update = (key: string, value: string) => setDraft({ ...draft, [key]: value });
  const field = (key: string, label: string, multiline = false) => (
    <label className="capability-field">
      <span>{label}</span>
      {multiline ? <textarea value={draft[key] || ""} onChange={(event) => update(key, event.target.value)} /> : <input value={draft[key] || ""} onChange={(event) => update(key, event.target.value)} />}
    </label>
  );
  if (tab === "mcp") {
    return (
      <div className="capability-form">
        {field("name", "Name")}
        {field("description", "Description")}
        <label className="capability-field"><span>Transport</span><select value={draft.transport || "stdio"} onChange={(event) => update("transport", event.target.value)}><option value="stdio">stdio</option><option value="http">http</option><option value="auto">auto</option></select></label>
        <label className="capability-field"><span>Protocol</span><select value={draft.protocol || "auto"} onChange={(event) => update("protocol", event.target.value)}><option value="auto">auto</option><option value="standard">standard</option><option value="compat">compat</option></select></label>
        {field("command", "Command")}
        {field("args", "Args", true)}
        {field("url", "URL")}
        {field("cwd", "CWD")}
        {field("env", "Env JSON", true)}
        {field("headers", "Headers JSON", true)}
        {field("bearer_token_env", "Bearer token env")}
        {field("timeout_seconds", "Timeout seconds")}
      </div>
    );
  }
  if (tab === "skills") {
    return <div className="capability-form">{field("name", "Name")}{field("description", "Description")}{field("body", "Skill body", true)}</div>;
  }
  return <div className="capability-form">{field("name", "Name")}{field("description", "Description")}{field("entrypoint", "Entrypoint")}{field("provides", "Provides", true)}</div>;
}

function stringifyList(value: unknown): string {
  return Array.isArray(value) ? value.map(String).join("\n") : "";
}

function parseLines(value?: string): string[] {
  return String(value || "").split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean);
}

function stringifyJson(value: unknown): string {
  return JSON.stringify(value || {}, null, 2);
}

function parseJsonObject(value?: string): Record<string, string> {
  const text = String(value || "").trim();
  if (!text) return {};
  const parsed = JSON.parse(text);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Expected a JSON object");
  return parsed as Record<string, string>;
}

function listStrings(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item || "").trim()).filter(Boolean);
}

function uniqueStrings(values: Array<string | undefined>) {
  return Array.from(new Set(values.map((value) => String(value || "").trim()).filter(Boolean)));
}

function firstString(...values: unknown[]) {
  for (const value of values) {
    const text = stringValue(value);
    if (text) return text;
  }
  return "";
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function compactPath(value: string) {
  return value.replace(/\\/g, "/").split("/").filter(Boolean).slice(-3).join("/");
}
