"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.SettingsCenter = SettingsCenter;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
const lucide_react_1 = require("lucide-react");
const api_1 = require("../../api");
const categories = [
    { id: "general", label: "General", description: "Workspace defaults and everyday behavior.", icon: lucide_react_1.Settings },
    { id: "providers", label: "Models & Providers", description: "Model, provider, and endpoint configuration.", icon: lucide_react_1.KeyRound },
    { id: "tools", label: "Tools & Capabilities", description: "Tool policy, built-in capabilities, and approvals.", icon: lucide_react_1.Wrench },
    { id: "agent", label: "Agent Behavior", description: "Planning, subagents, checkpoints, and compaction.", icon: lucide_react_1.Brain },
    { id: "resources", label: "Integrations", description: "MCP, skills, plugins, and bot gateway settings.", icon: lucide_react_1.Bot },
    { id: "memory", label: "Memory & Learning", description: "Memory files, search, learning, and storage.", icon: lucide_react_1.Database },
    { id: "security", label: "Security", description: "External access, shell risk, and approval safeguards.", icon: lucide_react_1.ShieldCheck },
    { id: "advanced", label: "Advanced", description: "Raw JSON patching and diagnostics.", icon: lucide_react_1.SlidersHorizontal }
];
function SettingsCenter({ sessionId, initialCategory = "general", onSaved, onOpenCapabilities }) {
    const [snapshot, setSnapshot] = (0, react_1.useState)(null);
    const [category, setCategory] = (0, react_1.useState)(normalizeCategory(initialCategory));
    const [scope, setScope] = (0, react_1.useState)(sessionId ? "session" : "project");
    const [profileDraft, setProfileDraft] = (0, react_1.useState)("");
    const [drafts, setDrafts] = (0, react_1.useState)({});
    const [jsonDraft, setJsonDraft] = (0, react_1.useState)("");
    const [saving, setSaving] = (0, react_1.useState)(false);
    const [notice, setNotice] = (0, react_1.useState)("");
    const [error, setError] = (0, react_1.useState)("");
    const [query, setQuery] = (0, react_1.useState)("");
    const [revealed, setRevealed] = (0, react_1.useState)({});
    const [fieldErrors, setFieldErrors] = (0, react_1.useState)({});
    const [providers, setProviders] = (0, react_1.useState)([]);
    const [modelCheck, setModelCheck] = (0, react_1.useState)(null);
    const [sandboxStatus, setSandboxStatus] = (0, react_1.useState)(null);
    (0, react_1.useEffect)(() => {
        load().catch((err) => setError(errorMessage(err)));
    }, [sessionId]);
    (0, react_1.useEffect)(() => {
        setCategory(normalizeCategory(initialCategory));
    }, [initialCategory]);
    (0, react_1.useEffect)(() => {
        if (!snapshot)
            return;
        setDrafts(buildDrafts(snapshot, scope, profileDraft));
        setJsonDraft(JSON.stringify(readScopeConfig(snapshot, scope), null, 2));
        setFieldErrors({});
    }, [snapshot, scope, profileDraft]);
    async function load() {
        const [payload, providerPayload, sandboxPayload] = await Promise.all([
            api_1.api.config(sessionId || undefined),
            api_1.api.modelProviders().catch(() => ({ providers: [] })),
            api_1.api.sandboxStatus(sessionId || undefined).catch(() => null)
        ]);
        setSnapshot(payload);
        setProviders(providerPayload.providers);
        setSandboxStatus(sandboxPayload);
        setProfileDraft(payload.active_profile || payload.profiles[0] || "default");
        setError("");
        setNotice("");
        setModelCheck(null);
    }
    async function applyChanges() {
        if (!snapshot)
            return;
        const dirty = fields.filter((field) => fieldDirty(snapshot, drafts, field, scope));
        if (!dirty.length)
            return;
        if (scope === "session" && !sessionId) {
            setError("Open a session before applying session overrides.");
            return;
        }
        const nextFieldErrors = {};
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
                let value;
                try {
                    value = parseDraft(drafts[field.path], field.type);
                }
                catch (err) {
                    nextFieldErrors[field.path] = errorMessage(err);
                    continue;
                }
                if (scope === "session" && sessionId && field.path === "model.model") {
                    const response = await api_1.api.setSessionModel(sessionId, String(value));
                    updated = response;
                    pendingNextTurn = Boolean(response.pending_next_turn);
                }
                else if (scope === "session" && sessionId) {
                    updated = await api_1.api.sessionConfigSet(sessionId, field.path, value);
                }
                else if (scope === "profile") {
                    updated = await api_1.api.configProfileSet(profileDraft || "default", field.path, value, baseHash, sessionId || undefined);
                }
                else {
                    updated = await api_1.api.configSet(field.path, value, baseHash);
                }
                baseHash = updated.config_hash;
            }
            setFieldErrors(nextFieldErrors);
            if (Object.keys(nextFieldErrors).length) {
                setError("Some settings need attention before they can be applied.");
            }
            else {
                setSnapshot(updated);
                setNotice(pendingNextTurn ? "Settings saved. Model changes apply on the next turn." : "Settings saved.");
                onSaved?.();
            }
        }
        catch (err) {
            setError(formatConfigError(err));
        }
        finally {
            setSaving(false);
        }
    }
    async function applyJson() {
        if (!snapshot)
            return;
        setSaving(true);
        setError("");
        try {
            const parsed = JSON.parse(jsonDraft || "{}");
            const updated = await api_1.api.configPatch(parsed, snapshot.config_hash);
            setSnapshot(updated);
            setNotice("JSON patch saved.");
            onSaved?.();
        }
        catch (err) {
            setError(formatConfigError(err));
        }
        finally {
            setSaving(false);
        }
    }
    function revert() {
        if (!snapshot)
            return;
        setDrafts(buildDrafts(snapshot, scope, profileDraft));
        setJsonDraft(JSON.stringify(readScopeConfig(snapshot, scope), null, 2));
        setFieldErrors({});
        setError("");
        setNotice("");
        setModelCheck(null);
    }
    function applyProviderPreset(providerId) {
        const preset = providers.find((item) => item.id === providerId);
        if (!preset)
            return;
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
            const result = await api_1.api.modelTest({
                name: drafts["provider.name"] || "",
                base_url: drafts["provider.base_url"] || "",
                api_key_env: drafts["provider.api_key_env"] || ""
            }, {
                provider: drafts["model.provider"] || drafts["provider.name"] || "",
                model: drafts["model.model"] || "",
                temperature: Number.parseFloat(drafts["model.temperature"] || "0.2"),
                max_tokens: drafts["model.max_tokens"] ? Number.parseInt(drafts["model.max_tokens"], 10) : null,
                enable_thinking: drafts["model.enable_thinking"] === "true"
            });
            setModelCheck(result);
            if (result.status === "ok")
                setNotice(result.message);
            if (result.status !== "ok")
                setError(`${result.message}${result.safe_detail ? ` ${result.safe_detail}` : ""}`);
        }
        catch (err) {
            setError(errorMessage(err));
        }
        finally {
            setSaving(false);
        }
    }
    const fields = snapshot?.schema.fields || [];
    const visibleFields = (0, react_1.useMemo)(() => fields.filter((field) => categoryMatches(field, category) && matchesSettingSearch(field, query)), [fields, category, query]);
    const dirtyCount = snapshot ? fields.filter((field) => fieldDirty(snapshot, drafts, field, scope)).length : 0;
    const selectedCategory = categories.find((item) => item.id === category) || categories[0];
    const CategoryIcon = selectedCategory.icon;
    return ((0, jsx_runtime_1.jsxs)("section", { className: "settings-center-page", children: [(0, jsx_runtime_1.jsxs)("aside", { className: "settings-center-nav", children: [(0, jsx_runtime_1.jsxs)("div", { className: "settings-center-title", children: [(0, jsx_runtime_1.jsx)("small", { children: "SETTINGS" }), (0, jsx_runtime_1.jsx)("h2", { children: "Hot Config" }), (0, jsx_runtime_1.jsx)("p", { children: snapshot ? `${effectLabel(snapshot.reload_policy)} / ${snapshot.active_profile || "default"}` : "Loading configuration" })] }), (0, jsx_runtime_1.jsxs)("div", { className: "settings-scope-card", children: [(0, jsx_runtime_1.jsx)("span", { children: "Scope" }), (0, jsx_runtime_1.jsxs)("div", { className: "segmented-control", children: [(0, jsx_runtime_1.jsx)("button", { className: scope === "project" ? "active" : "", onClick: () => setScope("project"), type: "button", children: "Project" }), (0, jsx_runtime_1.jsx)("button", { className: scope === "profile" ? "active" : "", onClick: () => setScope("profile"), type: "button", children: "Profile" }), (0, jsx_runtime_1.jsx)("button", { className: scope === "session" ? "active" : "", onClick: () => setScope("session"), disabled: !sessionId, type: "button", children: "Session" })] }), scope === "profile" ? (0, jsx_runtime_1.jsx)("input", { value: profileDraft, onChange: (event) => setProfileDraft(event.target.value), placeholder: "profile name" }) : null] }), categories.map((item) => ((0, jsx_runtime_1.jsxs)("button", { className: category === item.id ? "active" : "", onClick: () => setCategory(item.id), type: "button", children: [(0, jsx_runtime_1.jsx)(item.icon, { size: 15 }), (0, jsx_runtime_1.jsx)("span", { children: item.label })] }, item.id)))] }), (0, jsx_runtime_1.jsxs)("main", { className: "settings-center-main", children: [(0, jsx_runtime_1.jsxs)("header", { className: "settings-center-header", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("small", { children: "HOT CONFIG" }), (0, jsx_runtime_1.jsx)("h2", { children: "Manage models, permissions, memory, web access, and Agent behavior." })] }), (0, jsx_runtime_1.jsxs)("div", { className: "settings-center-actions", children: [category === "resources" ? (0, jsx_runtime_1.jsx)("button", { onClick: onOpenCapabilities, type: "button", children: "Open Capability Workbench" }) : null, (0, jsx_runtime_1.jsxs)("button", { onClick: () => load(), disabled: saving, type: "button", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.RefreshCw, { size: 14 }), " Reload"] })] })] }), (0, jsx_runtime_1.jsx)("div", { className: "settings-toolbar", children: (0, jsx_runtime_1.jsxs)("label", { className: "settings-search", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Search, { size: 14 }), (0, jsx_runtime_1.jsx)("input", { value: query, onChange: (event) => setQuery(event.target.value), placeholder: "Search settings" })] }) }), (0, jsx_runtime_1.jsxs)("div", { className: "settings-health-strip", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("span", { children: "Fields" }), (0, jsx_runtime_1.jsx)("strong", { children: visibleFields.length })] }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("span", { children: "Pending" }), (0, jsx_runtime_1.jsx)("strong", { children: dirtyCount })] }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("span", { children: "Scope" }), (0, jsx_runtime_1.jsx)("strong", { children: scope })] }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("span", { children: "Effect" }), (0, jsx_runtime_1.jsx)("strong", { children: effectLabel(snapshot?.reload_policy || "hot") })] })] }), snapshot?.pending_effects?.length ? (0, jsx_runtime_1.jsx)("div", { className: "settings-pending", children: snapshot.pending_effects.slice(0, 8).map((item) => (0, jsx_runtime_1.jsx)("span", { children: item }, item)) }) : null, error ? (0, jsx_runtime_1.jsx)("div", { className: "settings-error", children: error }) : null, notice ? (0, jsx_runtime_1.jsx)("div", { className: "settings-success", children: notice }) : null, category === "providers" ? ((0, jsx_runtime_1.jsxs)("section", { className: "model-provider-panel", children: [(0, jsx_runtime_1.jsxs)("div", { className: "model-provider-head", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("strong", { children: "Provider quick switch" }), (0, jsx_runtime_1.jsx)("span", { children: "Select a preset to fill the editable fields below, then apply when ready." })] }), (0, jsx_runtime_1.jsxs)("button", { onClick: testModelConnection, disabled: saving || !drafts["model.model"], type: "button", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Wifi, { size: 14 }), " Test model connection"] })] }), (0, jsx_runtime_1.jsx)("div", { className: "model-provider-grid", children: providers.map((provider) => ((0, jsx_runtime_1.jsxs)("button", { className: drafts["provider.name"] === provider.id ? "active" : "", onClick: () => applyProviderPreset(provider.id), type: "button", children: [(0, jsx_runtime_1.jsx)("strong", { children: provider.label }), (0, jsx_runtime_1.jsx)("span", { children: provider.protocol }), (0, jsx_runtime_1.jsx)("small", { children: provider.recommended_models[0] || "custom model" })] }, provider.id))) }), modelCheck ? ((0, jsx_runtime_1.jsxs)("div", { className: `model-test-result ${modelCheck.status}`, children: [(0, jsx_runtime_1.jsxs)("strong", { children: [modelCheck.status.toUpperCase(), " \u00B7 ", modelCheck.provider, " / ", modelCheck.model] }), (0, jsx_runtime_1.jsxs)("span", { children: [modelCheck.message, modelCheck.latency_ms ? ` · ${modelCheck.latency_ms}ms` : ""] }), modelCheck.safe_detail ? (0, jsx_runtime_1.jsx)("small", { children: modelCheck.safe_detail }) : null] })) : null] })) : null, category === "security" && sandboxStatus ? ((0, jsx_runtime_1.jsxs)("section", { className: `model-test-result ${sandboxStatus.ok ? "ok" : "warning"}`, children: [(0, jsx_runtime_1.jsxs)("strong", { children: ["Sandbox: ", sandboxStatus.backend, " / ", sandboxStatus.sandbox_isolation] }), (0, jsx_runtime_1.jsx)("span", { children: sandboxStatus.message }), (0, jsx_runtime_1.jsxs)("small", { children: ["image=", sandboxStatus.image, sandboxStatus.docker_found !== undefined ? ` | docker=${String(sandboxStatus.docker_found)}` : "", sandboxStatus.daemon_available !== undefined ? ` | daemon=${String(sandboxStatus.daemon_available)}` : "", sandboxStatus.image_available !== undefined ? ` | image=${String(sandboxStatus.image_available)}` : ""] }), !sandboxStatus.ok && sandboxStatus.install_url ? (0, jsx_runtime_1.jsx)("a", { href: sandboxStatus.install_url, target: "_blank", rel: "noreferrer", children: "Install Docker" }) : null, !sandboxStatus.ok && sandboxStatus.build_command ? (0, jsx_runtime_1.jsx)("code", { children: sandboxStatus.build_command }) : null] })) : null, category === "advanced" ? ((0, jsx_runtime_1.jsxs)("section", { className: "settings-json-editor product", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("strong", { children: "Advanced JSON" }), (0, jsx_runtime_1.jsx)("span", { children: "Project-level patch editor. Prefer cards above for hot config changes." })] }), (0, jsx_runtime_1.jsx)("textarea", { value: jsonDraft, onChange: (event) => setJsonDraft(event.target.value) }), (0, jsx_runtime_1.jsxs)("button", { onClick: applyJson, disabled: saving, type: "button", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Save, { size: 14 }), " Apply JSON"] })] })) : ((0, jsx_runtime_1.jsxs)("section", { className: "settings-group", children: [(0, jsx_runtime_1.jsxs)("div", { className: "settings-group-head", children: [(0, jsx_runtime_1.jsx)(CategoryIcon, { size: 16 }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("h3", { children: selectedCategory.label }), (0, jsx_runtime_1.jsx)("p", { children: selectedCategory.description })] })] }), (0, jsx_runtime_1.jsxs)("div", { className: "settings-field-grid", children: [visibleFields.map((field) => {
                                        const dirty = snapshot ? fieldDirty(snapshot, drafts, field, scope) : false;
                                        const secret = isSecretField(field);
                                        const disabled = scope === "session" && !field.session_override;
                                        return ((0, jsx_runtime_1.jsxs)("article", { className: settingCardClass(field, dirty, disabled), children: [(0, jsx_runtime_1.jsxs)("div", { className: "setting-card-copy", children: [(0, jsx_runtime_1.jsx)("strong", { children: fieldLabel(field.path) }), (0, jsx_runtime_1.jsx)("span", { children: field.description || "No description." }), (0, jsx_runtime_1.jsx)("code", { children: field.path }), (0, jsx_runtime_1.jsxs)("div", { className: "setting-card-meta", children: [(0, jsx_runtime_1.jsx)("em", { children: effectLabel(field.reload_policy) }), (0, jsx_runtime_1.jsx)("em", { children: snapshot?.source_map[field.path] || "default" }), (0, jsx_runtime_1.jsx)("em", { children: dirty ? "Changed" : "Synced" }), field.session_override ? (0, jsx_runtime_1.jsx)("em", { children: "Session" }) : null] })] }), (0, jsx_runtime_1.jsxs)("div", { className: "setting-card-control", children: [renderInput(field, drafts[field.path] || "", (value) => {
                                                            setDrafts((current) => ({ ...current, [field.path]: value }));
                                                            setFieldErrors((current) => ({ ...current, [field.path]: "" }));
                                                        }, Boolean(revealed[field.path]), disabled), (0, jsx_runtime_1.jsxs)("div", { className: "setting-card-actions", children: [secret ? ((0, jsx_runtime_1.jsxs)("button", { onClick: () => setRevealed((current) => ({ ...current, [field.path]: !current[field.path] })), type: "button", children: [revealed[field.path] ? (0, jsx_runtime_1.jsx)(lucide_react_1.EyeOff, { size: 14 }) : (0, jsx_runtime_1.jsx)(lucide_react_1.Eye, { size: 14 }), revealed[field.path] ? "Hide" : "Show"] })) : null, secret ? ((0, jsx_runtime_1.jsxs)("button", { onClick: () => navigator.clipboard.writeText(drafts[field.path] || ""), type: "button", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Copy, { size: 14 }), " Copy"] })) : null] }), disabled ? (0, jsx_runtime_1.jsx)("small", { children: "Session override is not supported for this field." }) : (0, jsx_runtime_1.jsx)("small", { children: fieldErrors[field.path] || (dirty ? "Ready to apply" : "Synced") })] })] }, field.path));
                                    }), snapshot && !visibleFields.length ? (0, jsx_runtime_1.jsx)("div", { className: "settings-empty", children: "No settings match this category or search." }) : null] })] }))] }), (0, jsx_runtime_1.jsxs)("footer", { className: "settings-center-footer", children: [(0, jsx_runtime_1.jsxs)("span", { children: [dirtyCount, " pending change", dirtyCount === 1 ? "" : "s"] }), (0, jsx_runtime_1.jsxs)("button", { onClick: revert, disabled: !dirtyCount || saving, type: "button", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.RotateCcw, { size: 14 }), " Revert"] }), (0, jsx_runtime_1.jsxs)("button", { className: "primary", onClick: applyChanges, disabled: !dirtyCount || saving || category === "advanced", type: "button", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Save, { size: 14 }), " ", saving ? "Saving" : "Apply"] })] })] }));
}
function normalizeCategory(value) {
    if (value === "model" || value === "browser_web")
        return "providers";
    if (value === "skills" || value === "plugins")
        return "resources";
    if (value === "subagents" || value === "storage" || value === "learning")
        return "agent";
    if (value === "tools")
        return "tools";
    if (value === "memory")
        return "memory";
    return categories.some((item) => item.id === value) ? value : "general";
}
function categoryMatches(field, category) {
    if (category === "general")
        return ["provider.base_url", "model.model", "tool_policy.confirm_high_risk_plan"].includes(field.path);
    if (category === "providers")
        return field.category === "model" || field.category === "browser_web" || field.path.startsWith("provider.");
    if (category === "tools")
        return field.category === "tools" || field.path.startsWith("tool_policy.") || field.path.startsWith("capabilities.builtin_tools");
    if (category === "agent")
        return ["subagents", "storage", "learning"].includes(field.category);
    if (category === "resources")
        return ["skills", "plugins"].includes(field.category) || field.path.startsWith("capabilities.mcp");
    if (category === "memory")
        return field.category === "memory" || field.path.includes("memory");
    if (category === "security")
        return field.path.includes("approval") || field.path.includes("shell") || field.path.includes("security") || field.path.startsWith("sandbox.");
    return false;
}
function renderInput(field, value, onChange, revealed = false, disabled = false) {
    if (field.type === "boolean") {
        return ((0, jsx_runtime_1.jsxs)("label", { className: "setting-checkbox", "aria-disabled": disabled, children: [(0, jsx_runtime_1.jsx)("input", { checked: value === "true", disabled: disabled, onChange: (event) => onChange(String(event.target.checked)), type: "checkbox" }), (0, jsx_runtime_1.jsx)("span", { children: value === "true" ? "Enabled" : "Disabled" })] }));
    }
    if (field.options?.length) {
        return ((0, jsx_runtime_1.jsx)("select", { value: value, onChange: (event) => onChange(event.target.value), disabled: disabled, children: field.options.map((option) => (0, jsx_runtime_1.jsx)("option", { value: option, children: option }, option)) }));
    }
    if (field.type === "array" || field.type === "object" || field.type.includes("null")) {
        return (0, jsx_runtime_1.jsx)("textarea", { value: value, onChange: (event) => onChange(event.target.value), disabled: disabled, rows: 3 });
    }
    return ((0, jsx_runtime_1.jsx)("input", { type: isSecretField(field) && !revealed ? "password" : field.type === "number" || field.type.startsWith("integer") ? "number" : "text", min: field.minimum ?? undefined, max: field.maximum ?? undefined, value: value, disabled: disabled, onChange: (event) => onChange(event.target.value) }));
}
function settingCardClass(field, dirty, disabled) {
    const classes = ["settings-product-field"];
    if (dirty)
        classes.push("dirty");
    if (disabled)
        classes.push("disabled");
    if (field.type === "array" || field.type === "object" || field.type.includes("null"))
        classes.push("wide");
    if (isDangerField(field))
        classes.push("danger");
    return classes.join(" ");
}
function fieldLabel(path) {
    return path
        .split(".")
        .slice(-2)
        .join(" ")
        .replace(/[_-]/g, " ")
        .replace(/\b\w/g, (char) => char.toUpperCase());
}
function matchesSettingSearch(field, query) {
    const text = query.trim().toLowerCase();
    if (!text)
        return true;
    return `${field.path} ${field.category} ${field.description || ""} ${field.type}`.toLowerCase().includes(text);
}
function isSecretField(field) {
    return /(api[_-]?key|secret|token|password|authorization|credential)/i.test(field.path);
}
function isDangerField(field) {
    return /(shell|delete|reset|danger|unrestricted|approval|write|filesystem)/i.test(field.path);
}
function buildDrafts(snapshot, scope, _profile) {
    const source = readScopeConfig(snapshot, scope);
    const drafts = {};
    snapshot.schema.fields.forEach((field) => {
        drafts[field.path] = stringify(readPath(source, field.path));
    });
    return drafts;
}
function readScopeConfig(snapshot, scope) {
    if (scope === "profile")
        return snapshot.profile_config || {};
    if (scope === "session")
        return snapshot.session_config || {};
    return snapshot.project_config || snapshot.settings;
}
function fieldDirty(snapshot, drafts, field, scope) {
    return stringify(readPath(readScopeConfig(snapshot, scope), field.path)) !== (drafts[field.path] || "");
}
function readPath(source, path) {
    return path.split(".").reduce((current, part) => current && typeof current === "object" ? current[part] : undefined, source);
}
function stringify(value) {
    if (value === undefined || value === null)
        return "";
    if (typeof value === "string")
        return value;
    if (typeof value === "boolean" || typeof value === "number")
        return String(value);
    return JSON.stringify(value, null, 2);
}
function parseDraft(value, type) {
    const text = (value || "").trim();
    if (type === "boolean")
        return text === "true";
    if (type.startsWith("integer"))
        return text ? Number.parseInt(text, 10) : null;
    if (type === "number")
        return text ? Number.parseFloat(text) : 0;
    if (type === "array")
        return text ? JSON.parse(text) : [];
    if (type === "object" || type.includes("null"))
        return text ? JSON.parse(text) : type.includes("null") ? null : {};
    return value || "";
}
function effectLabel(value) {
    if (value === "next_turn")
        return "Next turn";
    if (value === "rebuild_runtime")
        return "Rebuild runtime";
    if (value === "restart_required")
        return "Restart required";
    return "Hot";
}
function formatConfigError(error) {
    const message = errorMessage(error);
    if (message.includes("Config was changed by another writer") || message.includes("expected_hash")) {
        return "Config changed somewhere else. Reload to merge before applying again.";
    }
    return message;
}
function errorMessage(error) {
    return error instanceof Error ? error.message : String(error);
}
