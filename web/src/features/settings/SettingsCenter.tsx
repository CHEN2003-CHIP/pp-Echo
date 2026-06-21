import { useEffect, useMemo, useState } from "react";
import { Bot, Brain, Copy, Database, Eye, EyeOff, KeyRound, RefreshCw, RotateCcw, Save, Search, Settings, ShieldCheck, SlidersHorizontal, Wifi, Wrench } from "lucide-react";
import { api, type ConfigField, type ConfigSnapshot, type ModelConnectivityResult, type ModelProviderPreset } from "../../api";

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
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [providers, setProviders] = useState<ModelProviderPreset[]>([]);
  const [modelCheck, setModelCheck] = useState<ModelConnectivityResult | null>(null);

  useEffect(() => {
    load().catch((err) => setError(errorMessage(err)));
  }, [sessionId]);

  useEffect(() => {
    setCategory(normalizeCategory(initialCategory));
  }, [initialCategory]);

  useEffect(() => {
    if (!snapshot) return;
    setDrafts(buildDrafts(snapshot, scope, profileDraft));
    setJsonDraft(JSON.stringify(readScopeConfig(snapshot, scope), null, 2));
    setFieldErrors({});
  }, [snapshot, scope, profileDraft]);

  async function load() {
    const [payload, providerPayload] = await Promise.all([
      api.config(sessionId || undefined),
      api.modelProviders().catch(() => ({ providers: [] as ModelProviderPreset[] }))
    ]);
    setSnapshot(payload);
    setProviders(providerPayload.providers);
    setProfileDraft(payload.active_profile || payload.profiles[0] || "default");
    setError("");
    setNotice("");
    setModelCheck(null);
  }

  async function applyChanges() {
    if (!snapshot) return;
    const dirty = fields.filter((field) => fieldDirty(snapshot, drafts, field, scope));
    if (!dirty.length) return;
    if (scope === "session" && !sessionId) {
      setError("Open a session before applying session overrides.");
      return;
    }
    const nextFieldErrors: Record<string, string> = {};
    setSaving(true);
    setError("");
    setNotice("");
    try {
      let updated = snapshot;
      let baseHash = snapshot.config_hash;
      let pendingNextTurn = false;
      for (const field of dirty) {
        if (scope === "session" && !field.session_override) {
          nextFieldErrors[field.path] = "This setting does not support session override.";
          continue;
        }
        let value: unknown;
        try {
          value = parseDraft(drafts[field.path], field.type);
        } catch (err) {
          nextFieldErrors[field.path] = errorMessage(err);
          continue;
        }
        if (scope === "session" && sessionId && field.path === "model.model") {
          const response = await api.setSessionModel(sessionId, String(value));
          updated = response;
          pendingNextTurn = Boolean(response.pending_next_turn);
        } else if (scope === "session" && sessionId) {
          updated = await api.sessionConfigSet(sessionId, field.path, value);
        } else if (scope === "profile") {
          updated = await api.configProfileSet(profileDraft || "default", field.path, value, baseHash, sessionId || undefined);
        } else {
          updated = await api.configSet(field.path, value, baseHash);
        }
        baseHash = updated.config_hash;
      }
      setFieldErrors(nextFieldErrors);
      if (Object.keys(nextFieldErrors).length) {
        setError("Some settings need attention before they can be applied.");
      } else {
        setSnapshot(updated);
        setNotice(pendingNextTurn ? "Settings saved. Model changes apply on the next turn." : "Settings saved.");
        onSaved?.();
      }
    } catch (err) {
      setError(formatConfigError(err));
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
      setNotice("JSON patch saved.");
      onSaved?.();
    } catch (err) {
      setError(formatConfigError(err));
    } finally {
      setSaving(false);
    }
  }

  function revert() {
    if (!snapshot) return;
    setDrafts(buildDrafts(snapshot, scope, profileDraft));
    setJsonDraft(JSON.stringify(readScopeConfig(snapshot, scope), null, 2));
    setFieldErrors({});
    setError("");
    setNotice("");
    setModelCheck(null);
  }

  function applyProviderPreset(providerId: string) {
    const preset = providers.find((item) => item.id === providerId);
    if (!preset) return;
    const nextModel = preset.recommended_models[0] || "";
    setDrafts((current) => ({
      ...current,
      "provider.name": preset.id,
      "provider.base_url": preset.default_base_url,
      "provider.api_key_env": preset.default_api_key_env,
      "model.provider": preset.id,
      "model.model": nextModel || current["model.model"] || ""
    }));
    setModelCheck(null);
  }

  async function testModelConnection() {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const result = await api.modelTest(
        {
          name: drafts["provider.name"] || "",
          base_url: drafts["provider.base_url"] || "",
          api_key_env: drafts["provider.api_key_env"] || ""
        },
        {
          provider: drafts["model.provider"] || drafts["provider.name"] || "",
          model: drafts["model.model"] || "",
          temperature: Number.parseFloat(drafts["model.temperature"] || "0.2"),
          max_tokens: drafts["model.max_tokens"] ? Number.parseInt(drafts["model.max_tokens"], 10) : null,
          enable_thinking: drafts["model.enable_thinking"] === "true"
        }
      );
      setModelCheck(result);
      if (result.status === "ok") setNotice(result.message);
      if (result.status !== "ok") setError(`${result.message}${result.safe_detail ? ` ${result.safe_detail}` : ""}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  const fields = snapshot?.schema.fields || [];
  const visibleFields = useMemo(() => fields.filter((field) => categoryMatches(field, category) && matchesSettingSearch(field, query)), [fields, category, query]);
  const dirtyCount = snapshot ? fields.filter((field) => fieldDirty(snapshot, drafts, field, scope)).length : 0;
  const selectedCategory = categories.find((item) => item.id === category) || categories[0];
  const CategoryIcon = selectedCategory.icon;

  return (
    <section className="settings-center-page">
      <aside className="settings-center-nav">
        <div className="settings-center-title">
          <small>SETTINGS</small>
          <h2>Hot Config</h2>
          <p>{snapshot ? `${effectLabel(snapshot.reload_policy)} / ${snapshot.active_profile || "default"}` : "Loading configuration"}</p>
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
            <small>HOT CONFIG</small>
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
          <div><span>Scope</span><strong>{scope}</strong></div>
          <div><span>Effect</span><strong>{effectLabel(snapshot?.reload_policy || "hot")}</strong></div>
        </div>
        {snapshot?.pending_effects?.length ? <div className="settings-pending">{snapshot.pending_effects.slice(0, 8).map((item) => <span key={item}>{item}</span>)}</div> : null}
        {error ? <div className="settings-error">{error}</div> : null}
        {notice ? <div className="settings-success">{notice}</div> : null}
        {category === "providers" ? (
          <section className="model-provider-panel">
            <div className="model-provider-head">
              <div>
                <strong>Provider quick switch</strong>
                <span>Select a preset to fill the editable fields below, then apply when ready.</span>
              </div>
              <button onClick={testModelConnection} disabled={saving || !drafts["model.model"]} type="button"><Wifi size={14} /> Test model connection</button>
            </div>
            <div className="model-provider-grid">
              {providers.map((provider) => (
                <button
                  className={drafts["provider.name"] === provider.id ? "active" : ""}
                  key={provider.id}
                  onClick={() => applyProviderPreset(provider.id)}
                  type="button"
                >
                  <strong>{provider.label}</strong>
                  <span>{provider.protocol}</span>
                  <small>{provider.recommended_models[0] || "custom model"}</small>
                </button>
              ))}
            </div>
            {modelCheck ? (
              <div className={`model-test-result ${modelCheck.status}`}>
                <strong>{modelCheck.status.toUpperCase()} · {modelCheck.provider} / {modelCheck.model}</strong>
                <span>{modelCheck.message}{modelCheck.latency_ms ? ` · ${modelCheck.latency_ms}ms` : ""}</span>
                {modelCheck.safe_detail ? <small>{modelCheck.safe_detail}</small> : null}
              </div>
            ) : null}
          </section>
        ) : null}

        {category === "advanced" ? (
          <section className="settings-json-editor product">
            <div>
              <strong>Advanced JSON</strong>
              <span>Project-level patch editor. Prefer cards above for hot config changes.</span>
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
                const dirty = snapshot ? fieldDirty(snapshot, drafts, field, scope) : false;
                const secret = isSecretField(field);
                const disabled = scope === "session" && !field.session_override;
                return (
                  <article className={settingCardClass(field, dirty, disabled)} key={field.path}>
                    <div className="setting-card-copy">
                      <strong>{fieldLabel(field.path)}</strong>
                      <span>{field.description || "No description."}</span>
                      <code>{field.path}</code>
                      <div className="setting-card-meta">
                        <em>{effectLabel(field.reload_policy)}</em>
                        <em>{snapshot?.source_map[field.path] || "default"}</em>
                        <em>{dirty ? "Changed" : "Synced"}</em>
                        {field.session_override ? <em>Session</em> : null}
                      </div>
                    </div>
                    <div className="setting-card-control">
                      {renderInput(field, drafts[field.path] || "", (value) => {
                        setDrafts((current) => ({ ...current, [field.path]: value }));
                        setFieldErrors((current) => ({ ...current, [field.path]: "" }));
                      }, Boolean(revealed[field.path]), disabled)}
                      <div className="setting-card-actions">
                        {secret ? (
                          <button onClick={() => setRevealed((current) => ({ ...current, [field.path]: !current[field.path] }))} type="button">
                            {revealed[field.path] ? <EyeOff size={14} /> : <Eye size={14} />}
                            {revealed[field.path] ? "Hide" : "Show"}
                          </button>
                        ) : null}
                        {secret ? (
                          <button onClick={() => navigator.clipboard.writeText(drafts[field.path] || "")} type="button">
                            <Copy size={14} /> Copy
                          </button>
                        ) : null}
                      </div>
                      {disabled ? <small>Session override is not supported for this field.</small> : <small>{fieldErrors[field.path] || (dirty ? "Ready to apply" : "Synced")}</small>}
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

function renderInput(field: ConfigField, value: string, onChange: (value: string) => void, revealed = false, disabled = false) {
  if (field.type === "boolean") {
    return (
      <div className="setting-switch" aria-disabled={disabled}>
        <button className={value !== "true" ? "active" : ""} onClick={() => onChange("false")} disabled={disabled} type="button">Off</button>
        <button className={value === "true" ? "active" : ""} onClick={() => onChange("true")} disabled={disabled} type="button">On</button>
      </div>
    );
  }
  if (field.options?.length) {
    return (
      <select value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled}>
        {field.options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    );
  }
  if (field.type === "array" || field.type === "object" || field.type.includes("null")) {
    return <textarea value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled} rows={3} />;
  }
  return (
    <input
      type={isSecretField(field) && !revealed ? "password" : field.type === "number" || field.type.startsWith("integer") ? "number" : "text"}
      min={field.minimum ?? undefined}
      max={field.maximum ?? undefined}
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

function settingCardClass(field: ConfigField, dirty: boolean, disabled: boolean) {
  const classes = ["settings-product-field"];
  if (dirty) classes.push("dirty");
  if (disabled) classes.push("disabled");
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

function buildDrafts(snapshot: ConfigSnapshot, scope: SettingsScope, _profile: string) {
  const source = readScopeConfig(snapshot, scope);
  const drafts: Record<string, string> = {};
  snapshot.schema.fields.forEach((field) => {
    drafts[field.path] = stringify(readPath(source, field.path));
  });
  return drafts;
}

function readScopeConfig(snapshot: ConfigSnapshot, scope: SettingsScope) {
  if (scope === "profile") return snapshot.profile_config || {};
  if (scope === "session") return snapshot.session_config || {};
  return snapshot.project_config || snapshot.settings;
}

function fieldDirty(snapshot: ConfigSnapshot, drafts: Record<string, string>, field: ConfigField, scope: SettingsScope) {
  return stringify(readPath(readScopeConfig(snapshot, scope), field.path)) !== (drafts[field.path] || "");
}

function readPath(source: Record<string, unknown>, path: string): unknown {
  return path.split(".").reduce<unknown>((current, part) => current && typeof current === "object" ? (current as Record<string, unknown>)[part] : undefined, source);
}

function stringify(value: unknown) {
  if (value === undefined || value === null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "boolean" || typeof value === "number") return String(value);
  return JSON.stringify(value, null, 2);
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

function effectLabel(value: string) {
  if (value === "next_turn") return "Next turn";
  if (value === "rebuild_runtime") return "Rebuild runtime";
  if (value === "restart_required") return "Restart required";
  return "Hot";
}

function formatConfigError(error: unknown) {
  const message = errorMessage(error);
  if (message.includes("Config was changed by another writer") || message.includes("expected_hash")) {
    return "Config changed somewhere else. Reload to merge before applying again.";
  }
  return message;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}
