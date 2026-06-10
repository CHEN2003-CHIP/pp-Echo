import { useEffect, useMemo, useState } from "react";
import { Bot, Check, ChevronLeft, Copy, Globe2, Play, RefreshCw, Square, TestTube2 } from "lucide-react";
import { api, BotDetail, BotSummary } from "../../api";

type DetailTab = "overview" | "events" | "sessions" | "trace" | "config" | "security" | "logs";

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
  const [tab, setTab] = useState<DetailTab>("overview");
  const [publicUrl, setPublicUrl] = useState("");
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    refresh().catch((error) => setNotice(errorMessage(error)));
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    loadDetail(selectedId).catch((error) => setNotice(errorMessage(error)));
  }, [selectedId]);

  const selectedBot = useMemo(() => bots.find((item) => item.id === selectedId), [bots, selectedId]);

  async function refresh() {
    const payload = await api.bots();
    setBots(payload.bots);
    if (selectedId) await loadDetail(selectedId);
  }

  async function loadDetail(botId: string) {
    const payload = await api.botDetail(botId);
    setDetail(payload);
    setPublicUrl(payload.status.public_url || "");
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

  if (selectedId && detail) {
    return (
      <section className="bot-center bot-detail-page">
        <div className="bot-detail-head">
          <button className="bot-back" onClick={() => setSelectedId("")}>
            <ChevronLeft size={16} /> Bots
          </button>
          <div className="bot-title">
            <span className="bot-avatar">{platformLabel(detail.status.platform)}</span>
            <div>
              <h2>{detail.status.name}</h2>
              <p>{detail.status.platform} / {detail.status.type}</p>
            </div>
          </div>
          <div className="bot-detail-actions">
            <button onClick={() => action(detail.status.bot_id, "start")} disabled={Boolean(busy)}>
              <Play size={15} /> Start
            </button>
            <button onClick={() => action(detail.status.bot_id, "stop")} disabled={Boolean(busy)}>
              <Square size={14} /> Stop
            </button>
            <button onClick={() => loadDetail(detail.status.bot_id)} disabled={Boolean(busy)}>
              <RefreshCw size={15} />
            </button>
          </div>
        </div>

        {notice ? <div className="bot-notice">{notice}</div> : null}

        <div className="bot-tabs">
          {tabs.map((item) => (
            <button key={item.id} className={tab === item.id ? "active" : ""} onClick={() => setTab(item.id)}>{item.label}</button>
          ))}
        </div>

        {tab === "overview" ? <Overview detail={detail} /> : null}
        {tab === "events" ? <Events detail={detail} /> : null}
        {tab === "sessions" ? <Sessions detail={detail} /> : null}
        {tab === "trace" ? <Trace detail={detail} /> : null}
        {tab === "config" ? (
          <ConfigPanel
            detail={detail}
            publicUrl={publicUrl}
            setPublicUrl={setPublicUrl}
            onSavePublicUrl={savePublicUrl}
            onCopyWebhook={copyWebhook}
            onTestVerify={testVerify}
            busy={Boolean(busy)}
          />
        ) : null}
        {tab === "security" ? <Security detail={detail} /> : null}
        {tab === "logs" ? <Logs detail={detail} /> : null}
      </section>
    );
  }

  return (
    <section className="bot-center">
      <div className="bot-list-head">
        <div>
          <h2>Bots</h2>
          <p>Gateway entries that can safely trigger local pp-Echo runs.</p>
        </div>
        <button onClick={() => refresh()}><RefreshCw size={15} /> Refresh</button>
      </div>
      {notice ? <div className="bot-notice">{notice}</div> : null}
      <div className="bot-card-list">
        {bots.map((bot) => (
          <article key={bot.id} className="bot-card" onClick={() => setSelectedId(bot.id)}>
            <div className="bot-avatar">{platformLabel(bot.platform)}</div>
            <div className="bot-card-main">
              <div className="bot-card-title">
                <h3>{bot.name}</h3>
                <span className="bot-chip">{bot.type}</span>
              </div>
              <p>{bot.status_text}</p>
            </div>
            <div className="bot-card-state">
              <span className={`bot-dot ${stateTone(bot)}`} />
              <strong>{bot.process_state}</strong>
            </div>
            <div className="bot-card-actions" onClick={(event) => event.stopPropagation()}>
              <button onClick={() => action(bot.id, "start")} disabled={busy === `start:${bot.id}`}>
                <Play size={14} /> Start
              </button>
              <button onClick={() => action(bot.id, "stop")} disabled={busy === `stop:${bot.id}`}>
                <Square size={13} /> Stop
              </button>
            </div>
          </article>
        ))}
        {bots.length === 0 ? <div className="bot-empty"><Bot size={22} /> No bots configured.</div> : null}
      </div>
    </section>
  );
}

function Overview({ detail }: { detail: BotDetail }) {
  const s = detail.status;
  return (
    <div className="bot-detail-grid">
      <Info label="Bot ID" value={s.bot_id} />
      <Info label="Platform" value={s.platform} />
      <Info label="Type" value={s.type} />
      <Info label="Process State" value={s.process_state} />
      <Info label="Bot State" value={s.bot_state} />
      <Info label="Ingress State" value={s.ingress_state} />
      <Info label="Local URL" value={s.local_url || ""} />
      <Info label="Public URL" value={s.public_url || ""} />
      <Info label="Webhook URL" value={s.webhook_url || detail.webhook_url || ""} />
      <Info label="Group Trigger" value={String(detail.config.routing?.group_trigger || "")} />
      <Info label="Started At" value={s.started_at || ""} />
      <Info label="Last Heartbeat" value={s.last_heartbeat_at || ""} />
      <Info label="Last Message" value={s.last_message_at || ""} />
      <Info label="Last Reply" value={s.last_reply_at || ""} />
      <Info label="Last Error" value={s.last_error || ""} />
      <Info label="Bot Path" value={s.bot_path} wide />
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
          <pre>{JSON.stringify(item, null, 2)}</pre>
        </details>
      ))}
    </div>
  );
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

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}
