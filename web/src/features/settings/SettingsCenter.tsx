import { useEffect, useMemo, useState } from "react";
import { Bot, Brain, Database, Eye, EyeOff, KeyRound, RefreshCw, RotateCcw, Save, Search, Settings, ShieldCheck, SlidersHorizontal, Wrench } from "lucide-react";
import { api, type ConfigField, type ConfigSnapshot } from "../../api";

type SettingsCategory = "general" | "providers" | "tools" | "agent" | "resources" | "memory" | "security" | "advanced";
type SettingsScope = "project" | "profile" | "session";

const categories: Array<{ id: SettingsCategory; label: string; description: string; icon: typeof Settings }> = [
  { id: "general", label: "General", description: "Workspace defaults and everyday behavior.", icon: Settings },
  { id: "providers", label: "Models & Providers", description: "Model, provider, and endpoint configuration.", icon: KeyRound },
  { id: "tools", label: "Tools & Capabilities", description: "Tool policy, built-in capabilities, and approvals.", icon: Wrench },
  { id: "agent", label: "Agent Behavior", description: "Planning, subagents, checkpoints, and compaction.", icon: Brain },
  { id: "resources", label: "Integrations", description: "MCP, skills, plugins, and bot gateway settings.", icon: Bot },
  { id: "memory", label: "Memory & Learning", description: "Memory files, search, learning, and storage.", icon: Database },
  { id: "security", label: "Security", description: "External access, shell risk, and approval safeguards.", icon: ShieldCheck },
  { id: "advanced", label: "Advanced", description: "Raw JSON patching and diagnostics.", icon: SlidersHorizontal }
];

export function SettingsCenter({
  sessionId,
  initialCategory = "general",
  onSaved,
  onOpenCapabilities
}: {
  sessionId?: string;
  initialCategory?: string;
  onSaved?: () => void;
  onOpenCapabilities?: () => void;
}) {
  const [snapshot, setSnapshot] = useState<ConfigSnapshot | null>(null);
  const [category, setCategory] = useState<SettingsCategory>(normalizeCategory(initialCategory));
  const [scope, setScope] = useState<SettingsScope>(sessionId ? "session" : "project");
  const [profileDraft, setProfileDraft] = useState("");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [jsonDraft, setJsonDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});

  useEffect(() => {
    load().catch((err) => setError(errorMessage(err)));
  }, [sessionId]);

  useEffect(() => {
    setCategory(normalizeCategory(initialCategory));
  }, [initialCategory]);

  useEffect(() => {
    if (!snapshot) return;
    setJsonDraft(JSON.stringify(readScopeConfig(snapshot, scope, profileDraft), null, 2));
  }, [snapshot, scope, profileDraft]);

  async function load() {
    const payload = await api.config(sessionId || undefined);
    setSnapshot(payload);
    setProfileDraft(payload.active_profile || payload.profiles[0] || "default");
    setDrafts(buildDrafts(payload));
    setJsonDraft(JSON.stringify(payload.settings, null, 2));
    setError("");
    setNotice("");
  }

  async function applyChanges() {
    if (!snapshot) return;
    const dirty = fields.filter((field) => fieldDirty(snapshot, drafts, field, scope, profileDraft));
    if (!dirty.length) return;
    if (scope === "session" && !sessionId) {
      setError("Open a session before applying session overrides.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      let updated = snapshot;
      let baseHash = snapshot.config_hash;
      for (const field of dirty) {
        const value = parseDraft(drafts[field.path], field.type);
        if (scope === "session" && sessionId) updated = await api.sessionConfigSet(sessionId, field.path, value);
        else if (scope === "profile") updated = await api.configProfileSet(profileDraft || "default", field.path, value, baseHash, sessionId || undefined);
        else updated = await api.configSet(field.path, value, baseHash);
        baseHash = updated.config_hash;
      }
      setSnapshot(updated);
      setDrafts(buildDrafts(updated));
      setNotice("Settings saved.");
      onSaved?.();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function applyJson() {
    if (!snapshot) return;
    setSaving(true);
    setError("");
    try {
      const parsed = JSON.parse(jsonDraft || "{}");
      const updated = await api.configPatch(parsed, snapshot.config_hash);
      setSnapshot(updated);
      setDrafts(buildDrafts(updated));
      setNotice("JSON patch saved.");
      onSaved?.();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  function revert() {
    if (!snapshot) return;
    setDrafts(buildDrafts(snapshot));
    setJsonDraft(JSON.stringify(readScopeConfig(snapshot, scope, profileDraft), null, 2));
    setError("");
    setNotice("");
  }

  const fields = snapshot?.schema.fields || [];
  const visibleFields = useMemo(() => fields.filter((field) => categoryMatches(field, category) && matchesSettingSearch(field, query)), [fields, category, query]);
  const dirtyCount = snapshot ? fields.filter((field) => fieldDirty(snapshot, drafts, field, scope, profileDraft)).length : 0;
  const selectedCategory = categories.find((item) => item.id === category) || categories[0];
  const CategoryIcon = selectedCategory.icon;

  return (
    <section className="settings-center-page">
      <aside className="settings-center-nav">
        <div className="settings-center-title">
          <small>SETTINGS</small>
          <h2>Settings Center</h2>
          <p>{snapshot ? `${snapshot.reload_policy} reload / ${snapshot.active_profile || "no profile"}` : "Loading configuration"}</p>
        </div>
        <div className="settings-scope-card">
          <span>Scope</span>
          <div className="segmented-control">
            <button className={scope === "project" ? "active" : ""} onClick={() => setScope("project")} type="button">Project</button>
            <button className={scope === "profile" ? "active" : ""} onClick={() => setScope("profile")} type="button">Profile</button>
            <button className={scope === "session" ? "active" : ""} onClick={() => setScope("session")} disabled={!sessionId} type="button">Session</button>
          </div>
          {scope === "profile" ? <input value={profileDraft} onChange={(event) => setProfileDraft(event.target.value)} placeholder="profile name" /> : null}
        </div>
        {categories.map((item) => (
          <button className={category === item.id ? "active" : ""} key={item.id} onClick={() => setCategory(item.id)} type="button">
            <item.icon size={15} />
            <span>{item.label}</span>
          </button>
        ))}
      </aside>

      <main className="settings-center-main">
        <header className="settings-center-header">
          <div>
            <small>SETTINGS</small>
            <h2>Manage models, permissions, memory, web access, and Agent behavior.</h2>
          </div>
          <div className="settings-center-actions">
            {category === "resources" ? <button onClick={onOpenCapabilities} type="button">Open Capability Workbench</button> : null}
            <button onClick={() => load()} disabled={saving} type="button"><RefreshCw size={14} /> Reload</button>
          </div>
        </header>

        <div className="settings-toolbar">
          <label className="settings-search">
            <Search size={14} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search settings" />
          </label>
        </div>

        <div className="settings-health-strip">
          <div><span>Fields</span><strong>{visibleFields.length}</strong></div>
          <div><span>Pending</span><strong>{dirtyCount}</strong></div>
          <div><span>Profile</span><strong>{snapshot?.active_profile || "default"}</strong></div>
          <div><span>Reload</span><strong>{snapshot?.reload_policy || "unknown"}</strong></div>
        </div>
        {error ? <div className="settings-error">{error}</div> : null}
        {notice ? <div className="settings-success">{notice}</div> : null}
        {snapshot?.pending_effects?.length ? <div className="settings-pending">{snapshot.pending_effects.slice(0, 6).map((item) => <span key={item}>{item}</span>)}</div> : null}

        {category === "advanced" ? (
          <section className="settings-json-editor product">
            <div>
              <strong>Advanced JSON</strong>
              <span>Project-level patch editor. Sensitive values are still handled by the existing config API.</span>
            </div>
            <textarea value={jsonDraft} onChange={(event) => setJsonDraft(event.target.value)} />
            <button onClick={applyJson} disabled={saving} type="button"><Save size={14} /> Apply JSON</button>
          </section>
        ) : (
          <section className="settings-group">
            <div className="settings-group-head">
              <CategoryIcon size={16} />
              <div>
                <h3>{selectedCategory.label}</h3>
                <p>{selectedCategory.description}</p>
              </div>
            </div>
            <div className="settings-field-grid">
            {visibleFields.map((field) => {
              const dirty = snapshot ? fieldDirty(snapshot, drafts, field, scope, profileDraft) : false;
              const secret = isSecretField(field);
              return (
                <article className={settingCardClass(field, dirty)} key={field.path}>
                  <div>
                    <strong>{fieldLabel(field.path)}</strong>
                    <span>{field.description || "No description."}</span>
                    <em>{field.reload_policy} / {snapshot?.source_map[field.path] || "default"}</em>
                  </div>
                  <div className="setting-card-control">
                    {renderInput(field, drafts[field.path] || "", (value) => setDrafts((current) => ({ ...current, [field.path]: value })), Boolean(revealed[field.path]))}
                    {secret ? (
                      <button onClick={() => setRevealed((current) => ({ ...current, [field.path]: !current[field.path] }))} type="button">
                        {revealed[field.path] ? <EyeOff size={14} /> : <Eye size={14} />}
                        {revealed[field.path] ? "Hide" : "Show"}
                      </button>
                    ) : null}
                    <small>{dirty ? "Changed" : "Synced"}</small>
                  </div>
                </article>
              );
            })}
            {snapshot && !visibleFields.length ? <div className="settings-empty">No settings match this category or search.</div> : null}
            </div>
          </section>
        )}
      </main>

      <footer className="settings-center-footer">
        <span>{dirtyCount} pending change{dirtyCount === 1 ? "" : "s"}</span>
        <button onClick={revert} disabled={!dirtyCount || saving} type="button"><RotateCcw size={14} /> Revert</button>
        <button className="primary" onClick={applyChanges} disabled={!dirtyCount || saving || category === "advanced"} type="button"><Save size={14} /> {saving ? "Saving" : "Apply"}</button>
      </footer>
    </section>
  );
}

function normalizeCategory(value: string): SettingsCategory {
  if (value === "model" || value === "browser_web") return "providers";
  if (value === "skills" || value === "plugins") return "resources";
  if (value === "subagents" || value === "storage" || value === "learning") return "agent";
  if (value === "tools") return "tools";
  if (value === "memory") return "memory";
  return categories.some((item) => item.id === value) ? value as SettingsCategory : "general";
}

function categoryMatches(field: ConfigField, category: SettingsCategory) {
  if (category === "general") return ["provider.base_url", "model.model", "tool_policy.confirm_high_risk_plan"].includes(field.path);
  if (category === "providers") return field.category === "model" || field.category === "browser_web" || field.path.startsWith("provider.");
  if (category === "tools") return field.category === "tools" || field.path.startsWith("tool_policy.") || field.path.startsWith("capabilities.builtin_tools");
  if (category === "agent") return ["subagents", "storage", "learning"].includes(field.category);
  if (category === "resources") return ["skills", "plugins"].includes(field.category) || field.path.startsWith("capabilities.mcp");
  if (category === "memory") return field.category === "memory" || field.path.includes("memory");
  if (category === "security") return field.path.includes("approval") || field.path.includes("shell") || field.path.includes("security");
  return false;
}

function renderInput(field: ConfigField, value: string, onChange: (value: string) => void, revealed = false) {
  if (field.type === "boolean") {
    return (
      <div className="setting-switch">
        <button className={value !== "true" ? "active" : ""} onClick={() => onChange("false")} type="button">Off</button>
        <button className={value === "true" ? "active" : ""} onClick={() => onChange("true")} type="button">On</button>
      </div>
    );
  }
  if (field.type === "array" || field.type === "object" || field.type.includes("null")) {
    return <textarea value={value} onChange={(event) => onChange(event.target.value)} rows={3} />;
  }
  return <input type={isSecretField(field) && !revealed ? "password" : field.type === "number" || field.type.startsWith("integer") ? "number" : "text"} value={value} onChange={(event) => onChange(event.target.value)} />;
}

function settingCardClass(field: ConfigField, dirty: boolean) {
  const classes = ["settings-product-field"];
  if (dirty) classes.push("dirty");
  if (field.type === "array" || field.type === "object" || field.type.includes("null")) classes.push("wide");
  if (isDangerField(field)) classes.push("danger");
  return classes.join(" ");
}

function fieldLabel(path: string) {
  return path
    .split(".")
    .slice(-2)
    .join(" ")
    .replace(/[_-]/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function matchesSettingSearch(field: ConfigField, query: string) {
  const text = query.trim().toLowerCase();
  if (!text) return true;
  return `${field.path} ${field.category} ${field.description || ""} ${field.type}`.toLowerCase().includes(text);
}

function isSecretField(field: ConfigField) {
  return /(api[_-]?key|secret|token|password|authorization|credential)/i.test(field.path);
}

function isDangerField(field: ConfigField) {
  return /(shell|delete|reset|danger|unrestricted|approval|write|filesystem)/i.test(field.path);
}

function buildDrafts(snapshot: ConfigSnapshot) {
  const drafts: Record<string, string> = {};
  snapshot.schema.fields.forEach((field) => {
    drafts[field.path] = stringify(readPath(readScopeConfig(snapshot, "project", snapshot.active_profile || ""), field.path));
  });
  return drafts;
}

function readScopeConfig(snapshot: ConfigSnapshot, scope: SettingsScope, profile: string) {
  if (scope === "profile") return snapshot.profile_config || {};
  if (scope === "session") return snapshot.session_config || {};
  return snapshot.settings;
}

function fieldDirty(snapshot: ConfigSnapshot, drafts: Record<string, string>, field: ConfigField, _scope: SettingsScope, _profile: string) {
  return stringify(readPath(snapshot.settings, field.path)) !== (drafts[field.path] || "");
}

function readPath(source: Record<string, unknown>, path: string): unknown {
  return path.split(".").reduce<unknown>((current, part) => current && typeof current === "object" ? (current as Record<string, unknown>)[part] : undefined, source);
}

function stringify(value: unknown) {
  if (value === undefined || value === null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "boolean" || typeof value === "number") return String(value);
  return JSON.stringify(value);
}

function parseDraft(value: string | undefined, type: string): unknown {
  const text = (value || "").trim();
  if (type === "boolean") return text === "true";
  if (type.startsWith("integer")) return text ? Number.parseInt(text, 10) : null;
  if (type === "number") return text ? Number.parseFloat(text) : 0;
  if (type === "array") return text ? JSON.parse(text) : [];
  if (type === "object" || type.includes("null")) return text ? JSON.parse(text) : type.includes("null") ? null : {};
  return value || "";
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}
