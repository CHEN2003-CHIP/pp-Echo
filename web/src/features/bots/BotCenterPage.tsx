import { useEffect, useMemo, useState } from "react";
import { Bot, ChevronRight, Copy, Globe2, Play, RefreshCw, Search, Square, TestTube2, X } from "lucide-react";
import { api, BotDetail, BotSummary, CapabilityInventory } from "../../api";

type DetailTab = "overview" | "events" | "sessions" | "trace" | "config" | "security" | "logs";
type BotFilter = "all" | "running" | "waiting" | "error" | "disabled";

const tabs: Array<{ id: DetailTab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "events", label: "Events" },
  { id: "sessions", label: "Sessions" },
  { id: "trace", label: "Trace" },
  { id: "config", label: "Config" },
  { id: "security", label: "Security" },
  { id: "logs", label: "Logs" }
];

export function BotCenterPage() {
  const [bots, setBots] = useState<BotSummary[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<BotDetail | null>(null);
  const [capabilities, setCapabilities] = useState<CapabilityInventory | null>(null);
  const [tab, setTab] = useState<DetailTab>("overview");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<BotFilter>("all");
  const [publicUrl, setPublicUrl] = useState("");
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    refresh().catch((error) => setNotice(errorMessage(error)));
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    loadDetail(selectedId).catch((error) => setNotice(errorMessage(error)));
  }, [selectedId]);

  useEffect(() => {
    if (!selectedId || !detail) return;
    const lastEventId = String(detail.events.length ? detail.events[detail.events.length - 1]?.event_id || "" : "");
    const timer = window.setInterval(() => {
      api.botEvents(selectedId, lastEventId).then((payload) => {
        if (!payload.events.length) return;
        setDetail((current) => current ? { ...current, events: [...current.events, ...payload.events] } : current);
      }).catch((error) => setNotice(errorMessage(error)));
    }, 3000);
    return () => window.clearInterval(timer);
  }, [selectedId, detail?.events]);

  const filteredBots = useMemo(() => {
    const text = query.trim().toLowerCase();
    return bots.filter((bot) => {
      const haystack = `${bot.name} ${bot.platform} ${bot.type} ${bot.status_text} ${bot.agent_state || ""} ${bot.bot_state} ${bot.ingress_state} ${bot.qq_state || ""}`.toLowerCase();
      return matchesBotFilter(bot, filter) && (!text || haystack.includes(text));
    });
  }, [bots, query, filter]);

  async function refresh() {
    setLoading(true);
    try {
      const [payload, inventory] = await Promise.all([api.bots(), api.capabilityConfig()]);
      setBots(payload.bots);
      setCapabilities(inventory);
      if (selectedId) await loadDetail(selectedId);
    } finally {
      setLoading(false);
    }
  }

  async function loadDetail(botId: string) {
    const payload = await api.botDetail(botId);
    setDetail(payload);
    setPublicUrl(payload.status.public_url || "");
  }

  function openDetail(botId: string) {
    setSelectedId(botId);
    setTab("overview");
  }

  function closeDetail() {
    setSelectedId("");
    setDetail(null);
  }

  async function action(botId: string, kind: "start" | "stop") {
    setBusy(`${kind}:${botId}`);
    setNotice("");
    try {
      const payload = kind === "start" ? await api.startBot(botId) : await api.stopBot(botId);
      await refresh();
      if (selectedId === botId) setDetail(payload);
    } catch (error) {
      setNotice(errorMessage(error));
    } finally {
      setBusy("");
    }
  }

  async function savePublicUrl() {
    if (!selectedId) return;
    setBusy(`url:${selectedId}`);
    setNotice("");
    try {
      const payload = await api.setBotPublicUrl(selectedId, publicUrl);
      setDetail(payload);
      await refresh();
      setNotice("Public URL saved.");
    } catch (error) {
      setNotice(errorMessage(error));
    } finally {
      setBusy("");
    }
  }

  async function testVerify() {
    if (!selectedId) return;
    setBusy(`verify:${selectedId}`);
    setNotice("");
    try {
      await api.testBotWebhookVerify(selectedId);
      await loadDetail(selectedId);
      setNotice("Webhook verification simulation completed.");
    } catch (error) {
      setNotice(errorMessage(error));
    } finally {
      setBusy("");
    }
  }

  async function copyWebhook() {
    const value = detail?.webhook_url || detail?.status.webhook_url || "";
    if (!value) return;
    await navigator.clipboard.writeText(value);
    setNotice("Webhook URL copied.");
  }

  return (
    <section className="bot-center">
      <div className="bot-list-head">
        <div>
          <h2>Bots</h2>
          <p>Manage QQBot and external message gateways that can safely trigger pp-Echo runs.</p>
        </div>
        <div className="bot-head-actions">
          <button disabled><Bot size={15} /> Add Bot</button>
          <button onClick={() => refresh()} disabled={loading}><RefreshCw size={15} /> Refresh</button>
        </div>
      </div>

      <div className="bot-toolbar">
        <label className="bot-search">
          <Search size={14} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search name, platform, state" />
        </label>
        <div className="bot-filter-row">
          {(["all", "running", "waiting", "error", "disabled"] as BotFilter[]).map((item) => (
            <button key={item} className={filter === item ? "active" : ""} onClick={() => setFilter(item)} type="button">{filterLabel(item)}</button>
          ))}
        </div>
      </div>

      {notice ? <div className="bot-notice">{notice}</div> : null}

      <div className="bot-workspace">
        <div className="bot-card-list">
          {loading ? Array.from({ length: 6 }).map((_, index) => <div className="bot-card skeleton" key={index} />) : null}
          {!loading && filteredBots.map((bot) => (
            <article key={bot.id} className={selectedId === bot.id ? "bot-card active" : "bot-card"} onClick={() => openDetail(bot.id)}>
              <div className="bot-card-top">
                <div className="bot-card-status">
                  <span className={`bot-dot ${stateTone(bot)}`} />
                  <span className="bot-chip">{platformLabel(bot.platform)}</span>
                  <span className="bot-chip subtle">{bot.process_state || bot.bot_state || "idle"}</span>
                </div>
                <button aria-label="View details" type="button"><ChevronRight size={15} /></button>
              </div>

              <div className="bot-card-title">
                <span>{bot.type}</span>
                <h3>{bot.name}</h3>
                <small>{bot.status_text || bot.bot_state || "Ready"}</small>
              </div>

              <p>{bot.description || bot.status_text || "No description yet."}</p>

              <div className="bot-mini-status">
                <span>{bot.desired_state || (bot.enabled ? "enabled" : "disabled")}</span>
                <span>Agent: {bot.agent_state || bot.bot_state}</span>
                <span>Ingress: {bot.ingress_state}</span>
                <span>QQ: {bot.qq_state || (bot.configured ? "configured" : "not configured")}</span>
                <span>Runs: {bot.still_running_count || 0}</span>
                <span>Queue: {bot.queued_count || 0}</span>
              </div>

              <div className="bot-card-footer">
                <small>{bot.last_event_at || bot.last_message_at || "No recent event"}</small>
                <div className="bot-card-actions" onClick={(event) => event.stopPropagation()}>
                  <button onClick={() => action(bot.id, "start")} disabled={busy === `start:${bot.id}`}>
                    <Play size={14} /> Start
                  </button>
                  <button onClick={() => action(bot.id, "stop")} disabled={busy === `stop:${bot.id}`}>
                    <Square size={13} /> Stop
                  </button>
                  <button onClick={() => openDetail(bot.id)} type="button">Details</button>
                </div>
              </div>
            </article>
          ))}
          {!loading && bots.length === 0 ? <div className="bot-empty"><Bot size={22} /> No bots configured.</div> : null}
          {!loading && bots.length > 0 && filteredBots.length === 0 ? <div className="bot-empty"><Search size={22} /> No bots match this search.</div> : null}
        </div>

        {detail ? (
          <div className="bot-drawer-backdrop" onClick={closeDetail}>
            <aside className="bot-detail-panel" onClick={(event) => event.stopPropagation()}>
              <div className="bot-detail-head">
                <div className="bot-title">
                  <span className="bot-avatar">{platformLabel(detail.status.platform)}</span>
                  <div>
                    <h2>{detail.status.name}</h2>
                    <p>{detail.status.platform} / {detail.status.type}</p>
                  </div>
                </div>
                <button className="icon-button" onClick={closeDetail} type="button" title="Close details"><X size={15} /></button>
              </div>
              <div className="bot-detail-actions">
                <button onClick={() => action(detail.status.bot_id, "start")} disabled={Boolean(busy)}><Play size={15} /> Start</button>
                <button onClick={() => action(detail.status.bot_id, "stop")} disabled={Boolean(busy)}><Square size={14} /> Stop</button>
                <button onClick={() => loadDetail(detail.status.bot_id)} disabled={Boolean(busy)}><RefreshCw size={15} /> Reload</button>
              </div>
              <div className="bot-tabs">
                {tabs.map((item) => (
                  <button key={item.id} className={tab === item.id ? "active" : ""} onClick={() => setTab(item.id)}>{item.label}</button>
                ))}
              </div>
              <div className="bot-detail-scroll">
                {tab === "overview" ? <Overview detail={detail} capabilities={capabilities} /> : null}
                {tab === "events" ? <Events detail={detail} /> : null}
                {tab === "sessions" ? <Sessions detail={detail} /> : null}
                {tab === "trace" ? <Trace detail={detail} /> : null}
                {tab === "config" ? (
                  <ConfigPanel detail={detail} publicUrl={publicUrl} setPublicUrl={setPublicUrl} onSavePublicUrl={savePublicUrl} onCopyWebhook={copyWebhook} onTestVerify={testVerify} busy={Boolean(busy)} />
                ) : null}
                {tab === "security" ? <Security detail={detail} /> : null}
                {tab === "logs" ? <Logs detail={detail} /> : null}
              </div>
            </aside>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function Overview({ detail, capabilities }: { detail: BotDetail; capabilities: CapabilityInventory | null }) {
  const s = detail.status;
  const governance = connectorCapabilitySummary(capabilities, s.bot_id);
  return (
    <div className="bot-detail-grid">
      <Info label="Bot ID" value={s.bot_id} />
      <Info label="Platform" value={s.platform} />
      <Info label="Type" value={s.type} />
      <Info label="Process State" value={s.process_state} />
      <Info label="Desired State" value={s.desired_state || (s.enabled ? "enabled" : "disabled")} />
      <Info label="Agent State" value={s.agent_state || s.bot_state} />
      <Info label="Bot State" value={s.bot_state} />
      <Info label="Ingress State" value={s.ingress_state} />
      <Info label="QQ State" value={s.qq_state || (s.configured ? "configured" : "not configured")} />
      <Info label="Local URL" value={s.local_url || ""} />
      <Info label="Public URL" value={s.public_url || ""} />
      <Info label="Webhook URL" value={s.webhook_url || detail.webhook_url || ""} />
      <Info label="Group Trigger" value={String(detail.config.routing?.group_trigger || "")} />
      <Info label="Started At" value={s.started_at || ""} />
      <Info label="Last Heartbeat" value={s.last_heartbeat_at || ""} />
      <Info label="Last Message" value={s.last_message_at || ""} />
      <Info label="Last Reply" value={s.last_reply_at || ""} />
      <Info label="Last Run" value={s.last_run_at || ""} />
      <Info label="In-flight Runs" value={String(s.still_running_count || 0)} />
      <Info label="Queued" value={String(s.queued_count || 0)} />
      <Info label="Capability Status" value={governance.status} />
      <Info label="Capability Risk" value={governance.risk} />
      <Info label="Last Error" value={s.last_error || ""} />
      <Info label="Bot Path" value={s.bot_path} wide />
      <div className="bot-security-note">
        Capability governance: {governance.summary}
      </div>
    </div>
  );
}

function Events({ detail }: { detail: BotDetail }) {
  return <JsonList items={detail.events} empty="No events yet." />;
}

function Sessions({ detail }: { detail: BotDetail }) {
  const sessions = unique(detail.runs.map((run) => String(run.session_id || "")).filter(Boolean));
  return <JsonList items={sessions.map((session_id) => ({ session_id }))} empty="No Bot-triggered sessions yet." />;
}

function Trace({ detail }: { detail: BotDetail }) {
  return <JsonList items={detail.runs.length ? detail.runs : detail.traces} empty="No Bot run or trace index yet." />;
}

function ConfigPanel({
  detail,
  publicUrl,
  setPublicUrl,
  onSavePublicUrl,
  onCopyWebhook,
  onTestVerify,
  busy
}: {
  detail: BotDetail;
  publicUrl: string;
  setPublicUrl: (value: string) => void;
  onSavePublicUrl: () => void;
  onCopyWebhook: () => void;
  onTestVerify: () => void;
  busy: boolean;
}) {
  const routing = detail.config.routing || {};
  const ingress = detail.config.ingress || {};
  return (
    <div className="bot-form">
      <label>
        <span>Public URL</span>
        <input value={publicUrl} onChange={(event) => setPublicUrl(event.target.value)} placeholder="https://example.tunnel.dev" />
      </label>
      <div className="bot-form-actions">
        <button onClick={onSavePublicUrl} disabled={busy}><Globe2 size={15} /> Save Public URL</button>
        <button onClick={onCopyWebhook} disabled={!detail.webhook_url}><Copy size={15} /> Copy Webhook URL</button>
        <button onClick={onTestVerify} disabled={busy}><TestTube2 size={15} /> Test Verify</button>
      </div>
      <div className="bot-detail-grid">
        <Info label="Enabled" value={String(detail.config.enabled)} />
        <Info label="Webhook URL" value={detail.webhook_url || ""} wide />
        <Info label="Group Trigger" value={String(routing.group_trigger || "")} />
        <Info label="Private Chat" value={String(routing.private_chat ?? "")} />
        <Info label="Session Policy" value={String(routing.default_session_policy || "")} />
        <Info label="Tunnel Provider" value={String((ingress.tunnel as Record<string, unknown> | undefined)?.provider || "manual")} />
      </div>
    </div>
  );
}

function Security({ detail }: { detail: BotDetail }) {
  const security = detail.config.security || {};
  return (
    <div className="bot-detail-grid">
      <Info label="Require Approval" value={String(security.require_approval_for_tools ?? true)} />
      <Info label="Allow Shell" value={String(security.allow_shell ?? false)} />
      <Info label="Allowed Users" value={arrayValue(security.allowed_user_ids)} wide />
      <Info label="Allowed Groups" value={arrayValue(security.allowed_group_ids)} wide />
      <Info label="Workspace Roots" value={arrayValue(security.allowed_workspace_roots)} wide />
      <div className="bot-security-note">
        External bots can trigger local Agent runs. Keep allowlists, group triggers, workspace roots, and tool approval policies tight.
      </div>
    </div>
  );
}

function Logs({ detail }: { detail: BotDetail }) {
  return (
    <div className="bot-logs">
      <pre>{(detail.logs.bot || []).join("\n") || "No bot.log entries."}</pre>
      <pre>{(detail.logs.error || []).join("\n") || "No error.log entries."}</pre>
    </div>
  );
}

function Info({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={wide ? "bot-info wide" : "bot-info"}>
      <span>{label}</span>
      <strong>{value || "Not set"}</strong>
    </div>
  );
}

function JsonList({ items, empty }: { items: Array<Record<string, unknown>>; empty: string }) {
  if (!items.length) return <div className="bot-empty">{empty}</div>;
  return (
    <div className="bot-event-list">
      {items.map((item, index) => (
        <details key={String(item.event_id || item.run_id || item.session_id || index)}>
          <summary>
            <strong>{String(item.type || item.status || item.session_id || item.run_id || "item")}</strong>
            <span>{String(item.summary || item.timestamp || item.started_at || "")}</span>
          </summary>
          <pre>{JSON.stringify(maskSensitive(item), null, 2)}</pre>
        </details>
      ))}
    </div>
  );
}

function matchesBotFilter(bot: BotSummary, filter: BotFilter) {
  if (filter === "all") return true;
  if (filter === "error") return bot.process_state === "crashed" || bot.bot_state === "error" || Boolean(bot.last_error);
  if (filter === "disabled") return !bot.enabled || bot.desired_state === "stopped";
  if (filter === "waiting") return bot.bot_state === "waiting_approval" || bot.queued_count || bot.agent_state === "waiting_approval";
  if (filter === "running") return bot.process_state === "running" || bot.bot_state === "running_agent" || Boolean(bot.still_running_count);
  return true;
}

function filterLabel(filter: BotFilter) {
  if (filter === "all") return "All";
  if (filter === "running") return "Running";
  if (filter === "waiting") return "Waiting";
  if (filter === "error") return "Error";
  if (filter === "disabled") return "Disabled";
  return filter;
}

function stateTone(bot: BotSummary) {
  if (bot.process_state === "crashed" || bot.bot_state === "error") return "danger";
  if (bot.bot_state === "running_agent" || bot.bot_state === "waiting_approval") return "warning";
  if (bot.process_state === "running") return "success";
  return "muted";
}

function platformLabel(platform: string) {
  if (platform.toLowerCase() === "qq") return "QQ";
  return platform.slice(0, 2).toUpperCase();
}

function arrayValue(value: unknown) {
  return Array.isArray(value) && value.length ? value.join(", ") : "Not set";
}

function unique(values: string[]) {
  return Array.from(new Set(values));
}

function connectorCapabilitySummary(inventory: CapabilityInventory | null, botId: string) {
  const items = inventory?.capabilities?.items || [];
  const item = items.find((candidate) => candidate.kind === "connector" && (candidate.name === botId || candidate.id === `connector.${botId}`));
  if (!item) return { status: "Not listed", risk: "-", summary: "connector capability is not present in the current catalog snapshot." };
  const tags = Array.isArray(item.tags) ? item.tags.join(", ") : "";
  return {
    status: String(item.status || "unknown"),
    risk: String(item.risk_level || "unknown"),
    summary: `${String(item.id || item.name)} from ${String(item.source_kind || "connector")}${tags ? ` (${tags})` : ""}.`
  };
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function maskSensitive(value: unknown, seen = new WeakSet<object>()): unknown {
  if (!value || typeof value !== "object") return value;
  if (seen.has(value)) return "[Circular]";
  seen.add(value);
  if (Array.isArray(value)) return value.map((item) => maskSensitive(item, seen));
  const output: Record<string, unknown> = {};
  Object.entries(value as Record<string, unknown>).forEach(([key, item]) => {
    output[key] = /(api[_-]?key|secret|token|password|authorization|signature|app[_-]?secret)/i.test(key)
      ? "[masked]"
      : maskSensitive(item, seen);
  });
  return output;
}
