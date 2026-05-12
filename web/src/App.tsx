import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  Bot,
  Boxes,
  Check,
  ChevronRight,
  Clock3,
  Code2,
  GitBranch,
  LayoutDashboard,
  MessageSquare,
  Play,
  Plus,
  RefreshCw,
  Settings,
  ShieldCheck,
  Sparkles,
  Square,
  X
} from "lucide-react";
import { api, ApprovalsSummary, PendingAction, RuntimeEvent, SessionEntry, SessionSnapshot } from "./api";

type Tab =
  | { id: string; type: "chat"; title: string; sessionId: string }
  | { id: string; type: "agents" | "mcp" | "usage" | "settings" | "timeline"; title: string };

type TranscriptItem = {
  id: string;
  role: string;
  text: string;
  muted?: boolean;
  streaming?: boolean;
};

type ActiveApproval = {
  kind: "planner" | "pending";
  token: string;
  title: string;
  description: string;
  approveLabel: string;
  actionType?: string;
  meta?: string;
};

const navItems = [
  { type: "agents" as const, label: "Agents / Subagents", icon: Bot },
  { type: "mcp" as const, label: "MCP Manager", icon: Boxes },
  { type: "usage" as const, label: "Usage", icon: LayoutDashboard },
  { type: "timeline" as const, label: "Timeline", icon: GitBranch },
  { type: "settings" as const, label: "Settings", icon: Settings }
];

export function App() {
  const [workspace, setWorkspace] = useState({ name: "pp-Echo", path: "" });
  const [sessions, setSessions] = useState<SessionEntry[]>([]);
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [activeTabId, setActiveTabId] = useState("");
  const [snapshots, setSnapshots] = useState<Record<string, SessionSnapshot>>({});
  const [events, setEvents] = useState<Record<string, RuntimeEvent[]>>({});
  const [prompt, setPrompt] = useState("");
  const [status, setStatus] = useState("Ready");
  const [sideData, setSideData] = useState<Record<string, unknown>>({});
  const [approvalSummary, setApprovalSummary] = useState<ApprovalsSummary>({ count: 0, items: [] });
  const pollers = useRef<Record<string, number>>({});
  const transcriptRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    refreshAll();
    return () => {
      Object.values(pollers.current).forEach((poller) => window.clearInterval(poller));
    };
  }, []);

  const activeTab = tabs.find((tab) => tab.id === activeTabId);
  const activeSessionId = activeTab?.type === "chat" ? activeTab.sessionId : "";
  const activeSnapshot = activeSessionId ? snapshots[activeSessionId] : undefined;
  const activeEvents = activeSessionId ? events[activeSessionId] || [] : [];
  const transcript = useMemo(() => buildTranscript(activeSnapshot, activeEvents), [activeSnapshot, activeEvents]);
  const activityItems = useMemo(() => buildActivityItems(activeEvents), [activeEvents]);
  const activeApproval = useMemo(
    () => buildActiveApproval(activeSnapshot, activeEvents, approvalSummary),
    [activeSnapshot, activeEvents, approvalSummary]
  );
  const busy = Boolean(activeSnapshot?.busy || isTurnInFlight(activeEvents));

  useEffect(() => {
    const target = transcriptRef.current;
    if (target) {
      target.scrollTop = target.scrollHeight;
    }
  }, [transcript.length, transcript[transcript.length - 1]?.text]);

  async function refreshAll() {
    const [workspaceInfo, sessionList, approvals] = await Promise.all([api.workspace(), api.sessions(), api.approvals()]);
    setWorkspace(workspaceInfo);
    setSessions(sortSessionsByUpdatedAt(sessionList.sessions));
    setApprovalSummary(approvals);
    setStatus("Connected");
    if (sessionList.sessions[0] && tabs.length === 0) {
      openSession(sessionList.sessions[0].id);
    }
  }

  async function openSession(sessionId: string) {
    const snapshot = await api.snapshot(sessionId).catch(async () => {
      const created = await api.createSession();
      return created;
    });
    setSnapshots((current) => ({ ...current, [snapshot.session_id]: snapshot }));
    ensureEventPolling(snapshot.session_id);
    const tab: Tab = { id: `chat:${snapshot.session_id}`, type: "chat", title: shortId(snapshot.session_id), sessionId: snapshot.session_id };
    setTabs((current) => (current.some((item) => item.id === tab.id) ? current : [...current, tab]));
    setActiveTabId(tab.id);
  }

  async function createSession() {
    const created = await api.createSession();
    await refreshAll();
    openSession(created.session_id);
  }

  function ensureEventPolling(sessionId: string) {
    if (pollers.current[sessionId]) return;
    setStatus("Live events connected");
    const poll = async () => {
      const payload = await api.events(sessionId).catch(() => ({ events: [] as RuntimeEvent[] }));
      payload.events.forEach((event) => appendEvent(sessionId, event));
      refreshSessionState(sessionId);
    };
    poll();
    pollers.current[sessionId] = window.setInterval(poll, 700);
  }

  function appendEvent(sessionId: string, event: RuntimeEvent) {
    setEvents((current) => ({ ...current, [sessionId]: [...(current[sessionId] || []), event] }));
    setStatus(event.message || event.type);
  }

  function refreshSessionState(sessionId: string) {
    api.snapshot(sessionId).then((snapshot) => setSnapshots((current) => ({ ...current, [sessionId]: snapshot }))).catch(() => undefined);
    api.sessions().then((payload) => setSessions(sortSessionsByUpdatedAt(payload.sessions))).catch(() => undefined);
    refreshApprovals();
  }

  function refreshApprovals() {
    api.approvals().then(setApprovalSummary).catch(() => undefined);
  }

  function openPanel(type: Exclude<Tab["type"], "chat">) {
    const title = navItems.find((item) => item.type === type)?.label || type;
    const tab: Tab = { id: `panel:${type}`, type, title };
    setTabs((current) => (current.some((item) => item.id === tab.id) ? current : [...current, tab]));
    setActiveTabId(tab.id);
    loadPanel(type);
  }

  async function loadPanel(type: string) {
    const loader =
      type === "agents" ? api.capabilities :
      type === "mcp" ? api.mcp :
      type === "settings" ? api.settings :
      type === "usage" ? api.approvals :
      type === "timeline" && activeSessionId ? () => api.tree(activeSessionId) :
      async () => ({});
    const data = await loader().catch((error) => ({ error: String(error) }));
    setSideData((current) => ({ ...current, [type]: data }));
  }

  async function sendPrompt() {
    if (!activeSessionId || !prompt.trim()) return;
    const text = prompt;
    setPrompt("");
    appendEvent(activeSessionId, { type: "local_user_prompt", session_id: activeSessionId, message: text });
    await api.prompt(activeSessionId, text);
    refreshSessionState(activeSessionId);
  }

  async function approve() {
    if (!activeApproval) return;
    if (activeApproval.kind === "planner" && activeSessionId) {
      await api.approve(activeSessionId);
      clearPlannerToken(activeSessionId);
    } else {
      await api.approvePending(activeApproval.token);
      removeApproval(activeApproval.token);
    }
    if (activeSessionId) refreshSessionState(activeSessionId);
    refreshApprovals();
  }

  async function reject() {
    if (!activeApproval) return;
    if (activeApproval.kind === "planner" && activeSessionId) {
      await api.reject(activeSessionId);
      clearPlannerToken(activeSessionId);
    } else {
      await api.rejectPending(activeApproval.token);
      removeApproval(activeApproval.token);
    }
    if (activeSessionId) refreshSessionState(activeSessionId);
    refreshApprovals();
  }

  function clearPlannerToken(sessionId: string) {
    setSnapshots((current) => {
      const snapshot = current[sessionId];
      return snapshot ? { ...current, [sessionId]: { ...snapshot, pending_plan_token: null } } : current;
    });
  }

  function removeApproval(token: string) {
    setApprovalSummary((current) => ({
      ...current,
      count: Math.max(0, current.count - 1),
      tokens: current.tokens?.filter((item) => item !== token),
      items: current.items.filter((item) => item.token !== token)
    }));
  }

  function closeTab(tabId: string) {
    setTabs((current) => current.filter((tab) => tab.id !== tabId));
    if (activeTabId === tabId) {
      const remaining = tabs.filter((tab) => tab.id !== tabId);
      setActiveTabId(remaining[remaining.length - 1]?.id || "");
    }
  }

  return (
    <div className="shell">
      <header className="titlebar">
        <div className="brand">
          <div className="brand-mark"><Sparkles size={17} /></div>
          <div>
            <strong>pp-Echo</strong>
            <span>{workspace.path}</span>
          </div>
        </div>
        <div className="title-actions">
          <button title="Refresh" onClick={refreshAll}><RefreshCw size={16} /></button>
          <button title="New session" onClick={createSession}><Plus size={16} /></button>
          <button title="Stop"><Square size={15} /></button>
        </div>
      </header>

      <aside className="sidebar">
        <section className="workspace-card">
          <div className="workspace-icon"><Code2 size={20} /></div>
          <div>
            <h1>{workspace.name}</h1>
            <p>Local workspace</p>
          </div>
        </section>

        <nav className="nav-list">
          {navItems.map((item) => (
            <button key={item.type} onClick={() => openPanel(item.type)}>
              <item.icon size={16} />
              <span>{item.label}</span>
              <ChevronRight size={14} />
            </button>
          ))}
        </nav>

        <section className="session-list">
          <div className="section-title">
            <span>Sessions</span>
            <button onClick={createSession} title="New session"><Plus size={14} /></button>
          </div>
          {sessions.map((session) => (
            <button className="session-row" key={session.id} onClick={() => openSession(session.id)}>
              <MessageSquare size={15} />
              <div>
                <strong>{session.last_user_preview || session.summary_preview || shortId(session.id)}</strong>
                <span>{session.turn_count} turns · {session.model}</span>
              </div>
            </button>
          ))}
        </section>
      </aside>

      <main className="main">
        <div className="tabs">
          {tabs.map((tab) => (
            <button className={tab.id === activeTabId ? "tab active" : "tab"} key={tab.id} onClick={() => setActiveTabId(tab.id)}>
              <span>{tab.title}</span>
              <X size={13} onClick={(event) => { event.stopPropagation(); closeTab(tab.id); }} />
            </button>
          ))}
        </div>

        <div className="content">
          {activeTab?.type === "chat" ? (
            <>
              <section className="transcript" ref={transcriptRef}>
                {transcript.length === 0 && (
                  <div className="empty">
                    <Sparkles size={26} />
                    <h2>Start a pp-Echo session</h2>
                    <p>Ask for repo inspection, implementation planning, or a safe change.</p>
                  </div>
                )}
                {transcript.map((item) => (
                  <article className={`message ${item.role}${item.streaming ? " streaming" : ""}`} key={item.id}>
                    <div className="avatar">{item.role === "assistant" ? <Bot size={16} /> : <MessageSquare size={15} />}</div>
                    <div className="bubble">
                      <span>{item.role}</span>
                      <p>{item.text}{item.streaming && <i className="stream-cursor" />}</p>
                    </div>
                  </article>
                ))}
              </section>

              <aside className="detail-panel">
                <div className="panel-card">
                  <h3><Activity size={16} /> Runtime</h3>
                  <dl>
                    <dt>Status</dt><dd>{status}</dd>
                    <dt>Session</dt><dd>{shortId(activeSessionId)}</dd>
                    <dt>Queue</dt><dd>{activeSnapshot?.queued_message_count || 0}</dd>
                    <dt>Mode</dt><dd>{busy ? "Working" : "Idle"}</dd>
                  </dl>
                </div>
                <div className="panel-card">
                  <h3><ShieldCheck size={16} /> Approval</h3>
                  {activeApproval ? (
                    <>
                      <p className="approval-kind">{activeApproval.title}</p>
                      <p className="muted">{activeApproval.description}</p>
                      {activeApproval.meta && <small className="approval-meta">{activeApproval.meta}</small>}
                      <code>{String(activeApproval.token).slice(0, 18)}</code>
                      <div className="split-actions">
                        <button onClick={approve}><Check size={15} /> {activeApproval.approveLabel}</button>
                        <button onClick={reject}><X size={15} /> Reject</button>
                      </div>
                    </>
                  ) : <p className="muted">{approvalEmptyText(busy, approvalSummary.count)}</p>}
                </div>
                <div className="panel-card">
                  <h3><Clock3 size={16} /> Recent Events</h3>
                  <ul className="event-list">
                    {activityItems.length === 0 && <li className="muted-event">No tool activity yet</li>}
                    {activityItems.slice(-8).reverse().map((item, index) => (
                      <li key={`${item.label}-${index}`}>
                        <strong>{item.label}</strong>
                        <span>{item.detail}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </aside>

              <div className="composer">
                <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Ask pp-Echo what to do next" />
                <button disabled={!activeSessionId || !prompt.trim() || Boolean(activeApproval)} onClick={sendPrompt}>
                  <Play size={17} />
                </button>
              </div>
            </>
          ) : activeTab ? (
            <PanelView type={activeTab.type} data={sideData[activeTab.type]} onReload={() => loadPanel(activeTab.type)} />
          ) : (
            <div className="empty full"><Sparkles size={30} /><h2>Select or create a session</h2></div>
          )}
        </div>
      </main>
    </div>
  );
}

function PanelView({ type, data, onReload }: { type: string; data: unknown; onReload: () => void }) {
  return (
    <section className="panel-page">
      <header>
        <div>
          <h2>{panelTitle(type)}</h2>
          <p>{panelSubtitle(type)}</p>
        </div>
        <button onClick={onReload}><RefreshCw size={16} /> Reload</button>
      </header>
      <pre>{JSON.stringify(data || {}, null, 2)}</pre>
    </section>
  );
}

function buildTranscript(snapshot?: SessionSnapshot, events: RuntimeEvent[] = []): TranscriptItem[] {
  const committedMessages = snapshot?.messages || [];
  const stored: TranscriptItem[] = committedMessages
    .filter((message) => message.role === "user" || message.role === "assistant")
    .map((message, index) => ({
      id: `stored:${index}`,
      role: message.role,
      text: messageText(message)
    }))
    .filter((item) => item.text.trim());

  const committedUsers = new Set(
    committedMessages
      .filter((message) => message.role === "user")
      .map((message) => normalizeText(messageText(message)))
      .filter(Boolean)
  );
  const committedAssistants = committedMessages
    .filter((message) => message.role === "assistant")
    .map((message) => normalizeText(messageText(message)))
    .filter(Boolean);

  const runtime: TranscriptItem[] = [];
  let streamBuffer = "";
  let streamIndex = 0;

  const flushStream = () => {
    const text = streamBuffer.trim();
    streamBuffer = "";
    if (!text) return;
    const normalized = normalizeText(text);
    const alreadyCommitted = committedAssistants.some((committed) => committed.includes(normalized) || normalized.includes(committed));
    if (!alreadyCommitted) {
      runtime.push({ id: `stream:${streamIndex++}`, role: "assistant", text, streaming: true });
    }
  };

  for (const event of events) {
    if (event.type === "message_delta") {
      streamBuffer += event.delta || "";
      continue;
    }
    if (event.type === "local_user_prompt") {
      flushStream();
      const text = (event.message || "").trim();
      if (text && !committedUsers.has(normalizeText(text))) {
        runtime.push({ id: `local-user:${runtime.length}`, role: "user", text });
      }
      continue;
    }
    if (event.type === "turn_end" || event.type === "agent_end" || event.type === "agent_start") {
      flushStream();
      continue;
    }
    if (event.is_error && event.message) {
      flushStream();
      runtime.push({ id: `error:${runtime.length}`, role: "error", text: event.message });
      continue;
    }
    if (event.type.includes("tool")) {
      flushStream();
    }
  }
  flushStream();
  const items = [...stored, ...runtime];
  if (shouldShowThinking(items, events)) {
    items.push({ id: "thinking", role: "assistant", text: "Thinking", streaming: true });
  }
  return items;
}

function messageText(message: SessionSnapshot["messages"][number]) {
  return message.content.map((part) => part.text || part.name || "").filter(Boolean).join("\n");
}

function normalizeText(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function shouldShowThinking(items: TranscriptItem[], events: RuntimeEvent[]) {
  if (!isTurnInFlight(events)) return false;
  const latestUserIndex = findLastIndex(items, (item) => item.role === "user");
  if (latestUserIndex < 0) return true;
  return !items.slice(latestUserIndex + 1).some((item) => item.role === "assistant" && item.text.trim() && item.id !== "thinking");
}

function isTurnInFlight(events: RuntimeEvent[]) {
  let inFlight = false;
  for (const event of events) {
    if (event.type === "local_user_prompt" || event.type === "agent_start" || event.type === "turn_start") {
      inFlight = true;
    }
    if (event.type === "turn_end" || event.type === "agent_end" || event.type === "error") {
      inFlight = false;
    }
  }
  return inFlight;
}

function buildActivityItems(events: RuntimeEvent[]) {
  return events
    .filter((event) => event.type.includes("tool") || event.type.includes("planner") || event.type.includes("checkpoint"))
    .map((event) => ({
      label: event.tool_name || event.type.replace(/_/g, " "),
      detail: summarizeEvent(event)
    }));
}

function summarizeEvent(event: RuntimeEvent) {
  if (event.plan_step?.title) return event.plan_step.title;
  if (event.message) return truncate(event.message, 92);
  const preview = event.details?.preview;
  if (typeof preview === "string" && preview.trim()) return truncate(preview, 92);
  const summary = event.details?.summary;
  if (typeof summary === "string" && summary.trim()) return truncate(summary, 92);
  return event.is_error ? "Failed" : "Updated";
}

function truncate(value: string, limit: number) {
  const clean = normalizeText(value);
  return clean.length <= limit ? clean : `${clean.slice(0, limit - 1)}...`;
}

function findLastIndex<T>(items: T[], predicate: (item: T) => boolean) {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    if (predicate(items[index])) return index;
  }
  return -1;
}

function buildActiveApproval(snapshot: SessionSnapshot | undefined, events: RuntimeEvent[], summary: ApprovalsSummary): ActiveApproval | null {
  const plannerToken = snapshot?.pending_plan_token;
  if (plannerToken) {
    return {
      kind: "planner",
      token: plannerToken,
      title: "Step 1 of 2: approve plan",
      description: "Review the model's proposed tool plan. This step does not apply file changes yet.",
      approveLabel: "Approve plan"
    };
  }
  const sessionId = snapshot?.session_id || "";
  const eventTokens = eventPendingTokens(events);
  const pending = summary.items.find((item) => item.action_type !== "planner_approval" && approvalBelongsToSession(item, sessionId, eventTokens));
  if (!pending) return null;
  return {
    kind: "pending",
    token: pending.token,
    title: `Step 2 of 2: ${approvalTitle(pending.action_type)}`,
    description: approvalDescription(pending),
    approveLabel: approvalButtonLabel(pending.action_type),
    actionType: pending.action_type,
    meta: approvalMeta(pending)
  };
}

function eventPendingTokens(events: RuntimeEvent[]) {
  const tokens = new Set<string>();
  events.forEach((event) => {
    const token = event.details?.token;
    if (typeof token === "string" && token.trim()) tokens.add(token);
  });
  return tokens;
}

function approvalBelongsToSession(item: PendingAction, sessionId: string, eventTokens: Set<string>) {
  const itemSession = item.details?.session_id;
  if (typeof itemSession === "string" && itemSession) return itemSession === sessionId;
  return eventTokens.has(item.token);
}

function approvalEmptyText(busy: boolean, workspaceApprovalCount: number) {
  if (busy) return "Plan accepted. Waiting for model output or an exact action confirmation.";
  if (workspaceApprovalCount > 0) return `${workspaceApprovalCount} pending approval(s) exist in this workspace. Open Usage to review old items.`;
  return "No pending approval for this session.";
}

function approvalTitle(actionType: string) {
  if (actionType === "write_file") return "apply staged write";
  if (actionType === "edit_file") return "apply staged edit";
  if (actionType === "run_shell") return "run staged command";
  return actionType.replace(/_/g, " ");
}

function approvalButtonLabel(actionType: string) {
  if (actionType === "write_file") return "Apply write";
  if (actionType === "edit_file") return "Apply edit";
  if (actionType === "run_shell") return "Run command";
  return "Approve action";
}

function approvalDescription(item: PendingAction) {
  if (item.target_path) return `Target: ${item.target_path}`;
  if (item.command) return `Command: ${item.command}`;
  const details = item.details || {};
  const target = details.target_path || details.path || details.file_path;
  if (typeof target === "string" && target.trim()) return `Target: ${target}`;
  const command = details.command;
  if (typeof command === "string" && command.trim()) return `Command: ${command}`;
  const summary = details.summary;
  if (Array.isArray(summary) && summary.length > 0) return String(summary[0]);
  if (typeof summary === "string" && summary.trim()) return summary;
  return "A concrete staged action is waiting for your second confirmation.";
}

function approvalMeta(item: PendingAction) {
  const state = item.lifecycle?.state || "pending";
  return `${item.action_type} · ${state}`;
}

function shortId(value: string) {
  return value ? value.slice(0, 8) : "session";
}

function sortSessionsByUpdatedAt(items: SessionEntry[]) {
  return [...items].sort((left, right) => (right.updated_at || 0) - (left.updated_at || 0));
}

function panelTitle(type: string) {
  if (type === "agents") return "Agents / Subagents";
  if (type === "mcp") return "MCP Manager";
  if (type === "usage") return "Usage Dashboard";
  if (type === "timeline") return "Timeline & Checkpoints";
  return "Settings";
}

function panelSubtitle(type: string) {
  if (type === "agents") return "Discover built-in tools, skills, extensions, and subagent-facing capabilities.";
  if (type === "mcp") return "Inspect Model Context Protocol configuration for this workspace.";
  if (type === "usage") return "Runtime status and approval workload for the current workspace.";
  if (type === "timeline") return "Session tree, rewind targets, and checkpoint-oriented state.";
  return "Active pp-Echo configuration resolved from environment and project files.";
}
