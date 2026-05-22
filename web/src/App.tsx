import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import {
  Activity,
  Bot,
  BookOpen,
  Boxes,
  Check,
  ChevronRight,
  Clock3,
  Code2,
  Database,
  FileText,
  FolderOpen,
  LayoutDashboard,
  MessageSquare,
  Monitor,
  Plus,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Square,
  Users,
  X
} from "lucide-react";
import { api, ApprovalActionResponse, ApprovalsSummary, OpenWorkspaceResponse, PendingAction, RuntimeEvent, SessionEntry, SessionSnapshot, TimelineEntry, WorkspacesState } from "./api";
import { extractMessageBody, RichMessageContent } from "./rich-text";

type ViewKey =
  | "chat"
  | "history"
  | "search"
  | "group"
  | "workspace"
  | "tasks"
  | "board"
  | "channels"
  | "plugins"
  | "memory"
  | "model"
  | "logs"
  | "usage"
  | "skills"
  | "users";

type InspectorTab = "status" | "tools" | "approvals";
type ThemeMode = "dark" | "light";
type NoticeTone = "info" | "success" | "warning";

type TranscriptItem = {
  id: string;
  role: string;
  body: ReturnType<typeof extractMessageBody>;
  streaming?: boolean;
  timestamp?: number;
};

type Notice = {
  id: string;
  tone: NoticeTone;
  message: string;
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

type DirectoryPickerHandle = {
  name: string;
  path?: string;
  fullPath?: string;
  nativePath?: string;
  __path?: string;
};

type DirectoryPickerWindow = Window & {
  showDirectoryPicker?: () => Promise<DirectoryPickerHandle>;
};

const MAX_SESSION_EVENTS = 2000;
const ACTIONABLE_APPROVAL_STATES = new Set(["", "staged_not_granted", "grant_attached"]);
const STORAGE_THEME_KEY = "pp-echo-web-theme";
const STORAGE_ACTIVE_VIEW_KEY = "pp-echo-web-view";
const STORAGE_ACTIVE_SESSION_KEY = "pp-echo-web-session";

const navItems: Array<{
  view: ViewKey;
  label: string;
  icon: typeof MessageSquare;
  description: string;
}> = [
  { view: "chat", label: "会话", icon: MessageSquare, description: "聊天与当前会话" },
  { view: "history", label: "历史", icon: Clock3, description: "会话历史与回看" },
  { view: "group", label: "群聊", icon: Users, description: "多会话协作" },
  { view: "search", label: "搜索", icon: Search, description: "会话检索" },
  { view: "workspace", label: "工作区", icon: FolderOpen, description: "工作区切换" },
  { view: "tasks", label: "任务", icon: LayoutDashboard, description: "审批与待办" },
  { view: "board", label: "看板", icon: Boxes, description: "运行概览" },
  { view: "channels", label: "频道", icon: Bot, description: "MCP 与通道" },
  { view: "plugins", label: "插件", icon: Sparkles, description: "能力扩展" },
  { view: "memory", label: "记忆", icon: BookOpen, description: "记忆视图" },
  { view: "model", label: "模型", icon: Monitor, description: "模型与环境" },
  { view: "logs", label: "日志", icon: FileText, description: "时间线与日志" },
  { view: "usage", label: "用量", icon: Database, description: "运行统计" },
  { view: "skills", label: "技能", icon: ShieldCheck, description: "技能与规则" },
  { view: "users", label: "设置", icon: Settings, description: "系统设置" }
];

const shellNavGroups: Array<{ title: string; views: ViewKey[] }> = [
  { title: "对话", views: ["chat", "history", "group", "search"] },
  { title: "执行", views: ["workspace", "tasks", "board", "channels"] },
  { title: "扩展", views: ["plugins", "memory", "model"] },
  { title: "监控", views: ["logs", "usage", "skills", "users"] }
];

const inspectorTabs: Array<{ id: InspectorTab; label: string; icon: typeof Activity }> = [
  { id: "status", label: "状态", icon: Activity },
  { id: "tools", label: "工具", icon: Code2 },
  { id: "approvals", label: "审批", icon: ShieldCheck }
];

export function App() {
  const [theme, setTheme] = useState<ThemeMode>(() => readTheme());
  const [workspace, setWorkspace] = useState<WorkspacesState>({ active: { name: "pp-Echo", path: "", exists: true, is_dir: true }, recent: [] });
  const [sessions, setSessions] = useState<SessionEntry[]>([]);
  const [activeView, setActiveView] = useState<ViewKey>(() => readStoredView());
  const [activeSessionId, setActiveSessionId] = useState<string>(() => window.localStorage.getItem(STORAGE_ACTIVE_SESSION_KEY) || "");
  const [snapshots, setSnapshots] = useState<Record<string, SessionSnapshot>>({});
  const [events, setEvents] = useState<Record<string, RuntimeEvent[]>>({});
  const [prompt, setPrompt] = useState("");
  const [status, setStatus] = useState("Ready");
  const [approvalSummary, setApprovalSummary] = useState<ApprovalsSummary>({ count: 0, items: [] });
  const [approvalAction, setApprovalAction] = useState<{ token: string; action: "approve" | "reject" } | null>(null);
  const [approvalFeedback, setApprovalFeedback] = useState("");
  const [workspaceDraft, setWorkspaceDraft] = useState("");
  const [pendingWorkspace, setPendingWorkspace] = useState<OpenWorkspaceResponse | null>(null);
  const [promptSubmitting, setPromptSubmitting] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("status");
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [workspaceDialogOpen, setWorkspaceDialogOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);

  const pollers = useRef<Record<string, number>>({});
  const transcriptRef = useRef<HTMLElement | null>(null);
  const noticeTimer = useRef<number | null>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem(STORAGE_THEME_KEY, theme);
  }, [theme]);

  useEffect(() => {
    refreshAll().catch(() => undefined);
    return () => {
      stopPolling();
      if (noticeTimer.current) window.clearTimeout(noticeTimer.current);
    };
  }, []);

  useEffect(() => {
    if (!activeView) return;
    window.localStorage.setItem(STORAGE_ACTIVE_VIEW_KEY, activeView);
  }, [activeView]);

  useEffect(() => {
    if (!activeSessionId) return;
    window.localStorage.setItem(STORAGE_ACTIVE_SESSION_KEY, activeSessionId);
  }, [activeSessionId]);

  useEffect(() => {
    if (activeView !== "logs") return;
    refreshTimeline().catch(() => undefined);
  }, [activeView, activeSessionId]);

  useEffect(() => {
    const target = transcriptRef.current;
    if (target) target.scrollTop = target.scrollHeight;
  }, [activeSessionId, sessions.length, notice?.id]);

  const activeSnapshot = activeSessionId ? snapshots[activeSessionId] : undefined;
  const activeEvents = activeSessionId ? events[activeSessionId] || [] : [];
  const transcript = useMemo(() => buildTranscript(activeSnapshot, activeEvents), [activeSnapshot, activeEvents]);
  const activityItems = useMemo(() => buildActivityItems(activeEvents), [activeEvents]);
  const activeApproval = useMemo(() => buildActiveApproval(activeSnapshot, activeEvents, approvalSummary), [activeSnapshot, activeEvents, approvalSummary]);
  const busy = runtimeIsBusy(activeSnapshot, activeEvents);
  const displayStatus = runtimeDisplayStatus(status, activeSnapshot, activeEvents);
  const filteredSessions = useMemo(() => filterSessions(sessions, searchQuery), [sessions, searchQuery]);
  const sessionStats = useMemo(() => computeSessionStats(sessions), [sessions]);
  const viewLabel = navItems.find((item) => item.view === activeView)?.label || "会话";
  const viewMeta = navItems.find((item) => item.view === activeView);
  const middleMode = activeView === "history" ? "sessions" : activeView === "board" ? "observer" : null;

  async function refreshAll() {
    const [workspaceState, sessionList, approvals] = await Promise.all([api.workspaces(), api.sessions(), api.approvals()]);
    setWorkspace(workspaceState);
    setSessions(sortSessionsByUpdatedAt(sessionList.sessions));
    setApprovalSummary(approvals);
    setStatus("Connected");

    const restoredSessionId = window.localStorage.getItem(STORAGE_ACTIVE_SESSION_KEY) || "";
    const nextSessionId = sessionList.sessions.some((session) => session.id === restoredSessionId)
      ? restoredSessionId
      : sessionList.sessions[0]?.id || "";

    if (activeView === "chat") {
      if (nextSessionId) {
        await openSession(nextSessionId);
      }
      return;
    }

    if (nextSessionId && !activeSessionId) {
      await hydrateSession(nextSessionId);
    } else if (activeSessionId && !sessionList.sessions.some((session) => session.id === activeSessionId)) {
      setActiveSessionId(nextSessionId);
    }
  }

  async function refreshTimeline() {
    const payload = await api.timeline(activeSessionId || undefined, 120);
    setTimeline(payload.timeline);
  }

  async function openSession(sessionId: string) {
    setActiveView("chat");
    await hydrateSession(sessionId);
    setNotice(null);
  }

  async function hydrateSession(sessionId: string) {
    let snapshot: SessionSnapshot;
    try {
      snapshot = await api.snapshot(sessionId);
    } catch (error) {
      stopPollingExcept(sessionId);
      setStatus(`Failed to open session ${shortId(sessionId)}: ${error instanceof Error ? error.message : String(error)}`);
      return;
    }

    setActiveSessionId(snapshot.session_id);
    setSnapshots((current) => ({ ...current, [snapshot.session_id]: snapshot }));
    stopPollingExcept(snapshot.session_id);
    if (snapshot.history?.source !== "stored") {
      ensureEventPolling(snapshot.session_id);
    }
  }

  async function createSession() {
    const created = await api.createSession();
    await refreshAll();
    await openSession(created.session_id);
  }

  function ensureEventPolling(sessionId: string) {
    if (pollers.current[sessionId]) return;
    setStatus("Live events connected");
    const poll = async () => {
      try {
        const payload = await api.events(sessionId);
        payload.events.forEach((event) => appendEvent(sessionId, event));
        const refreshed = await refreshSessionState(sessionId);
        if (!refreshed) stopSessionPolling(sessionId);
      } catch (error) {
        stopSessionPolling(sessionId);
        setStatus(`Stopped polling ${shortId(sessionId)}: ${error instanceof Error ? error.message : String(error)}`);
      }
    };
    poll();
    pollers.current[sessionId] = window.setInterval(poll, 700);
  }

  function appendEvent(sessionId: string, event: RuntimeEvent) {
    setEvents((current) => {
      const existing = current[sessionId] || [];
      const key = runtimeEventKey(event);
      if (key && existing.some((item) => runtimeEventKey(item) === key)) return current;
      return { ...current, [sessionId]: [...existing, event].slice(-MAX_SESSION_EVENTS) };
    });
    setStatus(event.message || event.type);
  }

  async function refreshSessionState(sessionId: string) {
    try {
      const snapshot = await api.snapshot(sessionId);
      setSnapshots((current) => ({ ...current, [sessionId]: snapshot }));
    } catch (error) {
      setStatus(`Session ${shortId(sessionId)} refresh failed: ${error instanceof Error ? error.message : String(error)}`);
      return false;
    }
    api.sessions().then((payload) => setSessions(sortSessionsByUpdatedAt(payload.sessions))).catch(() => undefined);
    refreshApprovals();
    return true;
  }

  function refreshApprovals() {
    return api.approvals().then(setApprovalSummary).catch(() => undefined);
  }

  function openView(view: ViewKey) {
    if (view === "workspace") {
      setWorkspaceDialogOpen(true);
      setWorkspaceDraft(workspace.active.path || "");
      return;
    }
    if (view === "history") {
      if (activeView === "history") {
        setActiveView("chat");
        setInspectorOpen(false);
        return;
      }
      setActiveView("history");
      setInspectorOpen(false);
      if (!activeSessionId) {
        const firstSession = sessions[0]?.id;
        if (firstSession) hydrateSession(firstSession).catch(() => undefined);
      }
      return;
    }
    if (view === "board") {
      if (activeView === "board") {
        setActiveView("chat");
        setInspectorOpen(false);
        return;
      }
      setActiveView("board");
      setInspectorOpen(true);
      return;
    }
    setActiveView(view);
    if (view === "chat") {
      if (activeSessionId) return;
      const firstSession = sessions[0]?.id;
      if (firstSession) {
        openSession(firstSession).catch(() => undefined);
        return;
      }
      showNotice("还没有会话，先新建一个吧", "info");
      return;
    }

    const item: any = navItems.find((entry) => entry.view === view);
    if (item) {
      showNotice(`${item.label} 功能开发中，敬请期待`, "info");
    }
  }

  function stopPolling() {
    Object.values(pollers.current).forEach((poller) => window.clearInterval(poller));
    pollers.current = {};
  }

  function stopSessionPolling(sessionId: string) {
    const poller = pollers.current[sessionId];
    if (!poller) return;
    window.clearInterval(poller);
    delete pollers.current[sessionId];
  }

  function stopPollingExcept(sessionId: string) {
    Object.entries(pollers.current).forEach(([key, poller]) => {
      if (key === sessionId) return;
      window.clearInterval(poller);
      delete pollers.current[key];
    });
  }

  async function reloadWorkspaceAfterSwitch(workspaceState: WorkspacesState) {
    stopPolling();
    setWorkspace(workspaceState);
    setActiveView("chat");
    setActiveSessionId("");
    setSnapshots({});
    setEvents({});
    setTimeline([]);
    setPrompt("");
    setApprovalSummary({ count: 0, items: [] });
    const [sessionList, approvals] = await Promise.all([api.sessions(), api.approvals()]);
    const sorted = sortSessionsByUpdatedAt(sessionList.sessions);
    setSessions(sorted);
    setApprovalSummary(approvals);
    if (sorted[0]) {
      await hydrateSession(sorted[0].id);
    }
  }

  async function openWorkspace(path: string, confirmed = false) {
    const target = path.trim();
    if (!target) {
      showNotice("请输入工作区路径", "warning");
      return;
    }
    try {
      const response = await api.openWorkspace(target, confirmed);
      if (response.requires_confirmation) {
        setPendingWorkspace(response);
        return;
      }
      setPendingWorkspace(null);
      setWorkspaceDraft("");
      setWorkspaceDialogOpen(false);
      await reloadWorkspaceAfterSwitch(response);
      showNotice("工作区已切换", "success");
    } catch (error) {
      showNotice(workspaceErrorMessage(error, target), "warning");
    }
  }

  async function sendPrompt() {
    if (!activeSessionId || !prompt.trim() || promptSubmitting || busy || activeApproval) return;
    const text = prompt;
    setPromptSubmitting(true);
    setPrompt("");
    appendEvent(activeSessionId, { type: "local_user_prompt", session_id: activeSessionId, message: text, timestamp: Date.now() / 1000 });
    try {
      await api.prompt(activeSessionId, text);
      ensureEventPolling(activeSessionId);
      await refreshSessionState(activeSessionId);
    } catch (error) {
      setPrompt(text);
      showNotice(error instanceof Error ? error.message : String(error), "warning");
    } finally {
      setPromptSubmitting(false);
    }
  }

  async function cancelActiveSession() {
    if (!activeSessionId || !busy) return;
    appendEvent(activeSessionId, {
      type: "cancel_requested",
      session_id: activeSessionId,
      message: "Cancel requested for the running turn.",
      timestamp: Date.now() / 1000,
      details: { cancel_requested: true }
    });
    await api.cancel(activeSessionId);
    ensureEventPolling(activeSessionId);
    refreshSessionState(activeSessionId);
    showNotice("已请求停止当前会话", "info");
  }

  async function approve() {
    if (!activeApproval) return;
    const approval = activeApproval;
    setApprovalAction({ token: approval.token, action: "approve" });
    setApprovalFeedback("");
    try {
      if (approval.kind === "planner" && activeSessionId) {
        await api.approve(activeSessionId);
        clearPlannerToken(activeSessionId);
        setApprovalFeedback("Plan approved. Waiting for the concrete action.");
        ensureEventPolling(activeSessionId);
      } else {
        const result = await api.approvePending(approval.token);
        removeApproval(approval.token);
        const message = approvalSuccessMessage(approval.actionType || "", result);
        setApprovalFeedback(message);
        setStatus(message);
      }
      await refreshApprovals();
      if (activeSessionId) await refreshSessionState(activeSessionId);
      showNotice("审批已通过", "success");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setApprovalFeedback(message);
      setStatus(message);
      showNotice(message, "warning");
    } finally {
      setApprovalAction(null);
    }
  }

  async function reject() {
    if (!activeApproval) return;
    const approval = activeApproval;
    setApprovalAction({ token: approval.token, action: "reject" });
    setApprovalFeedback("");
    try {
      if (approval.kind === "planner" && activeSessionId) {
        await api.reject(activeSessionId);
        clearPlannerToken(activeSessionId);
        ensureEventPolling(activeSessionId);
      } else {
        await api.rejectPending(approval.token);
        removeApproval(approval.token);
      }
      setApprovalFeedback("Approval rejected.");
      setStatus("Approval rejected");
      await refreshApprovals();
      if (activeSessionId) await refreshSessionState(activeSessionId);
      showNotice("审批已拒绝", "info");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setApprovalFeedback(message);
      setStatus(message);
      showNotice(message, "warning");
    } finally {
      setApprovalAction(null);
    }
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
      items: current.items.filter((item) => item.token !== token)
    }));
  }

  function showNotice(message: string, tone: NoticeTone = "info") {
    setNotice({ id: `notice-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, message, tone });
    if (noticeTimer.current) window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => setNotice(null), 2200);
  }

  function handleComingSoon(label: string) {
    showNotice(`${label} 功能开发中，敬请期待`, "info");
  }

  return (
    <div className={`app-shell theme-${theme} ${middleMode ? `mode-${middleMode}` : "mode-chat"}`}>
      <aside className="app-nav">
        <div className="app-brand">
          <button className="brand-button" onClick={() => openView("chat")} title="pp-Echo">
            <div className="brand-mark">
              <Sparkles size={17} />
            </div>
            <div className="brand-copy">
              <strong>pp-Echo</strong>
              <span>{workspace.active.path || "本地工作区"}</span>
            </div>
          </button>
          <button className="icon-button" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} title="切换主题">
            <Monitor size={16} />
          </button>
        </div>

        <nav className="nav-groups">
          {shellNavGroups.map((group) => (
            <section className="nav-group" key={group.title}>
              <div className="nav-group-label">{group.title}</div>
              <div className="nav-group-items">
                {group.views.map((view) => {
                  const item = navItems.find((entry) => entry.view === view)!;
                  const Icon = item.icon;
                  return (
                    <button
                      key={item.view}
                      className={activeView === item.view ? "nav-entry active" : "nav-entry"}
                      title={item.description}
                      onClick={() => openView(item.view)}
                    >
                      <Icon size={16} />
                      <span>{item.label}</span>
                      <ChevronRight size={13} />
                    </button>
                  );
                })}
              </div>
            </section>
          ))}
        </nav>

        <div className="app-nav-footer">
          <button className="footer-line" onClick={refreshAll}>
            <RefreshCw size={15} />
            <span>刷新</span>
          </button>
          <button className="footer-line" onClick={createSession}>
            <Plus size={15} />
            <span>新会话</span>
          </button>
          <div className="footer-meta">
            <span>{sessionStats.total} 会话</span>
            <span>{sessionStats.active} 活跃</span>
          </div>
        </div>
      </aside>

      <section className="session-rail">
        <div className="session-rail-head">
          <div>
            <small>SESSIONS</small>
            <h2>会话列表</h2>
          </div>
          <button className="icon-button" onClick={() => openView("search")} title="搜索">
            <Search size={16} />
          </button>
        </div>

        <div className="session-rail-toolbar">
          <button className="session-toolbar-btn" onClick={createSession}>
            <Plus size={14} />
            <span>新建</span>
          </button>
          <button className="session-toolbar-btn" onClick={refreshAll}>
            <RefreshCw size={14} />
            <span>刷新</span>
          </button>
        </div>

        <label className="session-search">
          <Search size={15} />
          <input value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="搜索会话" />
        </label>

        <div className="session-meta">
          <span>{sessionStats.total} 会话</span>
          <span>{sessionStats.active} 活跃</span>
        </div>

        <div className="session-stack">
          {filteredSessions.slice(0, 14).map((session) => (
            <button className={activeSessionId === session.id ? "session-row active" : "session-row"} key={session.id} onClick={() => hydrateSession(session.id)}>
              <MessageSquare size={15} />
              <div>
                <strong>{session.last_user_preview || session.summary_preview || shortId(session.id)}</strong>
                <span>{session.turn_count} turns · {session.model}</span>
              </div>
              {session.pending_plan_token ? <em>审批中</em> : null}
            </button>
          ))}
        </div>
      </section>

      <main className="content-canvas">
        <header className="canvas-header">
          <div className="canvas-header-copy">
            <div className="canvas-crumbs">
              <span>PP-ECHO / {viewLabel.toUpperCase()}</span>
              <span>{activeSessionId ? shortId(activeSessionId) : "session"}</span>
            </div>
            <h1>{viewLabel}</h1>
            <p>{viewMeta?.description || workspace.active.path || "功能开发中，敬请期待"}</p>
          </div>

          <div className="canvas-actions">
            <button className="icon-button" onClick={refreshAll} title="刷新">
              <RefreshCw size={16} />
            </button>
            <button className="icon-button" onClick={createSession} title="新会话">
              <Plus size={16} />
            </button>
            <button className="icon-button" onClick={cancelActiveSession} disabled={!activeSessionId || !busy} title="停止">
              <Square size={15} />
            </button>
            <button className={inspectorOpen ? "icon-button active" : "icon-button"} onClick={() => setInspectorOpen((current) => !current)} title="观察窗">
              <Activity size={16} />
            </button>
          </div>
        </header>

        <div className="canvas-body">
          {activeView === "chat" || activeView === "history" || activeView === "board" ? (
            <ChatWorkspace
              transcriptRef={transcriptRef}
              transcript={transcript}
              activeSnapshot={activeSnapshot}
              activeSessionId={activeSessionId}
              displayStatus={displayStatus}
              busy={busy}
              prompt={prompt}
              promptSubmitting={promptSubmitting}
              activeApproval={activeApproval}
              setPrompt={setPrompt}
              sendPrompt={sendPrompt}
              cancelActiveSession={cancelActiveSession}
              activityItems={activityItems}
              approvalSummary={approvalSummary}
              approvalAction={approvalAction}
              approvalFeedback={approvalFeedback}
              approve={approve}
              reject={reject}
              inspectorTab={inspectorTab}
              setInspectorTab={setInspectorTab}
              activeEvents={activeEvents}
              notice={notice}
              inspectorOpen={inspectorOpen}
              setInspectorOpen={setInspectorOpen}
            />
          ) : activeView === "logs" ? (
            <TimelinePanel
              activeSessionId={activeSessionId}
              timeline={timeline}
              activeEvents={activeEvents}
              onReload={refreshTimeline}
            />
          ) : (
            <ComingSoonPanel title={viewLabel} onComingSoon={handleComingSoon} onReload={refreshAll} />
          )}
        </div>
      </main>

      <div className={inspectorOpen ? "inspector-drawer open" : "inspector-drawer"}>
        <div className="inspector-drawer-head">
          <div>
            <small>INSPECTOR</small>
            <h2>状态 / 工具 / 审批</h2>
          </div>
          <button className="icon-button" onClick={() => setInspectorOpen(false)} title="收起">
            <X size={16} />
          </button>
        </div>
        <div className="inspector-tabs">
          {inspectorTabs.map((tab) => (
            <button key={tab.id} className={inspectorTab === tab.id ? "inspector-tab active" : "inspector-tab"} onClick={() => setInspectorTab(tab.id)}>
              <tab.icon size={15} />
              <span>{tab.label}</span>
            </button>
          ))}
        </div>

        <div className="inspector-panel">
          {inspectorTab === "status" && (
            <InspectorCard title="运行状态" icon={Activity}>
              <StatGrid
                items={[
                  ["Status", displayStatus],
                  ["Session", shortId(activeSessionId)],
                  ["Phase", activeSnapshot?.runtime_control?.status || activeSnapshot?.turn?.phase || "idle"],
                  ["Queue", String(activeSnapshot?.queued_message_count || 0)],
                  ["Artifacts", String(activeSnapshot?.runtime_control?.pending_artifact_count || 0)],
                  ["Mode", activeSnapshot?.cancel_requested ? "Canceling" : busy ? "Working" : "Idle"]
                ]}
              />
            </InspectorCard>
          )}

          {inspectorTab === "tools" && (
            <InspectorCard title="工具调用" icon={Code2}>
              <ul className="event-list">
                {activityItems.length === 0 && <li className="muted-event">暂无工具活动</li>}
                {activityItems.slice(-8).reverse().map((item, index) => (
                  <li key={`${item.label}-${index}`}>
                    <strong>{item.label}</strong>
                    <span>{item.detail}</span>
                  </li>
                ))}
              </ul>
            </InspectorCard>
          )}

          {inspectorTab === "approvals" && (
            <InspectorCard title="审批流" icon={ShieldCheck}>
              {activeApproval ? (
                <>
                  <p className="approval-kind">{activeApproval.title}</p>
                  <p className="muted">{activeApproval.description}</p>
                  {activeApproval.meta && <small className="approval-meta">{activeApproval.meta}</small>}
                  <code>{String(activeApproval.token).slice(0, 18)}</code>
                  <div className="split-actions">
                    <button disabled={Boolean(approvalAction)} onClick={approve}>
                      <Check size={15} /> {approvalAction?.token === activeApproval.token && approvalAction.action === "approve" ? "处理中..." : activeApproval.approveLabel}
                    </button>
                    <button disabled={Boolean(approvalAction)} onClick={reject}>
                      <X size={15} /> {approvalAction?.token === activeApproval.token && approvalAction.action === "reject" ? "处理中..." : "拒绝"}
                    </button>
                  </div>
                </>
              ) : (
                <p className="muted">{approvalFeedback || approvalEmptyText(busy, approvalSummary.count)}</p>
              )}
            </InspectorCard>
          )}

          <InspectorCard title="概览" icon={Monitor}>
            <dl className="compact-meta">
              <dt>消息</dt><dd>{activeSnapshot?.messages?.length || 0}</dd>
              <dt>事件</dt><dd>{activeEvents.length}</dd>
              <dt>审批</dt><dd>{approvalSummary.count}</dd>
              <dt>状态</dt><dd>{displayStatus}</dd>
            </dl>
          </InspectorCard>
        </div>
      </div>

      {workspaceDialogOpen ? (
        <WorkspaceDialog
          currentPath={workspace.active.path || ""}
          value={workspaceDraft}
          pendingWorkspace={pendingWorkspace}
          onChange={(value) => {
            setWorkspaceDraft(value);
            setPendingWorkspace(null);
          }}
          onClose={() => {
            setWorkspaceDialogOpen(false);
            setPendingWorkspace(null);
          }}
          onOpen={() => openWorkspace(workspaceDraft)}
          onConfirm={() => pendingWorkspace?.candidate?.path ? openWorkspace(pendingWorkspace.candidate.path, true) : undefined}
        />
      ) : null}

      {notice ? (
        <div className={`toast toast-${notice.tone}`}>
          <span>{notice.message}</span>
        </div>
      ) : null}
    </div>
  );
}

function ChatWorkspace({
  transcriptRef,
  transcript,
  activeSnapshot,
  activeSessionId,
  displayStatus,
  busy,
  prompt,
  promptSubmitting,
  activeApproval,
  setPrompt,
  sendPrompt,
  cancelActiveSession,
  activityItems,
  approvalSummary,
  approvalAction,
  approvalFeedback,
  approve,
  reject,
  inspectorTab,
  setInspectorTab,
  activeEvents,
  notice,
  inspectorOpen,
  setInspectorOpen
}: {
  transcriptRef: RefObject<HTMLElement>;
  transcript: TranscriptItem[];
  activeSnapshot?: SessionSnapshot;
  activeSessionId: string;
  displayStatus: string;
  busy: boolean;
  prompt: string;
  promptSubmitting: boolean;
  activeApproval: ActiveApproval | null;
  setPrompt: (value: string) => void;
  sendPrompt: () => void;
  cancelActiveSession: () => void;
  activityItems: Array<{ label: string; detail: string }>;
  approvalSummary: ApprovalsSummary;
  approvalAction: { token: string; action: "approve" | "reject" } | null;
  approvalFeedback: string;
  approve: () => void;
  reject: () => void;
  inspectorTab: InspectorTab;
  setInspectorTab: (tab: InspectorTab) => void;
  activeEvents: RuntimeEvent[];
  notice: Notice | null;
  inspectorOpen: boolean;
  setInspectorOpen: (value: boolean | ((current: boolean) => boolean)) => void;
}) {
  return (
    <div className={inspectorOpen ? "chat-layout with-inspector" : "chat-layout"}>
      <section className="chat-stage">
        <header className="chat-header">
          <div className="chat-header-copy">
            <div className="crumbs">
              <span>PP-ECHO / CHAT</span>
              <span>{shortId(activeSessionId)}</span>
            </div>
            <h2>{activeSnapshot?.history?.source === "stored" ? "历史会话" : "当前会话"}</h2>
            <p>{activeSnapshot?.messages?.length ? `${activeSnapshot.messages.length} 条消息` : "尚无消息"}</p>
          </div>

          <div className="chat-header-actions">
            <span className="status-pill">{displayStatus}</span>
            <button className="icon-button" onClick={() => setInspectorOpen((current) => !current)} title={inspectorOpen ? "收起观察窗" : "展开观察窗"}>
              <Activity size={15} />
            </button>
            <button onClick={cancelActiveSession} disabled={!busy}>
              <Square size={14} />
              停止
            </button>
          </div>
        </header>

        {notice ? <div className="inline-hint">{notice.message}</div> : null}

        <section className="transcript" ref={transcriptRef}>
          {transcript.length === 0 && (
            <div className="empty">
              <Sparkles size={26} />
              <h2>选择或创建一个会话</h2>
              <p>pp-Echo 的聊天、状态观察和工具调用会在这里一起展开。</p>
            </div>
          )}
          {transcript.map((item) => (
            <article className={`message ${item.role}${item.streaming ? " streaming" : ""}`} key={item.id}>
              <div className="avatar">{item.role === "assistant" ? <Bot size={16} /> : <MessageSquare size={15} />}</div>
              <div className="bubble">
                <span>{roleLabel(item.role)}</span>
                <RichMessageContent
                  text={item.body.text}
                  attachments={item.body.attachments}
                  streaming={item.streaming}
                  plain={activeSnapshot?.history?.source === "stored" && !item.streaming}
                />
              </div>
            </article>
          ))}
        </section>

        {activeApproval ? (
          <section className="composer-approval" aria-live="polite">
            <div className="composer-approval-copy">
              <p className="approval-kind">{activeApproval.title}</p>
              <p>{activeApproval.description}</p>
              <div className="composer-approval-meta">
                {activeApproval.meta ? <small>{activeApproval.meta}</small> : null}
                <code>{String(activeApproval.token).slice(0, 18)}</code>
              </div>
            </div>
            <div className="split-actions">
              <button disabled={Boolean(approvalAction)} onClick={approve}>
                <Check size={15} /> {approvalAction?.token === activeApproval.token && approvalAction.action === "approve" ? "处理中..." : activeApproval.approveLabel}
              </button>
              <button disabled={Boolean(approvalAction)} onClick={reject}>
                <X size={15} /> {approvalAction?.token === activeApproval.token && approvalAction.action === "reject" ? "处理中..." : "拒绝"}
              </button>
            </div>
          </section>
        ) : null}

        <footer className="composer">
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                sendPrompt();
              }
            }}
            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
            disabled={!activeSessionId || busy || Boolean(activeApproval)}
          />
          <button disabled={!activeSessionId || !prompt.trim() || Boolean(activeApproval) || busy || promptSubmitting} onClick={sendPrompt}>
            <Plus size={16} />
          </button>
        </footer>
      </section>
    </div>
  );
}

function ComingSoonPanel({
  title,
  onComingSoon,
  onReload
}: {
  title: string;
  onComingSoon: (label: string) => void;
  onReload: () => void;
}) {
  return (
    <section className="panel-page">
      <header className="panel-header">
        <div>
          <h2>{title}</h2>
          <p>功能开发中，敬请期待</p>
        </div>
        <button onClick={onReload}>
          <RefreshCw size={16} />
          刷新
        </button>
      </header>
      <div className="coming-soon">
        <Sparkles size={28} />
        <h3>功能开发中，敬请期待</h3>
        <p>这个页面已经保留，后续会继续补齐。</p>
        <button onClick={() => onComingSoon(title)}>提示一下</button>
      </div>
    </section>
  );
}

function TimelinePanel({
  activeSessionId,
  timeline,
  activeEvents,
  onReload
}: {
  activeSessionId: string;
  timeline: TimelineEntry[];
  activeEvents: RuntimeEvent[];
  onReload: () => void;
}) {
  const liveEvents = activeEvents.map(runtimeEventToTimelineLike);
  const items = latestAgentLoopItems([...timeline, ...liveEvents]);
  const text = formatTimelineText(items);

  return (
    <section className="panel-page timeline-page">
      <header className="panel-header">
        <div>
          <h2>Timeline</h2>
          <p>{activeSessionId ? `Session ${shortId(activeSessionId)}` : "Recent workspace events"}</p>
        </div>
        <button onClick={onReload}>
          <RefreshCw size={16} />
          刷新
        </button>
      </header>
      <textarea
        className="timeline-textbox"
        readOnly
        value={text || "暂无最近一轮 agent loop 事件"}
        aria-label="最近一轮 agent loop 时间线"
      />
    </section>
  );
}

function formatEventTime(value?: number) {
  if (!value) return "--:--:--";
  return new Date(value * 1000).toLocaleTimeString();
}

function latestAgentLoopItems(items: Array<TimelineEntry | ReturnType<typeof runtimeEventToTimelineLike>>) {
  const sorted = [...items]
    .filter((item) => item.created_at || item.event_type)
    .sort((left, right) => (left.created_at || 0) - (right.created_at || 0));
  const start = findLastIndex(sorted, (item) => item.event_type === "agent_start" || item.event_type === "local_user_prompt");
  return sorted.slice(Math.max(0, start)).slice(-160);
}

function runtimeEventToTimelineLike(event: RuntimeEvent, index: number) {
  return {
    id: `live-${index}`,
    created_at: event.timestamp || 0,
    event_type: event.type,
    turn_id: event.turn_id || 0,
    phase: event.phase,
    tool_name: event.tool_name,
    message: event.message,
    is_error: Boolean(event.is_error),
    details: event.details
  };
}

function formatTimelineText(items: Array<TimelineEntry | ReturnType<typeof runtimeEventToTimelineLike>>) {
  return items
    .map((item) => {
      const time = formatEventTime(item.created_at);
      const turn = item.turn_id ? ` turn=${item.turn_id}` : "";
      const phase = item.phase ? ` phase=${item.phase}` : "";
      const tool = item.tool_name ? ` tool=${item.tool_name}` : "";
      const error = item.is_error ? " ERROR" : "";
      const message = item.message ? ` | ${truncate(item.message, 180)}` : "";
      return `${time}${error}${turn}${phase}${tool} ${item.event_type}${message}`.trim();
    })
    .join("\n");
}

function WorkspaceDialog({
  currentPath,
  value,
  pendingWorkspace,
  onChange,
  onClose,
  onOpen,
  onConfirm
}: {
  currentPath: string;
  value: string;
  pendingWorkspace: OpenWorkspaceResponse | null;
  onChange: (value: string) => void;
  onClose: () => void;
  onOpen: () => void;
  onConfirm: () => void | Promise<void> | undefined;
}) {
  const canPickDirectory = typeof (window as DirectoryPickerWindow).showDirectoryPicker === "function";
  const [pickerHint, setPickerHint] = useState("");

  async function pickDirectory() {
    const picker = (window as DirectoryPickerWindow).showDirectoryPicker;
    if (!picker) return;
    const handle = await picker();
    const pickedPath = pickedDirectoryPath(handle);
    if (pickedPath) {
      setPickerHint("");
      onChange(pickedPath);
      return;
    }
    setPickerHint(`已选择「${handle.name}」，但浏览器没有暴露完整本地路径。请把文件夹的绝对路径粘贴到上方，例如 E:\\Projects\\my-app。`);
  }

  return (
    <div className="workspace-dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="workspace-dialog" role="dialog" aria-modal="true" aria-label="选择工作区" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div>
            <small>WORKSPACE</small>
            <h2>选择工作区</h2>
          </div>
          <button className="icon-button" onClick={onClose} title="关闭">
            <X size={16} />
          </button>
        </header>

        <div className="workspace-current">
          <span>当前</span>
          <strong>{currentPath || "本地工作区"}</strong>
        </div>

        <label className="workspace-path-field">
          <span>本地路径</span>
          <input
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") onOpen();
            }}
            placeholder="E:\\Projects\\my-app"
          />
        </label>

        <div className="workspace-dialog-actions">
          <button type="button" onClick={pickDirectory} disabled={!canPickDirectory} title={canPickDirectory ? "浏览器通常不会返回完整本地路径；选择后可能仍需粘贴绝对路径" : "当前浏览器不支持目录选择器"}>
            <FolderOpen size={16} />
            选择文件夹
          </button>
          <button type="button" onClick={onOpen}>
            <Check size={16} />
            打开
          </button>
        </div>

        {pendingWorkspace?.candidate ? (
          <div className="workspace-confirm">
            <div>
              <strong>确认打开这个工作区？</strong>
              <span>{pendingWorkspace.candidate.path}</span>
            </div>
            <button type="button" onClick={onConfirm}>
              确认
            </button>
          </div>
        ) : (
          <p className="workspace-dialog-note">{pickerHint || "请粘贴本地绝对路径。浏览器安全策略通常不会把“选择文件夹”的完整路径交给网页。"}</p>
        )}
      </section>
    </div>
  );
}

function InspectorCard({ title, icon: Icon, children }: { title: string; icon: typeof Activity; children: React.ReactNode }) {
  return (
    <div className="panel-card">
      <h3>
        <Icon size={16} /> {title}
      </h3>
      {children}
    </div>
  );
}

function StatGrid({ items }: { items: Array<[string, string]> }) {
  return (
    <dl className="compact-meta">
      {items.map(([label, value]) => (
        <div key={label} className="compact-meta-row">
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function pickedDirectoryPath(handle?: DirectoryPickerHandle | null) {
  if (!handle) return "";
  for (const key of ["path", "fullPath", "nativePath", "__path"] as const) {
    const value = handle[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function workspaceErrorMessage(error: unknown, attemptedPath: string) {
  const message = error instanceof Error ? error.message : String(error);
  if (message.includes("Workspace does not exist")) {
    return `工作区不存在：${attemptedPath}。请确认这里填写的是完整本地绝对路径，不是单独的文件夹名称。`;
  }
  if (message.includes("Workspace is not a directory")) {
    return `工作区不是文件夹：${attemptedPath}`;
  }
  if (message.includes("Workspace path cannot be empty")) {
    return "请输入工作区路径";
  }
  return message;
}

function filterSessions(items: SessionEntry[], query: string) {
  const clean = query.trim().toLowerCase();
  if (!clean) return items;
  return items.filter((item) => {
    const fields = [item.id, item.model, item.summary_preview, item.last_user_preview, item.last_assistant_preview].filter(Boolean).join(" ").toLowerCase();
    return fields.includes(clean);
  });
}

function computeSessionStats(items: SessionEntry[]) {
  return {
    total: items.length,
    active: items.filter((item) => Boolean(item.pending_plan_token)).length
  };
}

function readTheme(): ThemeMode {
  const stored = window.localStorage.getItem(STORAGE_THEME_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function readStoredView(): ViewKey {
  const stored = window.localStorage.getItem(STORAGE_ACTIVE_VIEW_KEY) as ViewKey | null;
  return stored === "history" || stored === "board" ? "chat" : stored || "chat";
}

function roleLabel(role: string) {
  if (role === "assistant") return "assistant";
  if (role === "user") return "user";
  return role;
}

export function buildTranscript(snapshot?: SessionSnapshot, events: RuntimeEvent[] = []): TranscriptItem[] {
  const committedMessages = snapshot?.messages || [];
  const stored: TranscriptItem[] = committedMessages
    .filter((message) => message.role === "user" || message.role === "assistant")
    .map((message, index) => ({
      id: `stored:${index}`,
      role: message.role,
      body: extractMessageBody(message),
      timestamp: typeof message.timestamp === "number" ? message.timestamp : index + 1
    }))
    .filter((item) => item.body.text.trim() || item.body.attachments.length > 0);

  const committedUsers = new Set(
    committedMessages
      .filter((message) => message.role === "user")
      .map((message) => normalizeText(extractMessageBody(message).text))
      .filter(Boolean)
  );
  const committedAssistants = committedMessages
    .filter((message) => message.role === "assistant")
    .map((message) => normalizeText(extractMessageBody(message).text))
    .filter(Boolean);

  const runtime: TranscriptItem[] = [];
  let streamBuffer = "";
  let streamIndex = 0;
  let streamTimestamp = 0;

  const flushStream = () => {
    const text = streamBuffer.trim();
    streamBuffer = "";
    if (!text) return;
    const normalized = normalizeText(text);
    const alreadyCommitted = committedAssistants.some((committed) => committed.includes(normalized) || normalized.includes(committed));
    if (!alreadyCommitted) {
      runtime.push({ id: `stream:${streamIndex++}`, role: "assistant", body: { text, attachments: [] }, streaming: true, timestamp: streamTimestamp || undefined });
    }
    streamTimestamp = 0;
  };

  for (const event of events) {
    if (event.type === "message_delta") {
      streamBuffer += event.delta || "";
      streamTimestamp = streamTimestamp || event.timestamp || 0;
      continue;
    }
    if (event.type === "local_user_prompt") {
      flushStream();
      const text = (event.message || "").trim();
      if (text && !committedUsers.has(normalizeText(text))) {
        runtime.push({ id: `local-user:${runtime.length}`, role: "user", body: { text, attachments: [] }, timestamp: event.timestamp });
      }
      continue;
    }
    if (event.type === "turn_end" || event.type === "agent_end" || event.type === "agent_start") {
      flushStream();
      continue;
    }
    if (event.is_error && event.message) {
      flushStream();
      runtime.push({ id: `error:${runtime.length}`, role: "error", body: { text: formatErrorEvent(event), attachments: [] }, timestamp: event.timestamp });
      continue;
    }
    if (event.type.includes("tool")) flushStream();
  }

  flushStream();
  const items = [...stored, ...runtime].sort((left, right) => {
    const leftTime = left.timestamp || 0;
    const rightTime = right.timestamp || 0;
    if (leftTime !== rightTime) return leftTime - rightTime;
    return 0;
  });
  if (shouldShowThinking(items, events)) {
    items.push({ id: "thinking", role: "assistant", body: { text: "Thinking", attachments: [] }, streaming: true });
  }
  return items;
}

function normalizeText(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function formatErrorEvent(event: RuntimeEvent) {
  const lines = [`ERROR: ${event.message || event.type}`];
  if (event.tool_name) lines.push(`tool: ${event.tool_name}`);
  if (event.type && event.type !== "error") lines.push(`event: ${event.type}`);
  const details = event.details || {};
  const errorType = details.error_type;
  const action = details.action;
  const source = details.source;
  if (typeof errorType === "string" && errorType) lines.push(`type: ${errorType}`);
  if (typeof action === "string" && action) lines.push(`action: ${action}`);
  if (typeof source === "string" && source) lines.push(`source: ${source}`);
  const error = details.error;
  if (typeof error === "string" && error && error !== event.message) lines.push(`detail: ${error}`);
  const attempts = details.attempts;
  if (Array.isArray(attempts) && attempts.length > 0) {
    lines.push("attempts:");
    attempts.slice(0, 6).forEach((attempt) => {
      if (!attempt || typeof attempt !== "object") return;
      const item = attempt as Record<string, unknown>;
      const provider = typeof item.provider === "string" ? item.provider : "provider";
      const status = typeof item.status === "string" ? item.status : "unknown";
      const message = typeof item.error === "string" ? ` - ${item.error}` : "";
      lines.push(`  - ${provider}: ${status}${message}`);
    });
  }
  const diagnostics = details.diagnostics;
  if (diagnostics && typeof diagnostics === "object") {
    const payload = diagnostics as Record<string, unknown>;
    const runtime = payload.runtime;
    const controller = payload.controller;
    appendDiagnosticLines(lines, "runtime", runtime);
    appendDiagnosticLines(lines, "controller", controller);
  }
  return lines.join("\n");
}

function appendDiagnosticLines(lines: string[], label: string, value: unknown) {
  if (!value || typeof value !== "object") return;
  const payload = value as Record<string, unknown>;
  const status = payload.status && typeof payload.status === "object" ? payload.status as Record<string, unknown> : payload;
  const interesting = ["controller", "running", "controller_ready", "cdp_port", "tabs_count", "last_error", "doctor_error"];
  const parts = interesting
    .map((key) => {
      const item = status[key];
      if (item === undefined || item === null || item === "") return "";
      return `${key}=${String(item)}`;
    })
    .filter(Boolean);
  if (parts.length > 0) lines.push(`${label}: ${parts.join(", ")}`);
  const recent = status.recent_actions;
  if (Array.isArray(recent) && recent.length > 0) {
    const tail = recent.slice(-3).map((item) => {
      if (!item || typeof item !== "object") return "";
      const action = (item as Record<string, unknown>).action || "action";
      const ok = (item as Record<string, unknown>).ok === true ? "ok" : "failed";
      const duration = (item as Record<string, unknown>).duration_ms;
      const error = (item as Record<string, unknown>).error;
      return `${String(action)}:${ok}${typeof duration === "number" ? ` ${duration}ms` : ""}${typeof error === "string" ? ` ${error}` : ""}`;
    }).filter(Boolean);
    if (tail.length > 0) lines.push(`${label} recent: ${tail.join(" | ")}`);
  }
}

function runtimeEventKey(event: RuntimeEvent) {
  const detailKey = event.details?.event_id || event.details?.id || event.details?.tool_call_id || event.details?.token || event.details?.artifact_id || "";
  return [
    event.type,
    event.turn_id ?? "",
    event.phase ?? "",
    event.timestamp ?? "",
    event.tool_name ?? "",
    event.message ?? "",
    event.delta ?? "",
    typeof detailKey === "string" || typeof detailKey === "number" ? detailKey : ""
  ].join("\u001f");
}

function shouldShowThinking(items: TranscriptItem[], events: RuntimeEvent[]) {
  if (!isTurnInFlight(events)) return false;
  const latestUserIndex = findLastIndex(items, (item) => item.role === "user");
  if (latestUserIndex < 0) return true;
  return !items.slice(latestUserIndex + 1).some((item) => item.role === "assistant" && item.body.text.trim() && item.id !== "thinking");
}

export function runtimeIsBusy(snapshot: SessionSnapshot | undefined, events: RuntimeEvent[]) {
  if (snapshot) return Boolean(snapshot.busy);
  return isTurnInFlight(events);
}

export function runtimeDisplayStatus(currentStatus: string, snapshot: SessionSnapshot | undefined, events: RuntimeEvent[]) {
  if (snapshot?.cancel_requested) return "Canceling";
  if (snapshot?.busy) return currentStatus;
  const terminal = latestTerminalEvent(events);
  if (hasErrorSinceLatestStart(events)) return "Failed";
  const phase = snapshot?.turn?.phase;
  if (phase === "idle") return terminal ? "Completed" : "Idle";
  if (terminal) return "Completed";
  return currentStatus === "tool_start" ? "Idle" : currentStatus;
}

export function isTurnInFlight(events: RuntimeEvent[]) {
  let inFlight = false;
  for (const event of events) {
    if (event.type === "local_user_prompt" || event.type === "agent_start" || event.type === "turn_start") inFlight = true;
    if (event.type === "turn_end" || event.type === "agent_end" || event.type === "error") inFlight = false;
  }
  return inFlight;
}

function latestTerminalEvent(events: RuntimeEvent[]) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event.type === "turn_end" || event.type === "agent_end" || event.type === "error" || event.is_error) return event;
  }
  return undefined;
}

function hasErrorSinceLatestStart(events: RuntimeEvent[]) {
  const latestStart = findLastIndex(events, (event) => event.type === "local_user_prompt" || event.type === "agent_start" || event.type === "turn_start");
  return events.slice(Math.max(0, latestStart)).some((event) => event.type === "error" || event.is_error);
}

export function buildActivityItems(events: RuntimeEvent[]) {
  const toolStarts = new Map<string, RuntimeEvent>();
  return events
    .filter((event) => event.type.includes("tool") || event.type.includes("planner") || event.type.includes("checkpoint") || event.type.includes("subagent") || event.type === "cancel_requested")
    .map((event) => {
      const key = toolEventKey(event);
      if (event.type === "tool_start" && key) toolStarts.set(key, event);
      return {
        label: event.tool_name || eventLabel(event),
        detail: summarizeEvent(event, key ? toolStarts.get(key) : undefined)
      };
    });
}

function eventLabel(event: RuntimeEvent) {
  const specName = event.details?.spec_name;
  if (typeof specName === "string" && specName.trim()) return specName;
  return event.type.replace(/_/g, " ");
}

function summarizeEvent(event: RuntimeEvent, toolStart?: RuntimeEvent) {
  const duration = toolDuration(event, toolStart);
  const durationSuffix = duration ? ` (${duration})` : "";
  if (event.plan_step?.title) return event.plan_step.title;
  if (event.message) return `${truncate(event.message, 92)}${durationSuffix}`;
  const preview = event.details?.preview;
  if (typeof preview === "string" && preview.trim()) return `${truncate(preview, 92)}${durationSuffix}`;
  const summary = event.details?.summary;
  if (typeof summary === "string" && summary.trim()) return `${truncate(summary, 92)}${durationSuffix}`;
  const childSession = event.details?.child_session_id || event.details?.session_id;
  const status = event.details?.status;
  if (typeof childSession === "string" && childSession.trim()) {
    const prefix = typeof status === "string" && status.trim() ? `${status}: ` : "";
    return `${prefix}child ${childSession.slice(0, 8)}${durationSuffix}`;
  }
  const completed = event.details?.completed;
  const total = event.details?.total;
  if (typeof completed === "number" && typeof total === "number") return `${completed}/${total}${durationSuffix}`;
  if (event.type === "tool_start") return "Started";
  if (event.type === "subagent_start") return "Started";
  if (event.type === "subagent_progress") return "Running";
  if (event.type === "subagent_end") return "Completed";
  if (event.type === "cancel_requested") return "Cancel requested";
  return event.is_error ? "Failed" : "Updated";
}

function toolEventKey(event: RuntimeEvent) {
  const callId = event.details?.tool_call_id;
  if (typeof callId === "string" && callId.trim()) return callId;
  return event.tool_name || "";
}

function toolDuration(event: RuntimeEvent, toolStart?: RuntimeEvent) {
  if (event.type !== "tool_end" && event.type !== "tool_result" && event.type !== "tool_error") return "";
  if (!toolStart?.timestamp || !event.timestamp) return "";
  const elapsedMs = Math.max(0, (event.timestamp - toolStart.timestamp) * 1000);
  if (elapsedMs < 1000) return "";
  return formatDuration(elapsedMs);
}

function formatDuration(elapsedMs: number) {
  const totalSeconds = Math.max(1, Math.round(elapsedMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes ? `${minutes}m ${seconds}s` : `${seconds}s`;
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
  const pending = summary.items.find(
    (item) => item.action_type !== "planner_approval" && isActionableApproval(item) && approvalBelongsToSession(item, sessionId, eventTokens)
  );
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

function isActionableApproval(item: PendingAction) {
  const state = item.lifecycle?.state || "";
  return ACTIONABLE_APPROVAL_STATES.has(state);
}

function approvalEmptyText(busy: boolean, workspaceApprovalCount: number) {
  if (busy) return "Plan accepted. Waiting for model output or an exact action confirmation.";
  if (workspaceApprovalCount > 0) return `${workspaceApprovalCount} pending approval(s) exist in this workspace.`;
  return "No pending approval for this session.";
}

function approvalTitle(actionType: string) {
  if (actionType === "apply_patch_artifact") return "apply isolated patch artifact";
  if (actionType === "write_file") return "apply staged write";
  if (actionType === "edit_file") return "apply staged edit";
  if (actionType === "run_shell") return "run staged command";
  return actionType.replace(/_/g, " ");
}

function approvalButtonLabel(actionType: string) {
  if (actionType === "apply_patch_artifact") return "Apply patch";
  if (actionType === "write_file") return "Apply write";
  if (actionType === "edit_file") return "Apply edit";
  if (actionType === "run_shell") return "Run command";
  return "Approve action";
}

function approvalSuccessMessage(actionType: string, result: ApprovalActionResponse) {
  if (actionType === "apply_patch_artifact") {
    const changedPaths = Array.isArray(result.details?.changed_paths)
      ? result.details.changed_paths.filter((value): value is string => typeof value === "string" && value.trim().length > 0)
      : [];
    return changedPaths.length > 0 ? `Patch applied successfully: ${changedPaths.join(", ")}` : "Patch artifact applied successfully.";
  }
  const path = result.details?.absolute_path || result.details?.path;
  if (actionType === "write_file" || actionType === "edit_file") {
    return typeof path === "string" && path.trim() ? `Applied successfully: ${path}` : "Applied successfully.";
  }
  if (actionType === "run_shell") return "Command completed.";
  return result.result || "Approval completed.";
}

function approvalDescription(item: PendingAction) {
  if (item.action_type === "apply_patch_artifact") {
    const details = item.details || {};
    const changedPaths = Array.isArray(details.changed_paths)
      ? details.changed_paths.filter((value): value is string => typeof value === "string" && value.trim().length > 0)
      : [];
    if (changedPaths.length > 0) {
      return `Changed paths: ${changedPaths.join(", ")}. Staged only; the main workspace updates after approval.`;
    }
    return "Isolated patch artifact is staged only; the main workspace updates after approval.";
  }
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
