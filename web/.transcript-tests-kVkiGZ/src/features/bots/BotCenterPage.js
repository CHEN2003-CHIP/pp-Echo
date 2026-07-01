"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.BotCenterPage = BotCenterPage;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
const lucide_react_1 = require("lucide-react");
const api_1 = require("../../api");
const tabs = [
    { id: "overview", label: "Overview" },
    { id: "events", label: "Events" },
    { id: "sessions", label: "Sessions" },
    { id: "trace", label: "Trace" },
    { id: "config", label: "Config" },
    { id: "security", label: "Security" },
    { id: "logs", label: "Logs" }
];
function BotCenterPage() {
    const [bots, setBots] = (0, react_1.useState)([]);
    const [selectedId, setSelectedId] = (0, react_1.useState)("");
    const [detail, setDetail] = (0, react_1.useState)(null);
    const [capabilities, setCapabilities] = (0, react_1.useState)(null);
    const [tab, setTab] = (0, react_1.useState)("overview");
    const [query, setQuery] = (0, react_1.useState)("");
    const [filter, setFilter] = (0, react_1.useState)("all");
    const [publicUrl, setPublicUrl] = (0, react_1.useState)("");
    const [busy, setBusy] = (0, react_1.useState)("");
    const [notice, setNotice] = (0, react_1.useState)("");
    const [loading, setLoading] = (0, react_1.useState)(false);
    (0, react_1.useEffect)(() => {
        refresh().catch((error) => setNotice(errorMessage(error)));
    }, []);
    (0, react_1.useEffect)(() => {
        if (!selectedId)
            return;
        loadDetail(selectedId).catch((error) => setNotice(errorMessage(error)));
    }, [selectedId]);
    (0, react_1.useEffect)(() => {
        if (!selectedId || !detail)
            return;
        const lastEventId = String(detail.events.length ? detail.events[detail.events.length - 1]?.event_id || "" : "");
        const timer = window.setInterval(() => {
            api_1.api.botEvents(selectedId, lastEventId).then((payload) => {
                if (!payload.events.length)
                    return;
                setDetail((current) => current ? { ...current, events: [...current.events, ...payload.events] } : current);
            }).catch((error) => setNotice(errorMessage(error)));
        }, 3000);
        return () => window.clearInterval(timer);
    }, [selectedId, detail?.events]);
    const filteredBots = (0, react_1.useMemo)(() => {
        const text = query.trim().toLowerCase();
        return bots.filter((bot) => {
            const haystack = `${bot.name} ${bot.platform} ${bot.type} ${bot.status_text} ${bot.agent_state || ""} ${bot.bot_state} ${bot.ingress_state} ${bot.qq_state || ""}`.toLowerCase();
            return matchesBotFilter(bot, filter) && (!text || haystack.includes(text));
        });
    }, [bots, query, filter]);
    async function refresh() {
        setLoading(true);
        try {
            const [payload, inventory] = await Promise.all([api_1.api.bots(), api_1.api.capabilityConfig()]);
            setBots(payload.bots);
            setCapabilities(inventory);
            if (selectedId)
                await loadDetail(selectedId);
        }
        finally {
            setLoading(false);
        }
    }
    async function loadDetail(botId) {
        const payload = await api_1.api.botDetail(botId);
        setDetail(payload);
        setPublicUrl(payload.status.public_url || "");
    }
    function openDetail(botId) {
        setSelectedId(botId);
        setTab("overview");
    }
    function closeDetail() {
        setSelectedId("");
        setDetail(null);
    }
    async function action(botId, kind) {
        setBusy(`${kind}:${botId}`);
        setNotice("");
        try {
            const payload = kind === "start" ? await api_1.api.startBot(botId) : await api_1.api.stopBot(botId);
            await refresh();
            if (selectedId === botId)
                setDetail(payload);
        }
        catch (error) {
            setNotice(errorMessage(error));
        }
        finally {
            setBusy("");
        }
    }
    async function savePublicUrl() {
        if (!selectedId)
            return;
        setBusy(`url:${selectedId}`);
        setNotice("");
        try {
            const payload = await api_1.api.setBotPublicUrl(selectedId, publicUrl);
            setDetail(payload);
            await refresh();
            setNotice("Public URL saved.");
        }
        catch (error) {
            setNotice(errorMessage(error));
        }
        finally {
            setBusy("");
        }
    }
    async function testVerify() {
        if (!selectedId)
            return;
        setBusy(`verify:${selectedId}`);
        setNotice("");
        try {
            await api_1.api.testBotWebhookVerify(selectedId);
            await loadDetail(selectedId);
            setNotice("Webhook verification simulation completed.");
        }
        catch (error) {
            setNotice(errorMessage(error));
        }
        finally {
            setBusy("");
        }
    }
    async function copyWebhook() {
        const value = detail?.webhook_url || detail?.status.webhook_url || "";
        if (!value)
            return;
        await navigator.clipboard.writeText(value);
        setNotice("Webhook URL copied.");
    }
    return ((0, jsx_runtime_1.jsxs)("section", { className: "bot-center", children: [(0, jsx_runtime_1.jsxs)("div", { className: "bot-list-head", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("h2", { children: "Bots" }), (0, jsx_runtime_1.jsx)("p", { children: "Manage QQBot and external message gateways that can safely trigger pp-Echo runs." })] }), (0, jsx_runtime_1.jsxs)("div", { className: "bot-head-actions", children: [(0, jsx_runtime_1.jsxs)("button", { disabled: true, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Bot, { size: 15 }), " Add Bot"] }), (0, jsx_runtime_1.jsxs)("button", { onClick: () => refresh(), disabled: loading, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.RefreshCw, { size: 15 }), " Refresh"] })] })] }), (0, jsx_runtime_1.jsxs)("div", { className: "bot-toolbar", children: [(0, jsx_runtime_1.jsxs)("label", { className: "bot-search", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Search, { size: 14 }), (0, jsx_runtime_1.jsx)("input", { value: query, onChange: (event) => setQuery(event.target.value), placeholder: "Search name, platform, state" })] }), (0, jsx_runtime_1.jsx)("div", { className: "bot-filter-row", children: ["all", "running", "waiting", "error", "disabled"].map((item) => ((0, jsx_runtime_1.jsx)("button", { className: filter === item ? "active" : "", onClick: () => setFilter(item), type: "button", children: filterLabel(item) }, item))) })] }), notice ? (0, jsx_runtime_1.jsx)("div", { className: "bot-notice", children: notice }) : null, (0, jsx_runtime_1.jsxs)("div", { className: "bot-workspace", children: [(0, jsx_runtime_1.jsxs)("div", { className: "bot-card-list", children: [loading ? Array.from({ length: 6 }).map((_, index) => (0, jsx_runtime_1.jsx)("div", { className: "bot-card skeleton" }, index)) : null, !loading && filteredBots.map((bot) => ((0, jsx_runtime_1.jsxs)("article", { className: selectedId === bot.id ? "bot-card active" : "bot-card", onClick: () => openDetail(bot.id), children: [(0, jsx_runtime_1.jsxs)("div", { className: "bot-card-top", children: [(0, jsx_runtime_1.jsxs)("div", { className: "bot-card-status", children: [(0, jsx_runtime_1.jsx)("span", { className: `bot-dot ${stateTone(bot)}` }), (0, jsx_runtime_1.jsx)("span", { className: "bot-chip", children: platformLabel(bot.platform) }), (0, jsx_runtime_1.jsx)("span", { className: "bot-chip subtle", children: bot.process_state || bot.bot_state || "idle" })] }), (0, jsx_runtime_1.jsx)("button", { "aria-label": "View details", type: "button", children: (0, jsx_runtime_1.jsx)(lucide_react_1.ChevronRight, { size: 15 }) })] }), (0, jsx_runtime_1.jsxs)("div", { className: "bot-card-title", children: [(0, jsx_runtime_1.jsx)("span", { children: bot.type }), (0, jsx_runtime_1.jsx)("h3", { children: bot.name }), (0, jsx_runtime_1.jsx)("small", { children: bot.status_text || bot.bot_state || "Ready" })] }), (0, jsx_runtime_1.jsx)("p", { children: bot.description || bot.status_text || "No description yet." }), (0, jsx_runtime_1.jsxs)("div", { className: "bot-mini-status", children: [(0, jsx_runtime_1.jsx)("span", { children: bot.desired_state || (bot.enabled ? "enabled" : "disabled") }), (0, jsx_runtime_1.jsxs)("span", { children: ["Agent: ", bot.agent_state || bot.bot_state] }), (0, jsx_runtime_1.jsxs)("span", { children: ["Ingress: ", bot.ingress_state] }), (0, jsx_runtime_1.jsxs)("span", { children: ["QQ: ", bot.qq_state || (bot.configured ? "configured" : "not configured")] }), (0, jsx_runtime_1.jsxs)("span", { children: ["Runs: ", bot.still_running_count || 0] }), (0, jsx_runtime_1.jsxs)("span", { children: ["Queue: ", bot.queued_count || 0] })] }), (0, jsx_runtime_1.jsxs)("div", { className: "bot-card-footer", children: [(0, jsx_runtime_1.jsx)("small", { children: bot.last_event_at || bot.last_message_at || "No recent event" }), (0, jsx_runtime_1.jsxs)("div", { className: "bot-card-actions", onClick: (event) => event.stopPropagation(), children: [(0, jsx_runtime_1.jsxs)("button", { onClick: () => action(bot.id, "start"), disabled: busy === `start:${bot.id}`, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Play, { size: 14 }), " Start"] }), (0, jsx_runtime_1.jsxs)("button", { onClick: () => action(bot.id, "stop"), disabled: busy === `stop:${bot.id}`, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Square, { size: 13 }), " Stop"] }), (0, jsx_runtime_1.jsx)("button", { onClick: () => openDetail(bot.id), type: "button", children: "Details" })] })] })] }, bot.id))), !loading && bots.length === 0 ? (0, jsx_runtime_1.jsxs)("div", { className: "bot-empty", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Bot, { size: 22 }), " No bots configured."] }) : null, !loading && bots.length > 0 && filteredBots.length === 0 ? (0, jsx_runtime_1.jsxs)("div", { className: "bot-empty", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Search, { size: 22 }), " No bots match this search."] }) : null] }), detail ? ((0, jsx_runtime_1.jsx)("div", { className: "bot-drawer-backdrop", onClick: closeDetail, children: (0, jsx_runtime_1.jsxs)("aside", { className: "bot-detail-panel", onClick: (event) => event.stopPropagation(), children: [(0, jsx_runtime_1.jsxs)("div", { className: "bot-detail-head", children: [(0, jsx_runtime_1.jsxs)("div", { className: "bot-title", children: [(0, jsx_runtime_1.jsx)("span", { className: "bot-avatar", children: platformLabel(detail.status.platform) }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("h2", { children: detail.status.name }), (0, jsx_runtime_1.jsxs)("p", { children: [detail.status.platform, " / ", detail.status.type] })] })] }), (0, jsx_runtime_1.jsx)("button", { className: "icon-button", onClick: closeDetail, type: "button", title: "Close details", children: (0, jsx_runtime_1.jsx)(lucide_react_1.X, { size: 15 }) })] }), (0, jsx_runtime_1.jsxs)("div", { className: "bot-detail-actions", children: [(0, jsx_runtime_1.jsxs)("button", { onClick: () => action(detail.status.bot_id, "start"), disabled: Boolean(busy), children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Play, { size: 15 }), " Start"] }), (0, jsx_runtime_1.jsxs)("button", { onClick: () => action(detail.status.bot_id, "stop"), disabled: Boolean(busy), children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Square, { size: 14 }), " Stop"] }), (0, jsx_runtime_1.jsxs)("button", { onClick: () => loadDetail(detail.status.bot_id), disabled: Boolean(busy), children: [(0, jsx_runtime_1.jsx)(lucide_react_1.RefreshCw, { size: 15 }), " Reload"] })] }), (0, jsx_runtime_1.jsx)("div", { className: "bot-tabs", children: tabs.map((item) => ((0, jsx_runtime_1.jsx)("button", { className: tab === item.id ? "active" : "", onClick: () => setTab(item.id), children: item.label }, item.id))) }), (0, jsx_runtime_1.jsxs)("div", { className: "bot-detail-scroll", children: [tab === "overview" ? (0, jsx_runtime_1.jsx)(Overview, { detail: detail, capabilities: capabilities }) : null, tab === "events" ? (0, jsx_runtime_1.jsx)(Events, { detail: detail }) : null, tab === "sessions" ? (0, jsx_runtime_1.jsx)(Sessions, { detail: detail }) : null, tab === "trace" ? (0, jsx_runtime_1.jsx)(Trace, { detail: detail }) : null, tab === "config" ? ((0, jsx_runtime_1.jsx)(ConfigPanel, { detail: detail, publicUrl: publicUrl, setPublicUrl: setPublicUrl, onSavePublicUrl: savePublicUrl, onCopyWebhook: copyWebhook, onTestVerify: testVerify, busy: Boolean(busy) })) : null, tab === "security" ? (0, jsx_runtime_1.jsx)(Security, { detail: detail }) : null, tab === "logs" ? (0, jsx_runtime_1.jsx)(Logs, { detail: detail }) : null] })] }) })) : null] })] }));
}
function Overview({ detail, capabilities }) {
    const s = detail.status;
    const governance = connectorCapabilitySummary(capabilities, s.bot_id);
    return ((0, jsx_runtime_1.jsxs)("div", { className: "bot-detail-grid", children: [(0, jsx_runtime_1.jsx)(Info, { label: "Bot ID", value: s.bot_id }), (0, jsx_runtime_1.jsx)(Info, { label: "Platform", value: s.platform }), (0, jsx_runtime_1.jsx)(Info, { label: "Type", value: s.type }), (0, jsx_runtime_1.jsx)(Info, { label: "Process State", value: s.process_state }), (0, jsx_runtime_1.jsx)(Info, { label: "Desired State", value: s.desired_state || (s.enabled ? "enabled" : "disabled") }), (0, jsx_runtime_1.jsx)(Info, { label: "Agent State", value: s.agent_state || s.bot_state }), (0, jsx_runtime_1.jsx)(Info, { label: "Bot State", value: s.bot_state }), (0, jsx_runtime_1.jsx)(Info, { label: "Ingress State", value: s.ingress_state }), (0, jsx_runtime_1.jsx)(Info, { label: "QQ State", value: s.qq_state || (s.configured ? "configured" : "not configured") }), (0, jsx_runtime_1.jsx)(Info, { label: "Local URL", value: s.local_url || "" }), (0, jsx_runtime_1.jsx)(Info, { label: "Public URL", value: s.public_url || "" }), (0, jsx_runtime_1.jsx)(Info, { label: "Webhook URL", value: s.webhook_url || detail.webhook_url || "" }), (0, jsx_runtime_1.jsx)(Info, { label: "Group Trigger", value: String(detail.config.routing?.group_trigger || "") }), (0, jsx_runtime_1.jsx)(Info, { label: "Started At", value: s.started_at || "" }), (0, jsx_runtime_1.jsx)(Info, { label: "Last Heartbeat", value: s.last_heartbeat_at || "" }), (0, jsx_runtime_1.jsx)(Info, { label: "Last Message", value: s.last_message_at || "" }), (0, jsx_runtime_1.jsx)(Info, { label: "Last Reply", value: s.last_reply_at || "" }), (0, jsx_runtime_1.jsx)(Info, { label: "Last Run", value: s.last_run_at || "" }), (0, jsx_runtime_1.jsx)(Info, { label: "In-flight Runs", value: String(s.still_running_count || 0) }), (0, jsx_runtime_1.jsx)(Info, { label: "Queued", value: String(s.queued_count || 0) }), (0, jsx_runtime_1.jsx)(Info, { label: "Capability Status", value: governance.status }), (0, jsx_runtime_1.jsx)(Info, { label: "Capability Risk", value: governance.risk }), (0, jsx_runtime_1.jsx)(Info, { label: "Last Error", value: s.last_error || "" }), (0, jsx_runtime_1.jsx)(Info, { label: "Bot Path", value: s.bot_path, wide: true }), (0, jsx_runtime_1.jsxs)("div", { className: "bot-security-note", children: ["Capability governance: ", governance.summary] })] }));
}
function Events({ detail }) {
    return (0, jsx_runtime_1.jsx)(JsonList, { items: detail.events, empty: "No events yet." });
}
function Sessions({ detail }) {
    const sessions = unique(detail.runs.map((run) => String(run.session_id || "")).filter(Boolean));
    return (0, jsx_runtime_1.jsx)(JsonList, { items: sessions.map((session_id) => ({ session_id })), empty: "No Bot-triggered sessions yet." });
}
function Trace({ detail }) {
    return (0, jsx_runtime_1.jsx)(JsonList, { items: detail.runs.length ? detail.runs : detail.traces, empty: "No Bot run or trace index yet." });
}
function ConfigPanel({ detail, publicUrl, setPublicUrl, onSavePublicUrl, onCopyWebhook, onTestVerify, busy }) {
    const routing = detail.config.routing || {};
    const ingress = detail.config.ingress || {};
    return ((0, jsx_runtime_1.jsxs)("div", { className: "bot-form", children: [(0, jsx_runtime_1.jsxs)("label", { children: [(0, jsx_runtime_1.jsx)("span", { children: "Public URL" }), (0, jsx_runtime_1.jsx)("input", { value: publicUrl, onChange: (event) => setPublicUrl(event.target.value), placeholder: "https://example.tunnel.dev" })] }), (0, jsx_runtime_1.jsxs)("div", { className: "bot-form-actions", children: [(0, jsx_runtime_1.jsxs)("button", { onClick: onSavePublicUrl, disabled: busy, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Globe2, { size: 15 }), " Save Public URL"] }), (0, jsx_runtime_1.jsxs)("button", { onClick: onCopyWebhook, disabled: !detail.webhook_url, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Copy, { size: 15 }), " Copy Webhook URL"] }), (0, jsx_runtime_1.jsxs)("button", { onClick: onTestVerify, disabled: busy, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.TestTube2, { size: 15 }), " Test Verify"] })] }), (0, jsx_runtime_1.jsxs)("div", { className: "bot-detail-grid", children: [(0, jsx_runtime_1.jsx)(Info, { label: "Enabled", value: String(detail.config.enabled) }), (0, jsx_runtime_1.jsx)(Info, { label: "Webhook URL", value: detail.webhook_url || "", wide: true }), (0, jsx_runtime_1.jsx)(Info, { label: "Group Trigger", value: String(routing.group_trigger || "") }), (0, jsx_runtime_1.jsx)(Info, { label: "Private Chat", value: String(routing.private_chat ?? "") }), (0, jsx_runtime_1.jsx)(Info, { label: "Session Policy", value: String(routing.default_session_policy || "") }), (0, jsx_runtime_1.jsx)(Info, { label: "Tunnel Provider", value: String(ingress.tunnel?.provider || "manual") })] })] }));
}
function Security({ detail }) {
    const security = detail.config.security || {};
    return ((0, jsx_runtime_1.jsxs)("div", { className: "bot-detail-grid", children: [(0, jsx_runtime_1.jsx)(Info, { label: "Require Approval", value: String(security.require_approval_for_tools ?? true) }), (0, jsx_runtime_1.jsx)(Info, { label: "Allow Shell", value: String(security.allow_shell ?? false) }), (0, jsx_runtime_1.jsx)(Info, { label: "Allowed Users", value: arrayValue(security.allowed_user_ids), wide: true }), (0, jsx_runtime_1.jsx)(Info, { label: "Allowed Groups", value: arrayValue(security.allowed_group_ids), wide: true }), (0, jsx_runtime_1.jsx)(Info, { label: "Workspace Roots", value: arrayValue(security.allowed_workspace_roots), wide: true }), (0, jsx_runtime_1.jsx)("div", { className: "bot-security-note", children: "External bots can trigger local Agent runs. Keep allowlists, group triggers, workspace roots, and tool approval policies tight." })] }));
}
function Logs({ detail }) {
    return ((0, jsx_runtime_1.jsxs)("div", { className: "bot-logs", children: [(0, jsx_runtime_1.jsx)("pre", { children: (detail.logs.bot || []).join("\n") || "No bot.log entries." }), (0, jsx_runtime_1.jsx)("pre", { children: (detail.logs.error || []).join("\n") || "No error.log entries." })] }));
}
function Info({ label, value, wide = false }) {
    return ((0, jsx_runtime_1.jsxs)("div", { className: wide ? "bot-info wide" : "bot-info", children: [(0, jsx_runtime_1.jsx)("span", { children: label }), (0, jsx_runtime_1.jsx)("strong", { children: value || "Not set" })] }));
}
function JsonList({ items, empty }) {
    if (!items.length)
        return (0, jsx_runtime_1.jsx)("div", { className: "bot-empty", children: empty });
    return ((0, jsx_runtime_1.jsx)("div", { className: "bot-event-list", children: items.map((item, index) => ((0, jsx_runtime_1.jsxs)("details", { children: [(0, jsx_runtime_1.jsxs)("summary", { children: [(0, jsx_runtime_1.jsx)("strong", { children: String(item.type || item.status || item.session_id || item.run_id || "item") }), (0, jsx_runtime_1.jsx)("span", { children: String(item.summary || item.timestamp || item.started_at || "") })] }), (0, jsx_runtime_1.jsx)("pre", { children: JSON.stringify(maskSensitive(item), null, 2) })] }, String(item.event_id || item.run_id || item.session_id || index)))) }));
}
function matchesBotFilter(bot, filter) {
    if (filter === "all")
        return true;
    if (filter === "error")
        return bot.process_state === "crashed" || bot.bot_state === "error" || Boolean(bot.last_error);
    if (filter === "disabled")
        return !bot.enabled || bot.desired_state === "stopped";
    if (filter === "waiting")
        return bot.bot_state === "waiting_approval" || bot.queued_count || bot.agent_state === "waiting_approval";
    if (filter === "running")
        return bot.process_state === "running" || bot.bot_state === "running_agent" || Boolean(bot.still_running_count);
    return true;
}
function filterLabel(filter) {
    if (filter === "all")
        return "All";
    if (filter === "running")
        return "Running";
    if (filter === "waiting")
        return "Waiting";
    if (filter === "error")
        return "Error";
    if (filter === "disabled")
        return "Disabled";
    return filter;
}
function stateTone(bot) {
    if (bot.process_state === "crashed" || bot.bot_state === "error")
        return "danger";
    if (bot.bot_state === "running_agent" || bot.bot_state === "waiting_approval")
        return "warning";
    if (bot.process_state === "running")
        return "success";
    return "muted";
}
function platformLabel(platform) {
    if (platform.toLowerCase() === "qq")
        return "QQ";
    return platform.slice(0, 2).toUpperCase();
}
function arrayValue(value) {
    return Array.isArray(value) && value.length ? value.join(", ") : "Not set";
}
function unique(values) {
    return Array.from(new Set(values));
}
function connectorCapabilitySummary(inventory, botId) {
    const items = inventory?.capabilities?.items || [];
    const item = items.find((candidate) => candidate.kind === "connector" && (candidate.name === botId || candidate.id === `connector.${botId}`));
    if (!item)
        return { status: "Not listed", risk: "-", summary: "connector capability is not present in the current catalog snapshot." };
    const tags = Array.isArray(item.tags) ? item.tags.join(", ") : "";
    return {
        status: String(item.status || "unknown"),
        risk: String(item.risk_level || "unknown"),
        summary: `${String(item.id || item.name)} from ${String(item.source_kind || "connector")}${tags ? ` (${tags})` : ""}.`
    };
}
function errorMessage(error) {
    return error instanceof Error ? error.message : String(error);
}
function maskSensitive(value, seen = new WeakSet()) {
    if (!value || typeof value !== "object")
        return value;
    if (seen.has(value))
        return "[Circular]";
    seen.add(value);
    if (Array.isArray(value))
        return value.map((item) => maskSensitive(item, seen));
    const output = {};
    Object.entries(value).forEach(([key, item]) => {
        output[key] = /(api[_-]?key|secret|token|password|authorization|signature|app[_-]?secret)/i.test(key)
            ? "[masked]"
            : maskSensitive(item, seen);
    });
    return output;
}
