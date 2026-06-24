import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import {
  Activity,
  ArrowDown,
  Bot,
  BookOpen,
  Boxes,
  Check,
  ChevronDown,
  ChevronRight,
  ChevronsUpDown,
  Clock3,
  Code2,
  Database,
  FileText,
  FolderOpen,
  GitBranch,
  LayoutDashboard,
  MessageSquare,
  Monitor,
  Paperclip,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  RefreshCw,
  Search,
  Send,
  Settings,
  ShieldCheck,
  Sparkles,
  Square,
  Sun,
  Trash2,
  Users,
  X
} from "lucide-react";
import { api, ApprovalActionResponse, ApprovalsSummary, AttachmentRecord, CapabilityInventory, ConfigField, ConfigSnapshot, CoreMemoryAuditRecord, CoreMemoryRecord, CoreMemorySnapshot, LogEntry, MemoryFileRead, MemorySearchResponse, MemoryStatus, OpenWorkspaceResponse, PendingAction, RuntimeEvent, SessionEntry, SessionSnapshot, TimelineEntry, WorkspaceGitStatus, WorkspaceStatus, WorkspacesState } from "./api";
import { extractMessageBody, RichMessageAttachments, RichMessageContent, sanitizeMediaUrl, type RichAttachment } from "./rich-text";
import { TraceInspectPage } from "./features/traces/TraceInspectPage";
import { StartupGuidePage } from "./features/onboarding/StartupGuidePage";
import { AttachmentPanel } from "./features/attachments/AttachmentPanel";
import { BotCenterPage } from "./features/bots/BotCenterPage";
import { SettingsCenter } from "./features/settings/SettingsCenter";
import { ActivityCard } from "./features/activity/ActivityCard";
import { ActivityDetailsPanel } from "./features/activity/ActivityDetailsPanel";
import { buildActivityRuns } from "./features/activity/activity-normalizer";
import type { ActivityItem } from "./features/activity/activity-types";

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
  | "attachments"
  | "bots"
  | "startupGuide"
  | "traceInspect"
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
  activity?: ActivityItem;
};

type ActivityEntry = {
  id: string;
  kind: "tool" | "command" | "planner" | "subagent" | "checkpoint" | "approval" | "event";
  label: string;
  detail: string;
  timestamp?: number;
  durationLabel?: string;
  tone?: "running" | "success" | "warning" | "error";
  attachments?: RichAttachment[];
};

type TurnMarker = {
  id: string;
  turnNumber: number;
  userPreview: string;
  assistantPreview: string;
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
const SCROLL_BOTTOM_THRESHOLD = 96;
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
  { view: "attachments", label: "附件", icon: Paperclip, description: "上传文件、检索、导入与记忆写入" },
  { view: "bots", label: "Bots", icon: Bot, description: "Bot Gateway and external message entry points" },
  { view: "traceInspect", label: "TraceInspect", icon: Activity, description: "Agent Trace 审计与回放" },
  { view: "usage", label: "用量", icon: Database, description: "运行统计" },
  { view: "skills", label: "技能", icon: ShieldCheck, description: "技能与规则" },
  { view: "users", label: "设置", icon: Settings, description: "系统设置" }
];

const shellNavGroups: Array<{ title: string; views: ViewKey[] }> = [
  { title: "对话", views: ["chat", "history", "group", "search"] },
  { title: "执行", views: ["workspace", "tasks", "board", "channels"] },
  { title: "扩展", views: ["plugins", "memory", "model"] },
  { title: "监控", views: ["logs", "attachments", "bots", "traceInspect", "usage", "skills", "users"] }
];

const sidebarNavSections: Array<{ title: string; views: ViewKey[] }> = [
  { title: "Conversations", views: ["chat", "history", "group", "search"] },
  { title: "Runtime", views: ["workspace", "tasks", "board", "channels"] },
  { title: "Extensions", views: ["plugins", "memory", "model", "skills"] },
  { title: "Observability", views: ["logs", "attachments", "traceInspect"] },
  { title: "Bots", views: ["bots"] },
  { title: "Usage", views: ["usage"] },
  { title: "Settings", views: ["users"] }
];

const comingSoonViews = new Set<ViewKey>(["search", "group", "tasks", "usage"]);

const inspectorTabs: Array<{ id: InspectorTab; label: string; icon: typeof Activity }> = [
  { id: "status", label: "状态", icon: Activity },
  { id: "tools", label: "工具", icon: Code2 },
  { id: "approvals", label: "审批", icon: ShieldCheck }
];

function BrandLogo() {
  return (
    <div className="brand-mark" aria-hidden="true">
      <svg viewBox="0 0 40 48" role="img">
        <path d="m25.09 5.05-3.93-1.05-3.31 12.37-2.99-11.17-3.93 1.05 3.23 12.07-8.05-8.05-2.88 2.88 8.83 8.83-11-2.95-1.05 3.93 12.02 3.22a8.3 8.3 0 0 1-.21-1.85 8.14 8.14 0 1 1 16.08-.16l10.92 2.93 1.05-3.93-12.07-3.23 11-2.95-1.05-3.93-12.07 3.23 8.05-8.05-2.88-2.88-8.71 8.71z" />
        <path d="m27.87 26.22c-.34 1.43-1.05 2.71-2.03 3.73l7.91 7.91 2.88-2.88z" />
        <path d="m25.77 30.04c-.99 1.01-2.24 1.76-3.64 2.15l2.88 10.75 3.93-1.05z" />
        <path d="m21.98 32.23a8.3 8.3 0 0 1-4.21-.04l-2.88 10.76 3.93 1.05z" />
        <path d="m17.64 32.15a8.15 8.15 0 0 1-3.58-2.18l-7.93 7.93 2.88 2.88z" />
        <path d="m14 29.9a8.1 8.1 0 0 1-1.98-3.69l-10.96 2.94 1.05 3.93z" />
      </svg>
    </div>
  );
}

export function App() {
  const [theme, setTheme] = useState<ThemeMode>(() => readTheme());
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [openNavGroup, setOpenNavGroup] = useState("0");
  const [workspace, setWorkspace] = useState<WorkspacesState>({ active: { name: "pp-Echo", path: "", exists: true, is_dir: true }, recent: [] });
  const [workspaceStatus, setWorkspaceStatus] = useState<WorkspaceStatus | null>(null);
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
  const [settingsDialogOpen, setSettingsDialogOpen] = useState(false);
  const [settingsFocus, setSettingsFocus] = useState("general");
  const [searchQuery, setSearchQuery] = useState("");
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [attachments, setAttachments] = useState<Record<string, AttachmentRecord[]>>({});
  const [attachmentUploading, setAttachmentUploading] = useState(false);

  const pollers = useRef<Record<string, number>>({});
  const eventSockets = useRef<Record<string, WebSocket>>({});
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
    const groupIndex = sidebarNavSections.findIndex((group) => group.views.includes(activeView));
    if (groupIndex >= 0) setOpenNavGroup(String(groupIndex));
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
  const activeSession = activeSessionId ? sessions.find((session) => session.id === activeSessionId) : undefined;
  const activeEvents = activeSessionId ? events[activeSessionId] || [] : [];
  const transcript = useMemo(() => buildTranscript(activeSnapshot, activeEvents), [activeSnapshot, activeEvents]);
  const activityItems = useMemo(() => buildActivityItems(activeEvents, activeSnapshot, approvalSummary), [activeEvents, activeSnapshot, approvalSummary]);
  const activeApproval = useMemo(() => buildActiveApproval(activeSnapshot, activeEvents, approvalSummary), [activeSnapshot, activeEvents, approvalSummary]);
  const busy = runtimeIsBusy(activeSnapshot, activeEvents);
  const displayStatus = runtimeDisplayStatus(status, activeSnapshot, activeEvents);
  const filteredSessions = useMemo(() => filterSessions(sessions, searchQuery), [sessions, searchQuery]);
  const sessionStats = useMemo(() => computeSessionStats(sessions), [sessions]);
  const viewLabel = navItems.find((item) => item.view === activeView)?.label || "会话";
  const viewMeta = navItems.find((item) => item.view === activeView);
  const middleMode = activeView === "history" ? "sessions" : activeView === "board" ? "observer" : null;

  async function refreshAll() {
    const [workspaceState, workspaceMeta, sessionList, approvals] = await Promise.all([api.workspaces(), api.workspaceStatus(), api.sessions(), api.approvals()]);
    setWorkspace(workspaceState);
    setWorkspaceStatus(workspaceMeta);
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
    refreshAttachments(snapshot.session_id);
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
    if (eventSockets.current[sessionId] || pollers.current[sessionId]) return;
    if (connectEventSocket(sessionId)) return;
    startEventPolling(sessionId);
  }

  function connectEventSocket(sessionId: string) {
    if (!("WebSocket" in window)) return false;
    try {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(`${protocol}//${window.location.host}/api/sessions/${encodeURIComponent(sessionId)}/events`);
      eventSockets.current[sessionId] = socket;
      socket.onopen = () => {
        setStatus("Live events connected");
        const poller = pollers.current[sessionId];
        if (poller) {
          window.clearInterval(poller);
          delete pollers.current[sessionId];
        }
      };
      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data) as RuntimeEvent;
          appendEvent(sessionId, event);
          if (event.type === "turn_end" || event.type === "agent_end" || event.type === "error" || event.type.includes("gate")) {
            refreshSessionState(sessionId).catch(() => undefined);
          }
        } catch {
          // Ignore malformed websocket payloads and let the next event/snapshot recover the UI.
        }
      };
      socket.onerror = () => {
        socket.close();
      };
      socket.onclose = () => {
        if (eventSockets.current[sessionId] === socket) delete eventSockets.current[sessionId];
        if (!pollers.current[sessionId]) startEventPolling(sessionId);
      };
      return true;
    } catch {
      return false;
    }
  }

  function startEventPolling(sessionId: string) {
    if (pollers.current[sessionId]) return;
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
      const key = runtimeEventDedupeKey(event);
      if (key && existing.some((item) => runtimeEventDedupeKey(item) === key)) return current;
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

  async function refreshAttachments(sessionId: string) {
    if (!sessionId) return;
    try {
      const payload = await api.listAttachments(sessionId);
      setAttachments((current) => ({ ...current, [sessionId]: payload.attachments }));
    } catch {
      setAttachments((current) => ({ ...current, [sessionId]: current[sessionId] || [] }));
    }
  }

  async function uploadAttachment(file: File) {
    if (!activeSessionId || attachmentUploading) return;
    setAttachmentUploading(true);
    try {
      await api.uploadAttachment(activeSessionId, file);
      await refreshAttachments(activeSessionId);
      showNotice("Attachment uploaded", "success");
    } catch (error) {
      showNotice(error instanceof Error ? error.message : String(error), "warning");
    } finally {
      setAttachmentUploading(false);
    }
  }

  async function deleteAttachment(attachmentId: string) {
    if (!activeSessionId) return;
    try {
      await api.deleteAttachment(activeSessionId, attachmentId);
      await refreshAttachments(activeSessionId);
      showNotice("Attachment deleted", "success");
    } catch (error) {
      showNotice(error instanceof Error ? error.message : String(error), "warning");
    }
  }

  function openView(view: ViewKey) {
    if (view === "workspace") {
      setWorkspaceDialogOpen(true);
      setWorkspaceDraft(workspace.active.path || "");
      return;
    }
    if (view === "users" || view === "model") {
      setSettingsFocus(view === "users" ? "general" : view);
      setSettingsDialogOpen(true);
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
    if (item && comingSoonViews.has(view)) {
      showNotice(`${item.label} 功能开发中，敬请期待`, "info");
    }
  }

  function stopPolling() {
    Object.values(pollers.current).forEach((poller) => window.clearInterval(poller));
    pollers.current = {};
    Object.values(eventSockets.current).forEach((socket) => socket.close());
    eventSockets.current = {};
  }

  function stopSessionPolling(sessionId: string) {
    const poller = pollers.current[sessionId];
    if (poller) {
      window.clearInterval(poller);
      delete pollers.current[sessionId];
    }
    const socket = eventSockets.current[sessionId];
    if (socket) {
      delete eventSockets.current[sessionId];
      socket.close();
    }
  }

  function stopPollingExcept(sessionId: string) {
    Object.entries(pollers.current).forEach(([key, poller]) => {
      if (key === sessionId) return;
      window.clearInterval(poller);
      delete pollers.current[key];
    });
    Object.entries(eventSockets.current).forEach(([key, socket]) => {
      if (key === sessionId) return;
      delete eventSockets.current[key];
      socket.close();
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
    setAttachments({});
    setPrompt("");
    setWorkspaceStatus(null);
    setApprovalSummary({ count: 0, items: [] });
    const [workspaceMeta, sessionList, approvals] = await Promise.all([api.workspaceStatus(), api.sessions(), api.approvals()]);
    setWorkspaceStatus(workspaceMeta);
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
    let approvalTargetSessionId = activeSessionId;
    setApprovalAction({ token: approval.token, action: "approve" });
    setApprovalFeedback("");
    try {
      if (approval.kind === "planner" && activeSessionId) {
        await api.approve(activeSessionId);
        clearPlannerToken(activeSessionId);
        const message = "Plan approved. Waiting for the concrete action.";
        setApprovalFeedback(message);
        appendEvent(activeSessionId, {
          type: "approval_result",
          session_id: activeSessionId,
          message,
          timestamp: Date.now() / 1000,
          details: { action_type: "planner_approval", token: approval.token, success: true }
        });
        ensureEventPolling(activeSessionId);
      } else {
        const result = await api.approvePending(approval.token);
        approvalTargetSessionId = result.session_id || approvalTargetSessionId;
        removeApproval(approval.token);
        const message = approvalSuccessMessage(approval.actionType || "", result);
        setApprovalFeedback(message);
        setStatus(message);
        if (activeSessionId) {
          appendEvent(activeSessionId, {
            type: "approval_result",
            session_id: activeSessionId,
            message,
            timestamp: Date.now() / 1000,
            details: {
              action_type: approval.actionType || result.action_type,
              token: approval.token,
              success: result.success !== false,
              result: result.result,
              lifecycle: result.lifecycle,
              approval_details: result.details
            }
          });
          if (result.success !== false && result.resumed !== true && result.session_id === activeSessionId) {
            setStatus("Continuing after approved action");
            try {
              await api.continueSession(activeSessionId);
              ensureEventPolling(activeSessionId);
            } catch (continueError) {
              const continueMessage = continueError instanceof Error ? continueError.message : String(continueError);
              setStatus(`Approved, but continue failed: ${continueMessage}`);
              showNotice(`审批已执行，但自动继续失败：${continueMessage}`, "warning");
            }
          }
        }
        if (result.resumed === false && result.session_id) {
          await api.continueSession(result.session_id);
          ensureEventPolling(result.session_id);
        }
      }
      await refreshApprovals();
      if (approvalTargetSessionId) await refreshSessionState(approvalTargetSessionId);
      if (activeSessionId && activeSessionId !== approvalTargetSessionId) await refreshSessionState(activeSessionId);
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
    <div className={`app-shell theme-${theme} ${middleMode ? `mode-${middleMode}` : "mode-chat"} ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <aside className="app-nav">
        <div className="app-brand">
          <button className="brand-button" onClick={() => openView("startupGuide")} title="启动指引">
            <BrandLogo />
            <div className="brand-copy">
              <strong>pp-Echo</strong>
              <span>{workspace.active.path || "本地工作区"}</span>
            </div>
          </button>
          <button className="icon-button" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} title="切换主题">
            <Sun size={15} />
          </button>
          <button
            className="icon-button"
            onClick={() => setSidebarCollapsed((current) => !current)}
            title={sidebarCollapsed ? "Open sidebar" : "Close sidebar"}
          >
            {sidebarCollapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
          </button>
        </div>

        <nav className="nav-groups">
          {sidebarNavSections.map((group, index) => {
            const groupKey = String(index);
            const isOpen = openNavGroup === groupKey;
            const firstItem = navItems.find((entry) => entry.view === group.views[0])!;
            const GroupIcon = firstItem.icon;
            const groupActive = group.views.includes(activeView);
            const isSingleItem = group.views.length === 1;
            return (
            <section className={groupActive ? "nav-group active" : "nav-group"} key={group.title}>
              <button
                className={isOpen || groupActive ? "nav-parent open" : "nav-parent"}
                type="button"
                onClick={() => {
                  if (isSingleItem) {
                    openView(group.views[0]);
                    return;
                  }
                  setOpenNavGroup(isOpen ? "" : groupKey);
                }}
              >
                <GroupIcon size={16} />
                <span>{group.title}</span>
                {isSingleItem ? <ChevronRight size={14} /> : isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </button>
              {isOpen && !isSingleItem && !sidebarCollapsed ? <div className="nav-group-items">
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
              </div> : null}
            </section>
            );
          })}
        </nav>

        <div className="app-nav-footer">
          <button className="team-switcher-card" onClick={() => openView("workspace")} type="button">
            <div className="team-icon">
              <FolderOpen size={15} />
            </div>
            <div className="team-copy">
              <strong>{workspaceStatus?.name || workspace.active.name || "pp-Echo"}</strong>
              <span>{workspaceStatus?.git_branch || "workspace"}</span>
            </div>
            <ChevronsUpDown size={14} />
          </button>
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
        {activeView === "chat" || activeView === "history" || activeView === "board" ? null : (
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
        )}

        <div className={`canvas-body canvas-body-${activeView}`}>
          {activeView === "startupGuide" ? (
            <StartupGuidePage
              onBack={() => setActiveView("chat")}
              onOpenTrace={() => setActiveView("traceInspect")}
              onOpenChat={() => setActiveView("chat")}
            />
          ) : activeView === "chat" || activeView === "history" || activeView === "board" ? (
            <ChatWorkspace
              transcriptRef={transcriptRef}
              transcript={transcript}
              activeSnapshot={activeSnapshot}
              workspace={workspace}
              workspaceStatus={workspaceStatus}
              activeModel={activeSession?.model || ""}
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
              attachments={activeSessionId ? attachments[activeSessionId] || [] : []}
              attachmentUploading={attachmentUploading}
              approve={approve}
              reject={reject}
              refreshAttachments={() => activeSessionId ? refreshAttachments(activeSessionId) : undefined}
              uploadAttachment={uploadAttachment}
              deleteAttachment={deleteAttachment}
              openAttachments={() => setActiveView("attachments")}
              inspectorTab={inspectorTab}
              setInspectorTab={setInspectorTab}
              activeEvents={activeEvents}
              notice={notice}
              inspectorOpen={inspectorOpen}
              setInspectorOpen={setInspectorOpen}
              onWorkspaceChanged={() => refreshAll().catch(() => undefined)}
              onModelChanged={() => {
                refreshAll().catch(() => undefined);
                if (activeSessionId) refreshSessionState(activeSessionId).catch(() => undefined);
              }}
            />
          ) : activeView === "traceInspect" ? (
            <TraceInspectPage
              activeSessionId={activeSessionId}
              onBack={() => setActiveView("chat")}
            />
          ) : activeView === "attachments" ? (
            <AttachmentWorkbench
              activeSessionId={activeSessionId}
              attachments={activeSessionId ? attachments[activeSessionId] || [] : []}
              uploading={attachmentUploading}
              onRefresh={() => activeSessionId ? refreshAttachments(activeSessionId) : undefined}
              onDelete={deleteAttachment}
              onUpload={uploadAttachment}
            />
          ) : activeView === "bots" ? (
            <BotCenterPage />
          ) : activeView === "logs" ? (
            <ObservabilityPanel
              activeSessionId={activeSessionId}
              timeline={timeline}
              activeEvents={activeEvents}
              onReload={refreshTimeline}
            />
          ) : activeView === "skills" || activeView === "plugins" || activeView === "channels" ? (
            <CapabilityWorkbench
              initialTab={activeView === "skills" ? "skills" : activeView === "plugins" ? "plugins" : "mcp"}
              workspaceStatus={workspaceStatus}
              activeSessionId={activeSessionId}
            />
          ) : activeView === "memory" ? (
            <MemoryWorkbench />
          ) : activeView === "users" ? (
            <SettingsCenter
              sessionId={activeSessionId}
              initialCategory={settingsFocus}
              onOpenCapabilities={() => setActiveView("channels")}
              onSaved={() => {
                refreshAll().catch(() => undefined);
                if (activeSessionId) refreshSessionState(activeSessionId).catch(() => undefined);
              }}
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
            <ActivityDetailsPanel items={activityItems} />
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
                <p className="muted">{approvalFeedback || approvalEmptyText(busy, approvalSummary.active_count ?? approvalSummary.count)}</p>
              )}
            </InspectorCard>
          )}

          <InspectorCard title="概览" icon={Monitor}>
            <dl className="compact-meta">
              <dt>消息</dt><dd>{activeSnapshot?.messages?.length || 0}</dd>
              <dt>事件</dt><dd>{activeEvents.length}</dd>
              <dt>审批</dt><dd>{approvalSummary.active_count ?? approvalSummary.count}</dd>
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
          onOpenPath={(path) => openWorkspace(path)}
          onConfirm={() => pendingWorkspace?.candidate?.path ? openWorkspace(pendingWorkspace.candidate.path, true) : undefined}
        />
      ) : null}

      {settingsDialogOpen ? (
        <DynamicSettingsDialog
          sessionId={activeSessionId}
          initialCategory={settingsFocus}
          onClose={() => setSettingsDialogOpen(false)}
          onSaved={() => {
            refreshAll().catch(() => undefined);
            if (activeSessionId) refreshSessionState(activeSessionId).catch(() => undefined);
          }}
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

const settingsCategoryLabels: Record<string, string> = {
  general: "General",
  model: "Model",
  skills: "Skills",
  plugins: "Plugins",
  tools: "Tools",
  memory: "Memory",
  browser_web: "Browser/Web",
  subagents: "Subagents",
  storage: "Storage",
  learning: "Learning"
};

function DynamicSettingsDialog({
  sessionId,
  initialCategory,
  onClose,
  onSaved
}: {
  sessionId: string;
  initialCategory: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [snapshot, setSnapshot] = useState<ConfigSnapshot | null>(null);
  const [category, setCategory] = useState(initialCategory);
  const [scope, setScope] = useState<"project" | "profile" | "session">(sessionId ? "session" : "project");
  const [profileDraft, setProfileDraft] = useState("");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [jsonDraft, setJsonDraft] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    setCategory(initialCategory);
  }, [initialCategory]);

  useEffect(() => {
    loadConfig().catch((err) => applyConfigError(err, setError, setFieldErrors));
  }, [sessionId]);

  useEffect(() => {
    if (!snapshot) return;
    setJsonDraft(JSON.stringify(readScopeConfig(snapshot, scope, profileDraft), null, 2));
  }, [scope, profileDraft, snapshot]);

  async function loadConfig() {
    const payload = await api.config(sessionId || undefined);
    setSnapshot(payload);
    setProfileDraft(payload.active_profile || payload.profiles[0] || "default");
    setDrafts(buildConfigDrafts(payload));
    setJsonDraft(JSON.stringify(readScopeConfig(payload, scope), null, 2));
    setError("");
    setFieldErrors({});
    setNotice("");
  }

  async function applyChanges() {
    if (!snapshot) return;
    const dirtyFields = fields.filter((field) => isFieldDirty(snapshot, drafts, field, scope, profileDraft));
    if (!dirtyFields.length) return;
    if (scope === "session" && !sessionId) {
      setError("Open a session before applying session overrides.");
      return;
    }
    const profileName = profileDraft.trim();
    if (scope === "profile" && !profileName) {
      setError("Profile name is required.");
      return;
    }
    setSaving(true);
    setError("");
    setFieldErrors({});
    try {
      let updated = snapshot;
      let baseHash = snapshot.config_hash;
      for (const field of dirtyFields) {
        const value = parseFieldDraft(drafts[field.path], field.type);
        if (scope === "session" && sessionId) {
          updated = await api.sessionConfigSet(sessionId, field.path, value);
        } else if (scope === "profile") {
          updated = await api.configProfileSet(profileName, field.path, value, baseHash, sessionId || undefined);
        } else {
          updated = await api.configSet(field.path, value, baseHash);
        }
        baseHash = updated.config_hash;
      }
      setSnapshot(updated);
      setDrafts(buildConfigDrafts(updated));
      setProfileDraft(updated.active_profile || profileName || updated.profiles[0] || "default");
      setNotice(scope === "session" ? "Session override saved; takes effect on the next turn." : "Configuration saved.");
      onSaved();
    } catch (err) {
      applyConfigError(err, setError, setFieldErrors);
    } finally {
      setSaving(false);
    }
  }

  async function applyJson() {
    if (!snapshot) return;
    setSaving(true);
    setError("");
    setFieldErrors({});
    try {
      const parsed = JSON.parse(jsonDraft || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("JSON must be an object.");
      const updated = await api.configPatch(parsed as Record<string, unknown>, snapshot.config_hash);
      setSnapshot(updated);
      setDrafts(buildConfigDrafts(updated));
      setNotice("JSON patch saved.");
      onSaved();
    } catch (err) {
      applyConfigError(err, setError, setFieldErrors);
    } finally {
      setSaving(false);
    }
  }

  async function switchProfile(value: string) {
    if (!snapshot) return;
    setSaving(true);
    setError("");
    setFieldErrors({});
    try {
      const nextProfile = value || null;
      const updated = scope === "session" && sessionId
        ? await api.setSessionProfile(sessionId, nextProfile)
        : await api.setProjectProfile(nextProfile, snapshot.config_hash, sessionId || undefined);
      setSnapshot(updated);
      setProfileDraft(updated.active_profile || "");
      setDrafts(buildConfigDrafts(updated));
      setNotice(nextProfile ? `Profile switched to ${nextProfile}.` : "Profile cleared.");
      onSaved();
    } catch (err) {
      applyConfigError(err, setError, setFieldErrors);
    } finally {
      setSaving(false);
    }
  }

  function revertDrafts() {
    if (!snapshot) return;
    setDrafts(buildConfigDrafts(snapshot));
    setJsonDraft(JSON.stringify(readScopeConfig(snapshot, scope, profileDraft), null, 2));
    setError("");
    setFieldErrors({});
  }

  const savingPath = saving ? "__batch__" : "";
  async function saveField(field: ConfigField) {
    if (!snapshot) return;
    setSaving(true);
    setError("");
    try {
      const value = parseFieldDraft(drafts[field.path], field.type);
      const updated = field.path === "model.model" && sessionId
        ? await api.setSessionModel(sessionId, String(value))
        : await api.configSet(field.path, value, snapshot.config_hash);
      setSnapshot(updated);
      setDrafts(buildConfigDrafts(updated));
      onSaved();
    } catch (err) {
      applyConfigError(err, setError, setFieldErrors);
    } finally {
      setSaving(false);
    }
  }

  const fields = snapshot?.schema.fields || [];
  const categories = ["general", "model", "skills", "plugins", "tools", "memory", "browser_web", "subagents", "storage", "learning"]
    .filter((item) => item === "general" || fields.some((field) => field.category === item));
  const visibleFields = category === "general"
    ? fields.filter((field) => ["provider.base_url", "tool_policy.confirm_high_risk_plan", "capabilities.builtin_tools.enable"].includes(field.path))
    : fields.filter((field) => field.category === category);
  const dirtyCount = snapshot ? fields.filter((field) => isFieldDirty(snapshot, drafts, field, scope, profileDraft)).length : 0;
  const reloadTone = snapshot?.reload_policy || "hot";

  return (
    <div className="settings-dialog-backdrop">
      <section className="settings-dialog settings-workbench">
        <header className="settings-dialog-head">
          <div>
            <small>CONFIG</small>
            <h2>Dynamic settings</h2>
            <p>{snapshot ? `effective ${snapshot.effective_hash.slice(0, 12)} · project ${snapshot.config_hash.slice(0, 12)}` : "Loading"}</p>
          </div>
          {snapshot ? (
            <div className="settings-head-meta">
              <span className={`reload-badge reload-${reloadTone}`}>{snapshot.reload_policy}</span>
              <span>{snapshot.active_profile || "no profile"}</span>
            </div>
          ) : null}
          <button className="icon-button" onClick={onClose} title="Close">
            <X size={16} />
          </button>
        </header>

        <div className="settings-dialog-body">
          <nav className="settings-category-list">
            <div className="settings-scope-panel">
              <span>Scope</span>
              <div className="segmented-control">
                <button className={scope === "project" ? "active" : ""} onClick={() => setScope("project")}>Project</button>
                <button className={scope === "profile" ? "active" : ""} onClick={() => setScope("profile")}>Profile</button>
                <button className={scope === "session" ? "active" : ""} onClick={() => setScope("session")} disabled={!sessionId}>Session</button>
              </div>
              <select value={snapshot?.active_profile || ""} onChange={(event) => switchProfile(event.target.value)} disabled={!snapshot || saving}>
                <option value="">No active profile</option>
                {(snapshot?.profiles || []).map((profile) => <option key={profile} value={profile}>{profile}</option>)}
              </select>
              {scope === "profile" ? (
                <input value={profileDraft} onChange={(event) => setProfileDraft(event.target.value)} placeholder="profile name" />
              ) : null}
            </div>
            {categories.map((item) => (
              <button key={item} className={category === item ? "active" : ""} onClick={() => setCategory(item)}>
                {settingsCategoryLabels[item] || item}
              </button>
            ))}
          </nav>

          <div className="settings-editor">
            <div className="settings-editor-toolbar">
              <div>
                <strong>{settingsCategoryLabels[category] || category}</strong>
                <span>{scopeLabel(scope, profileDraft, sessionId)}</span>
              </div>
              <button onClick={loadConfig} disabled={saving}>
                <RefreshCw size={14} /> Reload
              </button>
            </div>
            {error ? <p className="settings-error">{error}</p> : null}
            {notice ? <p className="settings-success">{notice}</p> : null}
            {snapshot?.pending_effects?.length ? (
              <div className="settings-pending">
                {snapshot.pending_effects.slice(0, 5).map((effect) => <span key={effect}>{effect}</span>)}
              </div>
            ) : null}
            {!snapshot ? <p className="muted">Loading config...</p> : null}
            {snapshot && visibleFields.map((field) => {
              const dirty = isFieldDirty(snapshot, drafts, field, scope, profileDraft);
              const source = snapshot.source_map[field.path] || "default/env";
              const fieldError = fieldErrors[field.path];
              return (
                <div className={`settings-field ${dirty ? "dirty" : ""} ${fieldError ? "invalid" : ""}`} key={field.path}>
                  <div className="settings-field-copy">
                    <strong>{field.path}</strong>
                    <span>{source} · {field.reload_policy}</span>
                    {field.description ? <em>{field.description}</em> : null}
                    {fieldError ? <b>{fieldError}</b> : null}
                  </div>
                  {renderConfigInput(field, drafts[field.path] || "", (value) => setDrafts((current) => ({ ...current, [field.path]: value })))}
                  <span className="settings-field-state">{dirty ? "Changed" : "Synced"}</span>
                </div>
              );
            })}
            {advancedOpen && snapshot ? (
              <div className="settings-json-editor">
                <div>
                  <strong>Advanced JSON</strong>
                  <span>{scope === "project" ? "Project patch editor" : "Read-only layer preview"}</span>
                </div>
                <textarea value={jsonDraft} onChange={(event) => setJsonDraft(event.target.value)} readOnly={scope !== "project"} />
                {scope === "project" ? <button onClick={applyJson} disabled={saving}>Apply JSON</button> : null}
              </div>
            ) : null}
          </div>
        </div>
        <footer className="settings-action-bar">
          <button onClick={() => setAdvancedOpen((value) => !value)}>{advancedOpen ? "Hide JSON" : "Advanced JSON"}</button>
          <span>{dirtyCount} pending change{dirtyCount === 1 ? "" : "s"}</span>
          <button onClick={revertDrafts} disabled={!dirtyCount || saving}>Revert</button>
          <button onClick={revertDrafts} disabled={!dirtyCount || saving}>Reset</button>
          <button className="primary" onClick={applyChanges} disabled={!dirtyCount || saving}>{saving ? "Applying" : "Apply"}</button>
        </footer>
      </section>
    </div>
  );
}

function SettingsDialog({
  sessionId,
  initialCategory,
  onClose,
  onSaved
}: {
  sessionId: string;
  initialCategory: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [snapshot, setSnapshot] = useState<ConfigSnapshot | null>(null);
  const [category, setCategory] = useState(initialCategory);
  const [scope, setScope] = useState<"project" | "profile" | "session">(sessionId ? "session" : "project");
  const [profileDraft, setProfileDraft] = useState("");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [jsonDraft, setJsonDraft] = useState("");

  useEffect(() => {
    setCategory(initialCategory);
  }, [initialCategory]);

  useEffect(() => {
    loadConfig().catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [sessionId]);

  async function loadConfig() {
    const payload = await api.config(sessionId || undefined);
    setSnapshot(payload);
    setProfileDraft(payload.active_profile || payload.profiles[0] || "default");
    setDrafts(buildConfigDrafts(payload));
    setJsonDraft(JSON.stringify(readScopeConfig(payload, scope), null, 2));
    setError("");
    setFieldErrors({});
  }

  useEffect(() => {
    if (!snapshot) return;
    setJsonDraft(JSON.stringify(readScopeConfig(snapshot, scope, profileDraft), null, 2));
  }, [scope, profileDraft, snapshot]);

  async function applyChanges() {
    if (!snapshot) return;
    const dirtyFields = fields.filter((field) => isFieldDirty(snapshot, drafts, field, scope, profileDraft));
    if (dirtyFields.length === 0) return;
    if (scope === "session" && !sessionId) {
      setError("Open a session before applying session overrides.");
      return;
    }
    const profileName = profileDraft.trim();
    if (scope === "profile" && !profileName) {
      setError("Profile name is required.");
      return;
    }
    setSaving(true);
    setError("");
    setFieldErrors({});
    try {
      let updated = snapshot;
      let baseHash = snapshot.config_hash;
      for (const field of dirtyFields) {
        const value = parseFieldDraft(drafts[field.path], field.type);
        if (scope === "session" && sessionId) {
          updated = await api.sessionConfigSet(sessionId, field.path, value);
        } else if (scope === "profile") {
          updated = await api.configProfileSet(profileName, field.path, value, baseHash, sessionId || undefined);
        } else {
          updated = await api.configSet(field.path, value, baseHash);
        }
        baseHash = updated.config_hash;
      }
      setSnapshot(updated);
      setDrafts(buildConfigDrafts(updated));
      setProfileDraft(updated.active_profile || profileName || updated.profiles[0] || "default");
      onSaved();
    } catch (err) {
      applyConfigError(err, setError, setFieldErrors);
    } finally {
      setSaving(false);
    }
  }

  async function applyJson() {
    if (!snapshot) return;
    setSaving(true);
    setError("");
    setFieldErrors({});
    try {
      const parsed = JSON.parse(jsonDraft || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("JSON must be an object.");
      const updated = await api.configPatch(parsed as Record<string, unknown>, snapshot.config_hash);
      setSnapshot(updated);
      setDrafts(buildConfigDrafts(updated));
      onSaved();
    } catch (err) {
      applyConfigError(err, setError, setFieldErrors);
    } finally {
      setSaving(false);
    }
  }

  async function switchProfile(value: string) {
    if (!snapshot) return;
    setSaving(true);
    setError("");
    try {
      const nextProfile = value || null;
      const updated = scope === "session" && sessionId
        ? await api.setSessionProfile(sessionId, nextProfile)
        : await api.setProjectProfile(nextProfile, snapshot.config_hash, sessionId || undefined);
      setSnapshot(updated);
      setProfileDraft(updated.active_profile || "");
      setDrafts(buildConfigDrafts(updated));
      onSaved();
    } catch (err) {
      applyConfigError(err, setError, setFieldErrors);
    } finally {
      setSaving(false);
    }
  }

  function revertDrafts() {
    if (!snapshot) return;
    setDrafts(buildConfigDrafts(snapshot));
    setJsonDraft(JSON.stringify(readScopeConfig(snapshot, scope, profileDraft), null, 2));
    setError("");
    setFieldErrors({});
  }

  const savingPath = saving ? "__batch__" : "";
  async function saveField(field: ConfigField) {
    if (!snapshot) return;
    setSaving(true);
    setError("");
    try {
      const value = parseFieldDraft(drafts[field.path], field.type);
      const updated = field.path === "model.model" && sessionId
        ? await api.setSessionModel(sessionId, String(value))
        : await api.configSet(field.path, value, snapshot.config_hash);
      setSnapshot(updated);
      setDrafts(buildConfigDrafts(updated));
      onSaved();
    } catch (err) {
      applyConfigError(err, setError, setFieldErrors);
    } finally {
      setSaving(false);
    }
  }

  const fields = snapshot?.schema.fields || [];
  const categories = ["general", "model", "skills", "plugins", "tools", "memory", "browser_web", "subagents", "storage", "learning"]
    .filter((item) => item === "general" || fields.some((field) => field.category === item));
  const visibleFields = category === "general"
    ? fields.filter((field) => ["provider.base_url", "tool_policy.confirm_high_risk_plan", "capabilities.builtin_tools.enable"].includes(field.path))
    : fields.filter((field) => field.category === category);
  const dirtyCount = snapshot ? fields.filter((field) => isFieldDirty(snapshot, drafts, field, scope, profileDraft)).length : 0;
  const reloadTone = snapshot?.reload_policy || "hot";

  return (
    <div className="settings-dialog-backdrop">
      <section className="settings-dialog">
        <header className="settings-dialog-head">
          <div>
            <small>CONFIG</small>
            <h2>Dynamic settings</h2>
            <p>{snapshot ? `hash ${snapshot.config_hash.slice(0, 12)} · ${snapshot.reload_policy}` : "Loading"}</p>
          </div>
          <button className="icon-button" onClick={onClose} title="Close">
            <X size={16} />
          </button>
        </header>

        <div className="settings-dialog-body">
          <nav className="settings-category-list">
            {categories.map((item) => (
              <button key={item} className={category === item ? "active" : ""} onClick={() => setCategory(item)}>
                {settingsCategoryLabels[item] || item}
              </button>
            ))}
          </nav>

          <div className="settings-editor">
            <div className="settings-editor-toolbar">
              <strong>{settingsCategoryLabels[category] || category}</strong>
              <button onClick={loadConfig}>
                <RefreshCw size={14} /> Reload
              </button>
            </div>
            {error ? <p className="settings-error">{error}</p> : null}
            {!snapshot ? <p className="muted">Loading config...</p> : null}
            {snapshot && visibleFields.map((field) => {
              const dirty = drafts[field.path] !== stringifyConfigValue(readConfigPath(snapshot.settings, field.path));
              const source = snapshot.source_map[field.path] || "default/env";
              return (
                <div className="settings-field" key={field.path}>
                  <div className="settings-field-copy">
                    <strong>{field.path}</strong>
                    <span>{source} · {field.reload_policy}</span>
                  </div>
                  {field.type === "boolean" ? (
                    <label className="settings-toggle">
                      <input
                        type="checkbox"
                        checked={drafts[field.path] === "true"}
                        onChange={(event) => setDrafts((current) => ({ ...current, [field.path]: String(event.target.checked) }))}
                      />
                    </label>
                  ) : (
                    <input
                      value={drafts[field.path] || ""}
                      onChange={(event) => setDrafts((current) => ({ ...current, [field.path]: event.target.value }))}
                    />
                  )}
                  <button disabled={!dirty || savingPath === field.path} onClick={() => saveField(field)}>
                    {savingPath === field.path ? "Saving" : "Save"}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      </section>
    </div>
  );
}

function ChatWorkspace({
  transcriptRef,
  transcript,
  activeSnapshot,
  workspace,
  workspaceStatus,
  activeModel,
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
  attachments,
  attachmentUploading,
  approve,
  reject,
  refreshAttachments,
  uploadAttachment,
  deleteAttachment,
  openAttachments,
  inspectorTab,
  setInspectorTab,
  activeEvents,
  notice,
  inspectorOpen,
  setInspectorOpen,
  onWorkspaceChanged,
  onModelChanged
}: {
  transcriptRef: RefObject<HTMLElement>;
  transcript: TranscriptItem[];
  activeSnapshot?: SessionSnapshot;
  workspace: WorkspacesState;
  workspaceStatus: WorkspaceStatus | null;
  activeModel: string;
  activeSessionId: string;
  displayStatus: string;
  busy: boolean;
  prompt: string;
  promptSubmitting: boolean;
  activeApproval: ActiveApproval | null;
  setPrompt: (value: string) => void;
  sendPrompt: () => void;
  cancelActiveSession: () => void;
  activityItems: ActivityItem[];
  approvalSummary: ApprovalsSummary;
  approvalAction: { token: string; action: "approve" | "reject" } | null;
  approvalFeedback: string;
  attachments: AttachmentRecord[];
  attachmentUploading: boolean;
  approve: () => void;
  reject: () => void;
  refreshAttachments: () => void;
  uploadAttachment: (file: File) => void;
  deleteAttachment: (attachmentId: string) => void;
  openAttachments: () => void;
  inspectorTab: InspectorTab;
  setInspectorTab: (tab: InspectorTab) => void;
  activeEvents: RuntimeEvent[];
  notice: Notice | null;
  inspectorOpen: boolean;
  setInspectorOpen: (value: boolean | ((current: boolean) => boolean)) => void;
  onWorkspaceChanged: () => void;
  onModelChanged: () => void;
}) {
  const [showScrollToBottom, setShowScrollToBottom] = useState(false);
  const [activeTurnId, setActiveTurnId] = useState("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const nearBottomRef = useRef(true);
  const turnMarkers = useMemo(() => buildTurnMarkers(transcript), [transcript]);
  const transcriptTailKey = useMemo(() => {
    const tail = transcript[transcript.length - 1];
    return tail ? `${tail.id}:${tail.body.text.length}:${tail.streaming ? "streaming" : "done"}` : "empty";
  }, [transcript]);

  useEffect(() => {
    const target = transcriptRef.current;
    if (!target) return;

    const updateScrollState = () => {
      const distanceFromBottom = target.scrollHeight - target.scrollTop - target.clientHeight;
      const nearBottom = distanceFromBottom <= SCROLL_BOTTOM_THRESHOLD;
      nearBottomRef.current = nearBottom;
      setShowScrollToBottom(!nearBottom && transcript.length > 0);
      setActiveTurnId(findActiveTurnId(target, turnMarkers));
    };

    updateScrollState();
    target.addEventListener("scroll", updateScrollState, { passive: true });
    return () => target.removeEventListener("scroll", updateScrollState);
  }, [transcriptRef, transcript.length, turnMarkers]);

  useEffect(() => {
    const target = transcriptRef.current;
    if (!target || !nearBottomRef.current) return;
    window.requestAnimationFrame(() => {
      target.scrollTo({ top: target.scrollHeight, behavior: "smooth" });
    });
  }, [transcriptRef, transcriptTailKey]);

  useEffect(() => {
    const target = textareaRef.current;
    if (!target) return;
    target.style.height = "auto";
    target.style.height = `${target.scrollHeight}px`;
  }, [prompt]);

  useEffect(() => {
    const target = transcriptRef.current;
    if (!target) return;
    window.requestAnimationFrame(() => {
      target.scrollTop = target.scrollHeight;
      nearBottomRef.current = true;
      setShowScrollToBottom(false);
      setActiveTurnId(turnMarkers[turnMarkers.length - 1]?.id || "");
    });
  }, [activeSessionId, transcriptRef]);

  const scrollToBottom = () => {
    const target = transcriptRef.current;
    if (!target) return;
    target.scrollTo({ top: target.scrollHeight, behavior: "smooth" });
  };

  const jumpToTurn = (marker: TurnMarker) => {
    const target = transcriptRef.current;
    const element = target ? findTranscriptElement(target, marker.id) : null;
    if (!target || !element) return;
    target.scrollTo({ top: Math.max(0, element.offsetTop - 16), behavior: "smooth" });
    setActiveTurnId(marker.id);
  };

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
            <article className={`message ${item.role}${item.streaming ? " streaming" : ""}`} key={item.id} data-transcript-id={item.id}>
              <div className="avatar">{item.role === "assistant" ? <Bot size={16} /> : item.role === "activity" ? <Code2 size={15} /> : <MessageSquare size={15} />}</div>
              {item.role === "activity" && item.activity ? (
                <ActivityCard item={item.activity} />
              ) : (
                <div className="bubble">
                  <span>{roleLabel(item.role)}</span>
                  <RichMessageContent
                    text={item.body.text}
                    attachments={item.body.attachments}
                    streaming={item.streaming}
                    plain={activeSnapshot?.history?.source === "stored" && !item.streaming}
                  />
                </div>
              )}
            </article>
          ))}
        </section>
        <ConversationTurnRail markers={turnMarkers} activeTurnId={activeTurnId} onJump={jumpToTurn} />
        {showScrollToBottom ? (
          <button className="scroll-to-bottom" onClick={scrollToBottom} title="滚动到底部" aria-label="滚动到底部">
            <ArrowDown size={17} />
          </button>
        ) : null}

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

        <footer className="composer-shell">
          <div className="composer-input-card">
          <input
            ref={fileInputRef}
            type="file"
            className="attachment-input"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) uploadAttachment(file);
              event.currentTarget.value = "";
            }}
          />
          <button
            className="composer-icon-button"
            disabled={!activeSessionId || busy || Boolean(activeApproval) || attachmentUploading}
            onClick={() => fileInputRef.current?.click()}
            title="Upload attachment"
            type="button"
          >
            <Plus size={15} />
          </button>
          <button
            className="composer-pill-button"
            disabled={!activeSessionId}
            onClick={openAttachments}
            title="Open attachments"
            type="button"
          >
            <FileText size={14} />
            <span>Files</span>
          </button>
          <textarea
            ref={textareaRef}
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            onInput={(event) => {
              const target = event.currentTarget;
              target.style.height = "auto";
              target.style.height = `${target.scrollHeight}px`;
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                sendPrompt();
              }
            }}
            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
            disabled={!activeSessionId || busy || Boolean(activeApproval)}
            rows={1}
          />
          <button className="composer-send-button" disabled={!activeSessionId || !prompt.trim() || Boolean(activeApproval) || busy || promptSubmitting} onClick={sendPrompt} title="Send message" type="button">
            <Send size={14} />
          </button>
          </div>
        </footer>
        <AttachmentStrip attachments={attachments} uploading={attachmentUploading} onDelete={deleteAttachment} />
        <div className="composer-statusbar">
          <span>
            <FolderOpen size={14} />
            {workspaceStatus?.name || workspace.active.name || "workspace"}
          </span>
          <ComposerGitBranchButton workspaceStatus={workspaceStatus} onChanged={onWorkspaceChanged} />
          <ComposerModelButton activeSessionId={activeSessionId} activeModel={activeModel} onChanged={onModelChanged} />
        </div>
      </section>
    </div>
  );
}

function ComposerGitBranchButton({
  workspaceStatus,
  onChanged
}: {
  workspaceStatus: WorkspaceStatus | null;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [git, setGit] = useState<WorkspaceGitStatus | null>(null);
  const [query, setQuery] = useState("");
  const [newBranch, setNewBranch] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    loadGit();
  }, [open]);

  async function loadGit() {
    setError("");
    try {
      setGit(await api.workspaceGit());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function switchBranch(branch: string) {
    if (git?.dirty_count && !window.confirm("Workspace has local changes. Git switch will keep them, but conflicts can still block the switch. Continue?")) return;
    setBusy(branch);
    setError("");
    try {
      const next = await api.switchGitBranch(branch);
      setGit(next);
      onChanged();
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  async function createBranch() {
    const branch = newBranch.trim();
    if (!branch) return;
    setBusy("create");
    setError("");
    try {
      const next = await api.createGitBranch(branch);
      setGit(next);
      setNewBranch("");
      onChanged();
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  const branches = (git?.branches || []).filter((branch) => branch.name.toLowerCase().includes(query.trim().toLowerCase()));
  const label = git?.current_branch || workspaceStatus?.git_branch || "no branch";
  const dirty = git?.dirty_count ?? workspaceStatus?.git_dirty_count ?? 0;

  return (
    <div className="composer-popover-wrap">
      <button className="composer-status-button" onClick={() => setOpen((current) => !current)} type="button">
        <GitBranch size={14} />
        <span>{label}</span>
        {dirty ? <em>{dirty}</em> : null}
        <ChevronDown size={13} />
      </button>
      {open ? (
        <div className="composer-popover branch-popover">
          <label className="composer-popover-search">
            <Search size={14} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search branches" />
          </label>
          {error ? <div className="composer-popover-error">{error}</div> : null}
          {!git?.is_repo ? <div className="composer-popover-empty">This workspace is not a git repository.</div> : null}
          {git?.is_repo ? (
            <>
              <div className="composer-popover-section">Branches</div>
              <div className="composer-popover-list">
                {branches.map((branch) => (
                  <button key={branch.name} onClick={() => switchBranch(branch.name)} disabled={Boolean(busy)} type="button">
                    <GitBranch size={14} />
                    <span>
                      <strong>{branch.name}</strong>
                      <small>{branch.upstream || (git.dirty_count ? `${git.dirty_count} changed files` : "clean")}</small>
                    </span>
                    {branch.current ? <Check size={15} /> : null}
                  </button>
                ))}
              </div>
              <div className="composer-popover-create">
                <input value={newBranch} onChange={(event) => setNewBranch(event.target.value)} placeholder="Create new branch" />
                <button onClick={createBranch} disabled={!newBranch.trim() || Boolean(busy)} type="button">
                  <Plus size={14} /> Create
                </button>
              </div>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function ComposerModelButton({
  activeSessionId,
  activeModel,
  onChanged
}: {
  activeSessionId: string;
  activeModel: string;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<ConfigSnapshot | null>(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    api.config(activeSessionId || undefined).then(setSnapshot).catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [open, activeSessionId]);

  const models = useMemo(() => modelCandidates(snapshot, activeModel), [snapshot, activeModel]);
  const filteredModels = models.filter((model) => model.toLowerCase().includes(query.trim().toLowerCase()));
  const effortField = snapshot?.schema.fields.find((field) => /reasoning|effort|thinking/i.test(field.path) && field.options?.length);

  async function chooseModel(model: string) {
    setBusy(model);
    setError("");
    try {
      if (activeSessionId) {
        await api.setSessionModel(activeSessionId, model);
      } else {
        const baseHash = snapshot?.config_hash;
        await api.configSet("model.model", model, baseHash);
      }
      onChanged();
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  async function chooseEffort(value: string) {
    if (!effortField || !snapshot) return;
    setBusy(value);
    setError("");
    try {
      if (activeSessionId && effortField.session_override) {
        await api.sessionConfigSet(activeSessionId, effortField.path, value);
      } else {
        await api.configSet(effortField.path, value, snapshot.config_hash);
      }
      onChanged();
      setSnapshot(await api.config(activeSessionId || undefined));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="composer-popover-wrap">
      <button className="composer-status-button" onClick={() => setOpen((current) => !current)} type="button">
        <Monitor size={14} />
        <span>{activeModel || "model pending"}</span>
        <ChevronDown size={13} />
      </button>
      {open ? (
        <div className="composer-popover model-popover">
          <label className="composer-popover-search">
            <Search size={14} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search models" />
          </label>
          {error ? <div className="composer-popover-error">{error}</div> : null}
          {effortField?.options?.length ? (
            <>
              <div className="composer-popover-section">Reasoning</div>
              <div className="composer-segment-row">
                {effortField.options.map((option) => (
                  <button key={option} onClick={() => chooseEffort(option)} disabled={Boolean(busy)} type="button">{option}</button>
                ))}
              </div>
            </>
          ) : null}
          <div className="composer-popover-section">Models</div>
          <div className="composer-popover-list">
            {filteredModels.map((model) => (
              <button key={model} onClick={() => chooseModel(model)} disabled={Boolean(busy)} type="button">
                <Monitor size={14} />
                <span>
                  <strong>{model}</strong>
                  <small>{modelProviderLabel(model)}</small>
                </span>
                {model === activeModel ? <Check size={15} /> : null}
              </button>
            ))}
            {!filteredModels.length ? <div className="composer-popover-empty">No models match this search.</div> : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function modelCandidates(snapshot: ConfigSnapshot | null, activeModel: string) {
  const values = new Set<string>();
  const modelField = snapshot?.schema.fields.find((field) => field.path === "model.model");
  modelField?.options?.forEach((option) => values.add(option));
  const configured = snapshot ? readConfigPath(snapshot.effective_config, "model.model") : "";
  if (typeof configured === "string" && configured.trim()) values.add(configured.trim());
  if (activeModel.trim()) values.add(activeModel.trim());
  return Array.from(values).filter(Boolean);
}

function modelProviderLabel(model: string) {
  const lower = model.toLowerCase();
  if (lower.includes("qwen")) return "Qwen";
  if (lower.includes("deepseek")) return "DeepSeek";
  if (lower.includes("gpt") || lower.includes("o3") || lower.includes("o4")) return "OpenAI";
  if (lower.includes("claude")) return "Anthropic";
  return "Model";
}

function ConversationTurnRail({
  markers,
  activeTurnId,
  onJump
}: {
  markers: TurnMarker[];
  activeTurnId: string;
  onJump: (marker: TurnMarker) => void;
}) {
  if (markers.length < 2) return null;
  return (
    <nav className="turn-rail" aria-label="对话轮次导航">
      {markers.map((marker) => (
        <button
          className={`turn-marker${marker.id === activeTurnId ? " active" : ""}`}
          key={marker.id}
          onClick={() => onJump(marker)}
          title={`第 ${marker.turnNumber} 轮`}
          aria-label={`跳转到第 ${marker.turnNumber} 轮`}
        >
          <span className="turn-marker-line" />
          <span className="turn-preview" role="tooltip">
            <strong>第 {marker.turnNumber} 轮</strong>
            <span>{marker.userPreview || "用户消息"}</span>
            {marker.assistantPreview ? <em>{marker.assistantPreview}</em> : null}
          </span>
        </button>
      ))}
    </nav>
  );
}

function AttachmentWorkbench({
  activeSessionId,
  attachments,
  uploading,
  onRefresh,
  onDelete,
  onUpload
}: {
  activeSessionId: string;
  attachments: AttachmentRecord[];
  uploading: boolean;
  onRefresh: () => void;
  onDelete: (attachmentId: string) => void;
  onUpload: (file: File) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  return (
    <section className="attachment-workbench">
      <input
        ref={inputRef}
        type="file"
        className="attachment-input"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onUpload(file);
          event.currentTarget.value = "";
        }}
      />
      <div className="attachment-workbench-toolbar">
        <div>
          <strong>{attachments.length} attachments</strong>
          <span>{activeSessionId ? shortId(activeSessionId) : "no active session"}</span>
        </div>
        <button type="button" onClick={() => inputRef.current?.click()} disabled={!activeSessionId || uploading}>
          <Paperclip size={15} /> Upload
        </button>
        <button type="button" onClick={onRefresh} disabled={!activeSessionId}>
          <RefreshCw size={15} /> Refresh
        </button>
      </div>
      {activeSessionId ? (
        <AttachmentPanel sessionId={activeSessionId} attachments={attachments} onRefresh={onRefresh} onDelete={onDelete} />
      ) : (
        <div className="empty-state">Create or select a session before uploading attachments.</div>
      )}
    </section>
  );
}

function AttachmentStrip({
  attachments,
  uploading,
  onDelete
}: {
  attachments: AttachmentRecord[];
  uploading: boolean;
  onDelete: (attachmentId: string) => void;
}) {
  if (!uploading && attachments.length === 0) return null;
  return (
    <div className="attachment-strip" aria-live="polite">
      {uploading ? (
        <span className="attachment-chip loading">
          <Paperclip size={14} />
          Uploading
        </span>
      ) : null}
      {attachments.map((attachment) => (
        <span className={`attachment-chip ${attachment.status}`} key={attachment.attachment_id} title={attachment.text_preview || attachment.error || attachment.stored_filename}>
          <Paperclip size={14} />
          <span className="attachment-chip-main">
            <strong>{attachment.stored_filename}</strong>
            <small>{attachment.kind} · {formatBytes(attachment.size_bytes)} · {attachment.status}</small>
          </span>
          <button type="button" onClick={() => onDelete(attachment.attachment_id)} title="Delete attachment">
            <Trash2 size={13} />
          </button>
        </span>
      ))}
    </div>
  );
}

function ToolActivityBlock({ item }: { item: TranscriptItem }) {
  const activity = item.activity;
  if (!activity) return null;
  const entries = activity.entries || [];
  const commandCount = entries.filter((entry) => entry.kind === "command").length;
  return (
    <details className={`tool-activity ${activity.tone || "success"}`}>
      <summary>
        <span className="tool-activity-status">{activity.title}</span>
        <ChevronRight size={14} />
      </summary>
      <div className="tool-activity-detail">
        {activity.summary ? <p className="tool-activity-summary">{activity.summary}</p> : null}
        {commandCount > 0 ? <p className="tool-activity-command-count">已运行 {commandCount} 条命令</p> : null}
        {entries.length > 0 ? (
          <ol className="tool-activity-steps">
            {entries.map((entry) => (
              <li className={`tool-activity-step ${entry.tone || "success"}`} key={entry.id}>
                <div className="tool-activity-step-head">
                  <span>{entry.label}</span>
                  {entry.durationLabel ? <small>{entry.durationLabel}</small> : null}
                  {entry.tone === "running" ? <small>运行中</small> : null}
                </div>
                {entry.detail ? <pre>{entry.detail}</pre> : null}
                {entry.attachments?.length ? <RichMessageAttachments attachments={entry.attachments} /> : null}
              </li>
            ))}
          </ol>
        ) : (
          <pre>{activity.detail}</pre>
        )}
      </div>
      {entries.length === 0 ? <RichMessageAttachments attachments={item.body.attachments} /> : null}
    </details>
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

function ObservabilityPanel({
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
  const [tab, setTab] = useState<"timeline" | "logs">("timeline");
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [sources, setSources] = useState<string[]>([]);
  const [level, setLevel] = useState("all");
  const [source, setSource] = useState("all");
  const [search, setSearch] = useState("");
  const [follow, setFollow] = useState(true);
  const [selectedLogKey, setSelectedLogKey] = useState("");
  const [error, setError] = useState("");
  const liveEvents = activeEvents.map(runtimeEventToTimelineLike);
  const items = latestAgentLoopItems([...timeline, ...liveEvents]);
  const text = formatTimelineText(items);

  async function reloadLogs() {
    try {
      setError("");
      const payload = await api.logs({ level, source, search, sessionId: activeSessionId || undefined, limit: 300 });
      setLogs(payload.logs);
      setSources(payload.sources);
      if (follow) {
        setSelectedLogKey(payload.logs.length ? logEntryKey(payload.logs[payload.logs.length - 1], payload.logs.length - 1) : "");
      } else if (selectedLogKey && !payload.logs.some((entry, index) => logEntryKey(entry, index) === selectedLogKey)) {
        setSelectedLogKey(payload.logs.length ? logEntryKey(payload.logs[Math.min(payload.logs.length - 1, 0)], 0) : "");
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError));
    }
  }

  useEffect(() => {
    if (tab !== "logs") return;
    reloadLogs().catch(() => undefined);
  }, [tab, level, source, activeSessionId]);

  useEffect(() => {
    if (tab !== "logs" || !follow) return;
    const timer = window.setInterval(() => reloadLogs().catch(() => undefined), 2500);
    return () => window.clearInterval(timer);
  }, [tab, follow, level, source, activeSessionId, search]);

  return (
    <section className="panel-page timeline-page">
      <header className="panel-header">
        <div>
          <h2>Observability</h2>
          <p>{activeSessionId ? `Session ${shortId(activeSessionId)}` : "Recent workspace events and persistent logs"}</p>
        </div>
        <div className="segmented-actions">
          <button className={tab === "timeline" ? "active" : ""} onClick={() => setTab("timeline")}>Timeline</button>
          <button className={tab === "logs" ? "active" : ""} onClick={() => setTab("logs")}>Logs</button>
        </div>
      </header>
      {tab === "timeline" ? (
        <>
          <div className="observability-toolbar">
            <span>{items.length} events</span>
            <button onClick={onReload}>
              <RefreshCw size={16} />
              Refresh
            </button>
          </div>
          <textarea
            className="timeline-textbox"
            readOnly
            value={text || "No recent agent loop timeline events."}
            aria-label="Recent agent loop timeline"
          />
        </>
      ) : (
        <LogsPanel
          logs={logs}
          sources={sources}
          level={level}
          source={source}
          search={search}
          follow={follow}
          selectedLogKey={selectedLogKey}
          error={error}
          setLevel={setLevel}
          setSource={setSource}
          setSearch={setSearch}
          setFollow={setFollow}
          setSelectedLogKey={setSelectedLogKey}
          onReload={reloadLogs}
        />
      )}
    </section>
  );
}

function LogsPanel({
  logs,
  sources,
  level,
  source,
  search,
  follow,
  selectedLogKey,
  error,
  setLevel,
  setSource,
  setSearch,
  setFollow,
  setSelectedLogKey,
  onReload
}: {
  logs: LogEntry[];
  sources: string[];
  level: string;
  source: string;
  search: string;
  follow: boolean;
  selectedLogKey: string;
  error: string;
  setLevel: (value: string) => void;
  setSource: (value: string) => void;
  setSearch: (value: string) => void;
  setFollow: (value: boolean) => void;
  setSelectedLogKey: (value: string) => void;
  onReload: () => void;
}) {
  const selectedIndex = Math.max(0, logs.findIndex((entry, index) => logEntryKey(entry, index) === selectedLogKey));
  const selected = logs[Math.min(selectedIndex, Math.max(0, logs.length - 1))];
  return (
    <div className="logs-workbench">
      <div className="observability-toolbar logs-toolbar">
        <select value={level} onChange={(event) => setLevel(event.target.value)}>
          {["all", "debug", "info", "warning", "error", "critical"].map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <select value={source} onChange={(event) => setSource(event.target.value)}>
          <option value="all">all sources</option>
          {sources.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <input value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => event.key === "Enter" && onReload()} placeholder="Search logs" />
        <label className="inline-check">
          <input type="checkbox" checked={follow} onChange={(event) => setFollow(event.target.checked)} />
          Follow
        </label>
        <button onClick={onReload}>
          <RefreshCw size={16} />
          Refresh
        </button>
      </div>
      {error ? <p className="settings-error">{error}</p> : null}
      <div className="logs-grid">
        <div className="log-list">
          {logs.length ? logs.map((entry, index) => (
            <button
              key={logEntryKey(entry, index)}
              className={logEntryKey(entry, index) === selectedLogKey ? "log-row active" : "log-row"}
              onClick={() => {
                setFollow(false);
                setSelectedLogKey(logEntryKey(entry, index));
              }}
            >
              <span>{formatLogTime(entry.timestamp)}</span>
              <em className={`log-level level-${String(entry.level || "info").toLowerCase()}`}>{entry.level || "info"}</em>
              <strong>{entry.source || "log"}</strong>
              <p>{entry.message || entry.raw || ""}</p>
            </button>
          )) : (
            <div className="empty-state">
              <FileText size={24} />
              <strong>No logs match the current filters</strong>
              <span>pp-Echo checked timeline events, session JSONL files, and .pp-agent/logs/*.log and *.jsonl.</span>
            </div>
          )}
        </div>
        <aside className="log-detail">
          {selected ? (
            <>
              <div className="log-detail-head">
                <strong>{selected.source}</strong>
                <span className={`log-level level-${String(selected.level || "info").toLowerCase()}`}>{selected.level || "info"}</span>
              </div>
              <p>{selected.message}</p>
              <pre>{JSON.stringify({ timestamp: selected.timestamp, session_id: selected.session_id, details: selected.details, raw: selected.raw }, null, 2)}</pre>
              <button onClick={() => navigator.clipboard?.writeText(selected.raw || selected.message || "")}>Copy</button>
            </>
          ) : (
            <span>Select a log row to inspect details.</span>
          )}
        </aside>
      </div>
    </div>
  );
}

function logEntryKey(entry: LogEntry, index: number) {
  return [
    entry.timestamp ?? "",
    entry.session_id ?? "",
    entry.source ?? "",
    entry.level ?? "",
    entry.message ?? entry.raw ?? "",
    index,
  ].join("\u001f");
}

function MemoryWorkbench() {
  const [status, setStatus] = useState<MemoryStatus | null>(null);
  const [corePending, setCorePending] = useState<CoreMemoryRecord[]>([]);
  const [coreActive, setCoreActive] = useState<CoreMemoryRecord[]>([]);
  const [coreSnapshot, setCoreSnapshot] = useState<CoreMemorySnapshot | null>(null);
  const [coreAudit, setCoreAudit] = useState<CoreMemoryAuditRecord[]>([]);
  const [selectedCoreId, setSelectedCoreId] = useState("");
  const [providerStatus, setProviderStatus] = useState<Record<string, unknown> | null>(null);
  const [automationResult, setAutomationResult] = useState<Record<string, unknown> | null>(null);
  const [selectedPath, setSelectedPath] = useState("");
  const [selectedFile, setSelectedFile] = useState<MemoryFileRead | null>(null);
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("auto");
  const [searchResult, setSearchResult] = useState<MemorySearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const files = status?.files || [];

  async function reload() {
    try {
      setError("");
      const [nextStatus, pendingPayload, activePayload, snapshotPayload, auditPayload, providerPayload] = await Promise.all([
        api.memoryStatus(),
        api.coreMemoryPending(),
        api.coreMemoryActive(),
        api.coreMemorySnapshot(),
        api.coreMemoryAudit(selectedCoreId || undefined, 80),
        api.coreMemoryProviderStatus()
      ]);
      setStatus(nextStatus);
      setCorePending(pendingPayload.pending);
      setCoreActive(activePayload.active);
      setCoreSnapshot(snapshotPayload);
      setCoreAudit(auditPayload.audit);
      setProviderStatus(providerPayload);
      const nextPath = selectedPath || nextStatus.files[0]?.path || "";
      setSelectedPath(nextPath);
      if (nextPath) {
        setSelectedFile(await api.memoryFile(nextPath, 1, 220));
      } else {
        setSelectedFile(null);
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError));
    }
  }

  async function refreshCore(memoryId = selectedCoreId) {
    const [pendingPayload, activePayload, snapshotPayload, auditPayload] = await Promise.all([
      api.coreMemoryPending(),
      api.coreMemoryActive(),
      api.coreMemorySnapshot(),
      api.coreMemoryAudit(memoryId || undefined, 80)
    ]);
    setCorePending(pendingPayload.pending);
    setCoreActive(activePayload.active);
    setCoreSnapshot(snapshotPayload);
    setCoreAudit(auditPayload.audit);
  }

  async function actOnCoreMemory(action: "approve" | "reject" | "archive", memoryId: string) {
    try {
      setError("");
      if (action === "approve") await api.approveCoreMemory(memoryId);
      if (action === "reject") await api.rejectCoreMemory(memoryId);
      if (action === "archive") await api.archiveCoreMemory(memoryId);
      setSelectedCoreId(memoryId);
      await refreshCore(memoryId);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError));
    }
  }

  async function runAutomation(action: "merge-preview" | "merge-apply" | "compact-preview" | "compact-apply") {
    try {
      setError("");
      const result =
        action === "merge-preview" ? await api.coreMemoryMergePreview()
        : action === "merge-apply" ? await api.coreMemoryMergeApply()
        : action === "compact-preview" ? await api.coreMemoryCompactPreview()
        : await api.coreMemoryCompactApply();
      setAutomationResult(result);
      await refreshCore();
      setProviderStatus(await api.coreMemoryProviderStatus());
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError));
    }
  }

  async function readFile(path: string, startLine = 1) {
    try {
      setError("");
      setSelectedPath(path);
      setSelectedFile(await api.memoryFile(path, startLine, 220));
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError));
    }
  }

  async function searchMemory() {
    if (!query.trim()) return;
    try {
      setLoading(true);
      setError("");
      setSearchResult(await api.memorySearch(query.trim(), scope, 8));
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    reload().catch(() => undefined);
  }, []);

  return (
    <section className="panel-page memory-page">
      <header className="panel-header memory-header">
        <div>
          <h2>Memory</h2>
          <p>{status?.memory_root || "Long-term Markdown memory"}</p>
        </div>
        <button onClick={reload}>
          <RefreshCw size={16} />
          Refresh
        </button>
      </header>

      {error ? <p className="settings-error">{error}</p> : null}

      <div className="memory-stats">
        <MemoryStat label="Episodic memory" value={(status?.episodic_memory_enabled ?? status?.enabled) ? "enabled" : "disabled"} />
        <MemoryStat label="Core memory" value={(status?.core_memory_enabled ?? true) ? "enabled" : "disabled"} />
        <MemoryStat label="Core pending" value={`${corePending.length}`} />
        <MemoryStat label="Core active" value={`${coreActive.length}`} />
        <MemoryStat label="Snapshot" value={`${coreSnapshot?.chars || 0} chars`} />
        <MemoryStat label="Provider" value={String(providerStatus?.provider || "unknown")} />
        <MemoryStat label="File memory" value={status?.file_memory_enabled ? "enabled" : "disabled"} />
        <MemoryStat label="Search" value={status?.search_enabled ? "enabled" : "disabled"} />
        <MemoryStat label="Files" value={`${status?.file_count || 0} files / ${status?.indexed_file_count || 0} indexed`} />
      </div>

      <div className="core-memory-layout">
        <section className="core-memory-column">
          <div className="capability-list-head">
            <span>Pending</span>
            <button onClick={() => reload()}>Reload</button>
          </div>
          <CoreMemoryList
            memories={corePending}
            empty="No pending candidates."
            selectedId={selectedCoreId}
            onSelect={(id) => {
              setSelectedCoreId(id);
              api.coreMemoryAudit(id, 80).then((payload) => setCoreAudit(payload.audit)).catch(() => undefined);
            }}
            actions={(memory) => (
              <>
                <button onClick={() => actOnCoreMemory("approve", memory.id)}>
                  <Check size={14} />
                </button>
                <button onClick={() => actOnCoreMemory("reject", memory.id)}>
                  <X size={14} />
                </button>
              </>
            )}
          />
        </section>

        <section className="core-memory-column">
          <div className="capability-list-head">
            <span>Active</span>
          </div>
          <CoreMemoryList
            memories={coreActive}
            empty="No active core memory."
            selectedId={selectedCoreId}
            onSelect={(id) => {
              setSelectedCoreId(id);
              api.coreMemoryAudit(id, 80).then((payload) => setCoreAudit(payload.audit)).catch(() => undefined);
            }}
            actions={(memory) => (
              <button onClick={() => actOnCoreMemory("archive", memory.id)}>
                <Trash2 size={14} />
              </button>
            )}
          />
        </section>

        <section className="core-memory-column core-memory-preview">
          <div className="capability-list-head">
            <span>Snapshot</span>
            <small>{coreSnapshot?.snapshot_hash ? coreSnapshot.snapshot_hash.slice(0, 10) : "not frozen"}</small>
          </div>
          <pre>{coreSnapshot?.snapshot || "No active core memory will be injected."}</pre>
          {coreSnapshot?.skipped_ids?.length ? <p className="muted">Skipped: {coreSnapshot.skipped_ids.join(", ")}</p> : null}
        </section>

        <section className="core-memory-column">
          <div className="capability-list-head">
            <span>Audit</span>
            <small>{selectedCoreId ? shortId(selectedCoreId) : "all"}</small>
          </div>
          <div className="core-audit-list">
            {coreAudit.length ? coreAudit.map((record) => (
              <div key={record.audit_id} className="core-audit-row">
                <strong>{record.action}</strong>
                <span>{`${record.before_status || "-"} -> ${record.after_status || "-"}`}</span>
                <p>{record.reason || record.actor}</p>
              </div>
            )) : <p className="muted">No audit records.</p>}
          </div>
        </section>
      </div>

      <div className="core-automation-bar">
        <button onClick={() => runAutomation("merge-preview")}>Merge preview</button>
        <button onClick={() => runAutomation("merge-apply")}>Merge apply</button>
        <button onClick={() => runAutomation("compact-preview")}>Compact preview</button>
        <button onClick={() => runAutomation("compact-apply")}>Compact apply</button>
        <span>Provider writes: {String(providerStatus?.mirrored_write_count ?? 0)} / turns: {String(providerStatus?.synced_turn_count ?? 0)}</span>
      </div>
      {automationResult ? <pre className="core-automation-result">{JSON.stringify(automationResult, null, 2)}</pre> : null}

      <div className="memory-layout">
        <aside className="memory-sidebar">
          <div className="memory-searchbar">
            <Search size={15} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => event.key === "Enter" && searchMemory()} placeholder="Search memory" />
            <select value={scope} onChange={(event) => setScope(event.target.value)}>
              <option value="auto">auto</option>
              <option value="workspace">workspace</option>
              <option value="global">global</option>
              <option value="all">all</option>
            </select>
            <button onClick={searchMemory} disabled={!query.trim() || loading}>{loading ? "Searching" : "Search"}</button>
          </div>

          <div className="memory-results">
            {searchResult?.warnings?.map((warning) => <p className="settings-error" key={warning}>{warning}</p>)}
            {searchResult?.results?.map((hit) => (
              <button key={`${hit.path}-${hit.line_start}`} className="memory-hit" onClick={() => readFile(hit.path, hit.line_start)}>
                <strong>{hit.path}</strong>
                <span>{hit.source_scope} · lines {hit.line_start}-{hit.line_end} · {hit.score.toFixed(2)}</span>
                <p>{hit.snippet}</p>
              </button>
            ))}
          </div>

          <div className="memory-file-list">
            <div className="capability-list-head">
              <span>{files.length} memory files</span>
            </div>
            {files.map((file) => (
              <button key={file.path} className={selectedPath === file.path ? "memory-file-row active" : "memory-file-row"} onClick={() => readFile(file.path)}>
                <strong>{file.path}</strong>
                <span>{file.scope} · {formatBytes(file.size)}</span>
              </button>
            ))}
          </div>
        </aside>

        <div className="memory-reader">
          {selectedFile ? (
            <>
              <div className="memory-reader-head">
                <div>
                  <small>{selectedFile.line_start}-{selectedFile.line_end}</small>
                  <h3>{selectedFile.path}</h3>
                </div>
                <span>{status?.index_path || ""}</span>
              </div>
              <pre>{selectedFile.content || "This memory file is empty."}</pre>
            </>
          ) : (
            <div className="empty-state">
              <BookOpen size={24} />
              <strong>No memory files found</strong>
              <span>Create MEMORY.md or memory/**/*.md to populate this view.</span>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function MemoryStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function CoreMemoryList({
  memories,
  empty,
  selectedId,
  onSelect,
  actions
}: {
  memories: CoreMemoryRecord[];
  empty: string;
  selectedId: string;
  onSelect: (id: string) => void;
  actions: (memory: CoreMemoryRecord) => React.ReactNode;
}) {
  if (!memories.length) return <div className="core-memory-list"><p className="muted">{empty}</p></div>;
  return (
    <div className="core-memory-list">
      {memories.map((memory) => (
        <article key={memory.id} className={selectedId === memory.id ? "core-memory-item active" : "core-memory-item"}>
          <button className="core-memory-main" onClick={() => onSelect(memory.id)}>
            <span className="core-memory-meta">{memory.scope}/{memory.section}/{memory.type}</span>
            <strong className="core-memory-content">{memory.content}</strong>
            <small>{shortId(memory.id)} · confidence {memory.confidence.toFixed(2)}</small>
          </button>
          <div className="core-memory-actions">{actions(memory)}</div>
        </article>
      ))}
    </div>
  );
}

type CapabilityTab = "mcp" | "skills" | "plugins";
type CapabilityDrawerMode = "none" | "edit" | "settings";

function CapabilityWorkbench({
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
  const items = capabilityItems(inventory, tab);
  const filteredItems = items.filter((item) => capabilityMatchesQuery(item, query));
  const selected = selectedName ? items.find((item) => String(item.name || "") === selectedName) : undefined;
  const governanceSummary = capabilityGovernanceSummary(inventory, tab);

  async function reload() {
    const [nextInventory, nextSnapshot] = await Promise.all([api.capabilityConfig(), api.config(activeSessionId || undefined)]);
    setInventory(nextInventory);
    setSnapshot(nextSnapshot);
    const nextItems = capabilityItems(nextInventory, tab);
    if (!selectedName && nextItems[0]) setSelectedName(String(nextItems[0].name || ""));
    setSettingsDraft(capabilitySettingsToDraft(nextInventory, tab));
  }

  useEffect(() => {
    setTab(initialTab);
  }, [initialTab]);

  useEffect(() => {
    reload().catch((nextError) => setError(nextError instanceof Error ? nextError.message : String(nextError)));
  }, [tab, activeSessionId]);

  useEffect(() => {
    setDraft(capabilityItemToDraft(selected, tab));
  }, [selectedName, tab, inventory]);

  useEffect(() => {
    if (tab !== "skills" || !selectedName || !selected || selected.body_materialized) return;
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
  }, [selectedName, tab, selected]);

  async function applySettings() {
    try {
      setError("");
      const patch = capabilitySettingsFromDraft(settingsDraft, tab);
      const response = await api.capabilitySettingsPatch({ [tab]: patch });
      setInventory(response.inventory);
      setSnapshot(response.snapshot);
      setNotice("Settings applied.");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError));
    }
  }

  async function saveItem() {
    try {
      setError("");
      const payload = capabilityPayloadFromDraft(draft, tab);
      let nextInventory: CapabilityInventory;
      if (tab === "mcp") {
        nextInventory = selected ? await api.updateMcpServer(String(selected.name), payload) : await api.createMcpServer(payload);
      } else if (tab === "skills") {
        nextInventory = selected ? await api.updateSkill(String(selected.name), payload) : await api.createSkill(payload);
      } else {
        nextInventory = selected ? await api.updatePlugin(String(selected.name), payload) : await api.createPlugin(payload);
      }
      setInventory(nextInventory);
      setSelectedName(String(payload.name || ""));
      setDrawerMode("edit");
      setNotice("Saved.");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError));
    }
  }

  async function deleteMcp() {
    if (tab !== "mcp" || !selected) return;
    if (!window.confirm(`Delete MCP server "${String(selected.name)}"? This removes the server from workspace capability configuration.`)) return;
    try {
      const nextInventory = await api.deleteMcpServer(String(selected.name));
      setInventory(nextInventory);
      setSelectedName("");
      setDrawerMode("none");
      setNotice("Deleted.");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError));
    }
  }

  function newItem() {
    setSelectedName("");
    setDraft(capabilityItemToDraft(null, tab));
    setDrawerMode("edit");
  }

  return (
    <section className="panel-page capability-page">
      <header className="panel-header">
        <div>
          <h2>Capability Workbench</h2>
          <p>{workspaceStatus?.path || inventory?.workspace || "Workspace capability configuration"}</p>
        </div>
        <div className="capability-meta">
          <span>{workspaceStatus?.git_branch || "no branch"}</span>
          <span>{snapshot?.effective_hash ? snapshot.effective_hash.slice(0, 10) : "hash pending"}</span>
          <span className={`reload-badge reload-${snapshot?.reload_policy || "hot"}`}>{snapshot?.reload_policy || "hot"}</span>
          <span>{governanceSummary.total} governed</span>
          <span>{governanceSummary.currentTab} {governanceSummary.label}</span>
          <span>{governanceSummary.risk}</span>
        </div>
      </header>

      <div className="segmented-actions capability-tabs">
        {(["mcp", "skills", "plugins"] as CapabilityTab[]).map((item) => (
          <button key={item} className={tab === item ? "active" : ""} onClick={() => { setTab(item); setSelectedName(""); }}>{item.toUpperCase()}</button>
        ))}
      </div>

      {error ? <p className="settings-error">{error}</p> : null}
      {notice ? <p className="settings-success">{notice}</p> : null}

      <div className="capability-toolbar">
        <label className="capability-search">
          <Search size={14} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`Search ${tab}`} />
        </label>
        <button onClick={() => reload()}><RefreshCw size={14} /> Reload</button>
        <button onClick={() => setDrawerMode("settings")}><Settings size={14} /> Settings</button>
        <button onClick={newItem}><Plus size={14} /> New</button>
      </div>

      <div className="capability-layout">
        <div className="capability-grid">
          {filteredItems.map((item) => (
            <button
              key={String(item.name)}
              className={String(item.name) === String(selected?.name || "") ? "capability-card active" : "capability-card"}
              title={String(item.description || item.path || item.resolved_transport || "")}
              onClick={() => { setSelectedName(String(item.name || "")); setDrawerMode("edit"); }}
              type="button"
            >
              <span className={`capability-card-initials capability-card-initials-${tab}`}>{capabilityInitials(item, tab)}</span>
              <span className="capability-card-body">
                <span className="capability-card-top">
                  <span>{tab.toUpperCase()}</span>
                  <em>{capabilityStatus(item, tab)}</em>
                </span>
                <strong>{String(item.name || "unnamed")}</strong>
                <p>{String(item.description || item.path || item.entrypoint || item.command || "No description yet.")}</p>
                <span className="capability-card-meta">
                  {capabilityMeta(item, tab).map((meta) => <span key={meta}>{meta}</span>)}
                </span>
              </span>
              <span className="capability-card-menu" aria-hidden="true">⋮</span>
            </button>
          ))}
          {items.length === 0 ? <div className="capability-empty">No {tab} resources configured yet.</div> : null}
          {items.length > 0 && filteredItems.length === 0 ? <div className="capability-empty">No {tab} resources match this search.</div> : null}
        </div>

        {drawerMode !== "none" ? (
          <div className="capability-drawer-backdrop" onClick={() => setDrawerMode("none")}>
            <aside className="capability-drawer" onClick={(event) => event.stopPropagation()}>
              {drawerMode === "settings" ? (
                <>
                  <div className="capability-editor-head">
                    <div>
                      <small>SETTINGS</small>
                      <h3>{tab.toUpperCase()} settings</h3>
                      <p>{snapshot?.pending_effects?.slice(0, 3).join(", ") || `${snapshot?.reload_policy || "hot"} reload policy`}</p>
                    </div>
                    <div className="capability-editor-actions">
                      <button onClick={() => setSettingsDraft(capabilitySettingsToDraft(inventory!, tab))} disabled={!inventory}>Revert</button>
                      <button className="primary" onClick={applySettings}>Apply</button>
                      <button onClick={() => setDrawerMode("none")}><X size={14} /></button>
                    </div>
                  </div>
                  <div className="capability-settings-card drawer">
                    {renderCapabilitySettings(settingsDraft, setSettingsDraft, tab)}
                  </div>
                </>
              ) : (
                <>
                  <div className="capability-editor-head">
                    <div>
                      <small>{selected ? "EDIT" : "CREATE"}</small>
                      <h3>{selected ? String(selected.name) : `New ${tab.slice(0, -1)}`}</h3>
                    </div>
                    <div className="capability-editor-actions">
                      {tab === "mcp" && selected ? <button onClick={deleteMcp}>Delete</button> : null}
                      <button onClick={() => setDraft(capabilityItemToDraft(selected, tab))}>Revert</button>
                      <button className="primary" onClick={saveItem}>Apply</button>
                      <button onClick={() => setDrawerMode("none")}><X size={14} /></button>
                    </div>
                  </div>
                  {renderCapabilityEditor(tab, draft, setDraft)}
                </>
              )}
            </aside>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function capabilityItems(inventory: CapabilityInventory | null, tab: CapabilityTab): Array<Record<string, unknown>> {
  if (!inventory) return [];
  if (tab === "mcp") return inventory.mcp.servers;
  return inventory[tab].items;
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

function capabilityMatchesQuery(item: Record<string, unknown>, query: string) {
  const text = query.trim().toLowerCase();
  if (!text) return true;
  return [
    item.name,
    item.description,
    item.path,
    item.entrypoint,
    item.command,
    item.url,
    item.transport,
    item.protocol
  ].map((value) => String(value || "")).join(" ").toLowerCase().includes(text);
}

function capabilityStatus(item: Record<string, unknown>, tab: CapabilityTab) {
  if (item.enabled === false) return "disabled";
  if (tab === "mcp") return String(item.resolved_transport || item.transport || "server");
  if (tab === "skills") return String(item.source || "skill");
  return String(item.entrypoint ? "configured" : "plugin");
}

function capabilityInitials(item: Record<string, unknown>, tab: CapabilityTab) {
  const fallback = tab === "mcp" ? "MC" : tab === "skills" ? "SK" : "PL";
  const name = String(item.name || "").trim();
  if (!name) return fallback;
  const parts = name.split(/[\s._/-]+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  return name.slice(0, 2).toUpperCase();
}

function capabilityMeta(item: Record<string, unknown>, tab: CapabilityTab) {
  if (tab === "mcp") {
    return [
      String(item.transport || item.resolved_transport || "auto"),
      String(item.protocol || "auto"),
      String(item.url || item.command || "no endpoint"),
      item.timeout_seconds ? `${item.timeout_seconds}s` : ""
    ].filter(Boolean).slice(0, 4);
  }
  if (tab === "skills") {
    return [
      String(item.source || item.root || "workspace"),
      String(item.path || "inline"),
    ].filter(Boolean).slice(0, 3);
  }
  return [
    String(item.entrypoint || "no entrypoint"),
    Array.isArray(item.provides) ? `${item.provides.length} provides` : ""
  ].filter(Boolean);
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

function formatEventTime(value?: number) {
  if (!value) return "--:--:--";
  return new Date(value * 1000).toLocaleTimeString();
}

function formatLogTime(value?: string | number | null) {
  if (!value) return "--:--:--";
  const date = typeof value === "number" ? new Date(value > 10_000_000_000 ? value : value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleTimeString();
}

function formatBytes(value?: number) {
  const size = Number(value || 0);
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
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
  onOpenPath,
  onConfirm
}: {
  currentPath: string;
  value: string;
  pendingWorkspace: OpenWorkspaceResponse | null;
  onChange: (value: string) => void;
  onClose: () => void;
  onOpen: () => void;
  onOpenPath: (path: string) => void | Promise<void>;
  onConfirm: () => void | Promise<void> | undefined;
}) {
  const canPickDirectory = typeof (window as DirectoryPickerWindow).showDirectoryPicker === "function";
  const [pickerHint, setPickerHint] = useState("");
  const [pickingDirectory, setPickingDirectory] = useState(false);

  async function pickDirectory() {
    setPickingDirectory(true);
    try {
      const response = await api.pickWorkspaceDirectory();
      if (response.path) {
        setPickerHint("");
        onChange(response.path);
        await onOpenPath(response.path);
        return;
      }
      if (response.cancelled) {
        setPickerHint("Folder selection was cancelled.");
        return;
      }
    } catch (error) {
      setPickerHint(error instanceof Error ? error.message : String(error));
    } finally {
      setPickingDirectory(false);
    }

    const picker = (window as DirectoryPickerWindow).showDirectoryPicker;
    if (!picker) return;
    const handle = await picker();
    const pickedPath = pickedDirectoryPath(handle);
    if (pickedPath) {
      setPickerHint("");
      onChange(pickedPath);
      await onOpenPath(pickedPath);
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
          <button type="button" onClick={pickDirectory} disabled={pickingDirectory} title="打开系统文件夹选择器">
            <FolderOpen size={16} />
            {pickingDirectory ? "选择中..." : "选择文件夹"}
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

function scopeLabel(scope: "project" | "profile" | "session", profile: string, sessionId: string) {
  if (scope === "profile") return `Profile: ${profile || "new profile"}`;
  if (scope === "session") return sessionId ? `Session override: ${shortId(sessionId)}` : "Session override unavailable";
  return "Project defaults";
}

function readScopeConfig(snapshot: ConfigSnapshot, scope: "project" | "profile" | "session", profile?: string) {
  if (scope === "session") return snapshot.session_config || {};
  if (scope === "profile") {
    const profiles = (snapshot.project_config.profiles || {}) as Record<string, unknown>;
    const name = profile || snapshot.active_profile || "";
    const value = profiles[name];
    return value && typeof value === "object" ? value as Record<string, unknown> : {};
  }
  return snapshot.project_config || {};
}

function isFieldDirty(
  snapshot: ConfigSnapshot,
  drafts: Record<string, string>,
  field: ConfigField,
  scope: "project" | "profile" | "session",
  profile?: string
) {
  const layer = readScopeConfig(snapshot, scope, profile);
  const layerValue = readConfigPath(layer, field.path);
  const baseline = layerValue === undefined ? readConfigPath(snapshot.settings, field.path) : layerValue;
  return (drafts[field.path] || "") !== stringifyConfigValue(baseline);
}

function renderConfigInput(field: ConfigField, value: string, onChange: (value: string) => void) {
  if (field.type === "boolean") {
    return (
      <label className="settings-toggle">
        <input type="checkbox" checked={value === "true"} onChange={(event) => onChange(String(event.target.checked))} />
      </label>
    );
  }
  if (field.options?.length) {
    return (
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {field.options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    );
  }
  if (field.type === "array") {
    const chips = value.trim().startsWith("[") ? parseArrayPreview(value) : value.split(",").map((item) => item.trim()).filter(Boolean);
    return (
      <div className="settings-array-editor">
        <div>{chips.slice(0, 8).map((item) => <span key={item}>{item}</span>)}</div>
        <input value={value} onChange={(event) => onChange(event.target.value)} placeholder="comma list or JSON array" />
      </div>
    );
  }
  if (field.type === "object") {
    return <textarea className="settings-inline-json" value={value} onChange={(event) => onChange(event.target.value)} />;
  }
  return (
    <input
      type={field.type.startsWith("integer") || field.type === "number" ? "number" : "text"}
      min={field.minimum ?? undefined}
      max={field.maximum ?? undefined}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

function parseArrayPreview(value: string) {
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}

function applyConfigError(
  err: unknown,
  setError: (value: string) => void,
  setFieldErrors: (value: Record<string, string>) => void
) {
  const message = err instanceof Error ? err.message : String(err);
  try {
    const payload = JSON.parse(message);
    const errors = Array.isArray(payload.errors) ? payload.errors : [];
    const next: Record<string, string> = {};
    errors.forEach((item: Record<string, unknown>) => {
      if (typeof item.path === "string") next[item.path] = String(item.message || item.code || "Invalid value");
    });
    setFieldErrors(next);
    setError(String(payload.message || "Config validation failed."));
    return;
  } catch {
    setError(message.includes("[object Object]") ? "Config conflict or validation error. Reload and reapply the change." : message);
  }
}

function buildConfigDrafts(snapshot: ConfigSnapshot) {
  const drafts: Record<string, string> = {};
  snapshot.schema.fields.forEach((field) => {
    drafts[field.path] = stringifyConfigValue(readConfigPath(snapshot.settings, field.path));
  });
  return drafts;
}

function readConfigPath(source: Record<string, unknown>, path: string): unknown {
  return path.split(".").reduce<unknown>((current, part) => {
    if (!current || typeof current !== "object") return undefined;
    return (current as Record<string, unknown>)[part];
  }, source);
}

function stringifyConfigValue(value: unknown) {
  if (value === undefined || value === null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function parseFieldDraft(value: string | undefined, type: string): unknown {
  const text = (value || "").trim();
  if (type === "boolean") return text === "true";
  if (type.startsWith("integer")) return text ? Number.parseInt(text, 10) : null;
  if (type === "number") return text ? Number.parseFloat(text) : 0;
  if (type === "array") {
    if (!text) return [];
    if (!text.startsWith("[")) return text.split(",").map((item) => item.trim()).filter(Boolean);
    return JSON.parse(text);
  }
  if (type === "object" || type.includes("null")) {
    if (!text) return type.includes("null") ? null : {};
    return JSON.parse(text);
  }
  return value || "";
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
  const activityGroups: RuntimeEvent[][] = [];
  let activeActivityGroup: RuntimeEvent[] = [];
  let streamBuffer = "";
  let streamIndex = 0;
  let streamTimestamp = 0;

  const flushActivityGroup = () => {
    const group = activeActivityGroup;
    activeActivityGroup = [];
    if (group.some(isActivityEvent)) activityGroups.push(group);
  };

  const appendActivityEvent = (event: RuntimeEvent) => {
    if (activeActivityGroup.length === 0) activeActivityGroup.push(event);
    else activeActivityGroup.push(event);
  };

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
      flushActivityGroup();
      activeActivityGroup.push(event);
      const text = (event.message || "").trim();
      if (text && !committedUsers.has(normalizeText(text))) {
        runtime.push({ id: `local-user:${runtime.length}`, role: "user", body: { text, attachments: [] }, timestamp: event.timestamp });
      }
      continue;
    }
    if (event.type === "turn_start" || event.type === "agent_start") {
      flushStream();
      flushActivityGroup();
      activeActivityGroup.push(event);
      continue;
    }
    if (event.type === "approval_result") {
      flushStream();
      appendActivityEvent(event);
      continue;
    }
    if (event.type === "turn_end" || event.type === "agent_end") {
      flushStream();
      appendActivityEvent(event);
      flushActivityGroup();
      continue;
    }
    if (event.is_error && event.message) {
      flushStream();
      if (isActivityEvent(event)) {
        appendActivityEvent(event);
      } else {
        runtime.push({ id: `error:${runtime.length}`, role: "error", body: { text: formatErrorEvent(event), attachments: [] }, timestamp: event.timestamp });
      }
      continue;
    }
    if (isActivityEvent(event)) {
      flushStream();
      appendActivityEvent(event);
      continue;
    }
  }

  flushStream();
  flushActivityGroup();
  activityGroups.forEach((group, index) => {
    const activity = combineActivityItemsForTranscript(buildActivityRuns(group), group);
    if (!activity) return;
    runtime.push({
      id: `activity-turn:${index}:${activity.startedAt || activity.endedAt || runtime.length}`,
      role: "activity",
      body: { text: activity.detail, attachments: activity.entries?.flatMap((entry) => entry.attachments || []) || [] },
      timestamp: activity.endedAt || activity.startedAt,
      activity
    });
  });
  const items = [...stored, ...runtime].sort((left, right) => {
    const leftTime = left.timestamp || 0;
    const rightTime = right.timestamp || 0;
    if (leftTime !== rightTime) return leftTime - rightTime;
    return 0;
  });
  if (shouldShowProgressPlaceholder(items, events)) {
    items.push({ id: "progress-placeholder", role: "assistant", body: { text: "Analyzing the request", attachments: [] }, streaming: true });
  }
  return items;
}

function combineActivityItemsForTranscript(items: ActivityItem[], events: RuntimeEvent[]): ActivityItem | null {
  if (items.length === 0) return null;
  if (items.length === 1) return items[0];
  const startedAt = firstTimestamp(events) ?? items[0].startedAt;
  const endedAt = latestTerminalTimestamp(events) ?? items[items.length - 1].endedAt;
  const running = items.some((item) => item.running);
  const hasError = items.some((item) => item.status === "error");
  const status = hasError ? "error" : running ? "running" : "success";
  const endForDuration = running ? Date.now() / 1000 : endedAt;
  const durationLabel = startedAt && endForDuration ? formatDuration(Math.max(0, (endForDuration - startedAt) * 1000)) : "";
  const entries = items.flatMap((item) => item.entries);
  const detail = entries.map((entry) => [entry.label, entry.detail].filter(Boolean).join("\n")).join("\n\n");
  const toolCount = items.reduce((total, item) => total + item.toolCount, 0);
  const approvalCount = items.reduce((total, item) => total + item.approvalCount, 0);
  const errorCount = items.reduce((total, item) => total + item.errorCount, 0);
  return {
    id: `turn-activity:${startedAt || items[0].id}`,
    phase: items.some((item) => item.phase === "preparing" || item.phase === "analyzing" || item.phase === "finalizing") ? "analyzing" : items.some((item) => item.phase === "planning") ? "planning" : "tool",
    status,
    tone: status,
    title: `${status === "error" ? "Failed" : running ? "Running" : "Done"} · ${items.length} activities${durationLabel ? ` · ${durationLabel}` : ""}`,
    summary: [
      toolCount ? `${toolCount} tool call${toolCount === 1 ? "" : "s"}` : "",
      approvalCount ? `${approvalCount} approval${approvalCount === 1 ? "" : "s"}` : "",
      errorCount ? `${errorCount} error${errorCount === 1 ? "" : "s"}` : "",
    ].filter(Boolean).join(" · ") || `${entries.length} runtime event${entries.length === 1 ? "" : "s"}`,
    detail,
    timestamp: startedAt,
    startedAt,
    endedAt: running ? undefined : endedAt,
    durationLabel,
    running,
    entries,
    attachments: entries.flatMap((entry) => entry.attachments || []),
    eventCount: items.reduce((total, item) => total + item.eventCount, 0),
    toolCount,
    approvalCount,
    errorCount
  };
}

export function buildTurnMarkers(transcript: TranscriptItem[]): TurnMarker[] {
  const markers: TurnMarker[] = [];
  let current: TurnMarker | null = null;
  const assistantParts: string[] = [];

  const finishCurrent = () => {
    if (!current) return;
    current.assistantPreview = summarizePreview(assistantParts.join(" "));
    markers.push(current);
    current = null;
    assistantParts.length = 0;
  };

  transcript.forEach((item) => {
    if (item.role === "user") {
      finishCurrent();
      current = {
        id: item.id,
        turnNumber: markers.length + 1,
        userPreview: summarizePreview(item.body.text),
        assistantPreview: ""
      };
      return;
    }
    if (!current || item.id === "progress-placeholder") return;
    if (item.role === "assistant") {
      assistantParts.push(item.body.text);
    } else if (item.role === "activity" && item.activity) {
      assistantParts.push(item.activity.summary || item.body.text);
    } else if (item.role === "error") {
      assistantParts.push(item.body.text);
    }
  });

  finishCurrent();
  return markers;
}

function findActiveTurnId(target: HTMLElement, markers: TurnMarker[]) {
  if (markers.length === 0) return "";
  const anchorTop = target.scrollTop + 80;
  let active = markers[0].id;
  markers.forEach((marker) => {
    const element = findTranscriptElement(target, marker.id);
    if (element && element.offsetTop <= anchorTop) active = marker.id;
  });
  return active;
}

function findTranscriptElement(target: HTMLElement, id: string) {
  const items = Array.from(target.querySelectorAll<HTMLElement>("[data-transcript-id]"));
  return items.find((item) => item.dataset.transcriptId === id) || null;
}

function summarizePreview(value: string) {
  const clean = normalizeText(value);
  return clean ? truncate(clean, 120) : "";
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

function isActivityEvent(event: RuntimeEvent) {
  return (
    event.type.includes("tool") ||
    event.type.includes("planner") ||
    event.type.startsWith("reasoning_") ||
    event.type === "before_provider_request" ||
    event.type === "provider_response" ||
    event.type === "provider_error" ||
    event.type.includes("checkpoint") ||
    event.type.includes("subagent") ||
    event.type === "approval_result" ||
    event.type === "cancel_requested"
  );
}

function formatActivityGroup(events: RuntimeEvent[], index: number): {
  title: string;
  summary: string;
  detail: string;
  durationLabel?: string;
  entries?: ActivityEntry[];
  startedAt?: number;
  endedAt?: number;
  running?: boolean;
  tone?: "running" | "success" | "warning" | "error";
} | null {
  const activityEvents = events.filter(isActivityEvent);
  if (activityEvents.length === 0) return null;
  const startedAt = firstTimestamp(events) ?? firstTimestamp(activityEvents);
  const endedAt = latestTerminalTimestamp(events) ?? lastTimestamp(activityEvents);
  const hasError = activityEvents.some((event) => event.type === "tool_error" || event.is_error);
  const entries = buildActivityEntries(activityEvents);
  if (entries.length === 0) return null;
  const hasTerminal = events.some((event) => event.type === "turn_end" || event.type === "agent_end");
  const running = !hasError && !hasTerminal && entries.some((entry) => entry.tone === "running");
  const effectiveEnd = running ? Math.max(Date.now() / 1000, startedAt || lastTimestamp(activityEvents) || 0) : endedAt;
  const durationLabel = startedAt && effectiveEnd ? formatDuration(Math.max(0, (effectiveEnd - startedAt) * 1000)) : "";
  const commandCount = entries.filter((entry) => entry.kind === "command").length;
  const toolCount = entries.filter((entry) => entry.kind === "tool").length;
  const title = `${hasError ? "处理失败" : running ? "处理中" : "已处理"}${durationLabel ? ` ${durationLabel}` : ""}`;
  const summaryParts = [
    commandCount ? `已运行 ${commandCount} 条命令` : "",
    toolCount ? `已调用 ${toolCount} 个工具` : "",
    entries.length && !commandCount && !toolCount ? `${entries.length} 个步骤` : ""
  ].filter(Boolean);
  const detail = entries.map((entry) => activityEntryDetail(entry)).filter(Boolean).join("\n\n");
  return {
    title,
    summary: summaryParts.join(" · ") || `已处理 ${entries.length} 个步骤`,
    detail,
    durationLabel,
    entries,
    startedAt,
    endedAt: running ? undefined : endedAt,
    running,
    tone: hasError ? "error" : running ? "running" : "success"
  };
}

function buildActivityEntries(events: RuntimeEvent[]): ActivityEntry[] {
  const entries: ActivityEntry[] = [];
  const toolStarts = new Map<string, RuntimeEvent>();
  const seenToolEnds = new Set<string>();
  const plannerSummary = groupPlannerDetailLines(events);

  events.forEach((event, index) => {
    if (event.type === "tool_start") {
      const key = toolEventKey(event) || `tool:${event.tool_name || "tool"}:${event.timestamp || index}`;
      toolStarts.set(key, event);
      return;
    }
    if (event.type === "tool_end" || event.type === "tool_result" || event.type === "tool_error") {
      const key = toolEventKey(event) || `tool:${event.tool_name || "tool"}:${event.timestamp || index}`;
      const start = toolStarts.get(key);
      seenToolEnds.add(key);
      entries.push(formatToolEntry(event, start, key));
      return;
    }
    if (event.type === "approval_result") {
      entries.push({
        id: `approval:${event.timestamp || index}`,
        kind: "approval",
        label: "审批结果",
        detail: formatApprovalEvent(event),
        timestamp: event.timestamp,
        tone: event.is_error ? "error" : "success"
      });
      return;
    }
    if (event.type.includes("planner")) {
      entries.push(formatPlannerEntry(event, index, plannerSummary));
      return;
    }
    if (event.type.includes("subagent")) {
      entries.push(formatRuntimeEntry(event, "subagent", index));
      return;
    }
    if (event.type.includes("checkpoint")) {
      entries.push(formatRuntimeEntry(event, "checkpoint", index));
      return;
    }
    if (event.type === "cancel_requested") {
      entries.push(formatRuntimeEntry(event, "event", index));
    }
  });

  toolStarts.forEach((event, key) => {
    if (seenToolEnds.has(key)) return;
    entries.push(formatRunningToolEntry(event, key));
  });

  return entries.sort((left, right) => (left.timestamp || 0) - (right.timestamp || 0));
}

function formatToolEntry(event: RuntimeEvent, start: RuntimeEvent | undefined, key: string): ActivityEntry {
  const details = event.details || {};
  const startDetails = start?.details || {};
  const toolName = event.tool_name || start?.tool_name || "tool";
  const command = details.command ?? startDetails.command;
  const path = details.path ?? startDetails.path;
  const returncode = details.returncode;
  const isCommand = toolName === "run_shell" || typeof command === "string";
  const durationLabel = start?.timestamp && event.timestamp ? formatDuration(Math.max(0, (event.timestamp - start.timestamp) * 1000)) : "";
  const bits: string[] = [];
  if (typeof command === "string" && command.trim()) bits.push(`Command: ${command.trim()}`);
  if (typeof path === "string" && path.trim()) bits.push(`Path: ${path.trim()}`);
  if (typeof returncode === "number") bits.push(`Exit: ${returncode}`);
  if (event.message && event.message.trim()) bits.push(truncateMultiline(event.message.trim(), 1200));
  return {
    id: `tool:${key}:${event.timestamp || ""}`,
    kind: isCommand ? "command" : "tool",
    label: toolName,
    detail: bits.join("\n") || formatToolEvent(event),
    timestamp: start?.timestamp || event.timestamp,
    durationLabel,
    tone: event.type === "tool_error" || event.is_error ? "error" : "success",
    attachments: toolResultAttachments(details)
  };
}

function formatRunningToolEntry(event: RuntimeEvent, key: string): ActivityEntry {
  const details = event.details || {};
  const toolName = event.tool_name || "tool";
  const command = details.command;
  const path = details.path;
  const bits = ["运行中"];
  if (typeof command === "string" && command.trim()) bits.push(`Command: ${command.trim()}`);
  if (typeof path === "string" && path.trim()) bits.push(`Path: ${path.trim()}`);
  return {
    id: `tool:${key}:running`,
    kind: toolName === "run_shell" || typeof command === "string" ? "command" : "tool",
    label: toolName,
    detail: bits.join("\n"),
    timestamp: event.timestamp,
    tone: "running"
  };
}

function groupPlannerDetailLines(events: RuntimeEvent[]) {
  const plannerEnd = [...events].reverse().find((event) => event.type === "planner_end");
  const plannerSteps = events.filter((event) => event.type === "planner_step" && event.plan_step);
  const details = plannerEnd?.details || {};
  const lines: string[] = [];
  const planSteps = Array.isArray(details.plan_steps) ? details.plan_steps : plannerSteps.map((event) => event.plan_step);
  const summary = stringList(details.summary);
  const files = stringList(details.files_touched_guess);
  const shell = stringList(details.shell_commands_guess);
  const tools = stringList(details.tools);
  const highRisk = stringList(details.high_risk_tools);
  const stepCount = typeof details.step_count === "number" ? details.step_count : typeof details.count === "number" ? details.count : planSteps.length || summary.length;
  if (stepCount) lines.push(`计划包含 ${stepCount} 个步骤。`);
  summary.slice(0, 4).forEach((item) => lines.push(`- ${item}`));
  if (files.length > 0) lines.push(`预计处理文件：${files.slice(0, 5).join(", ")}`);
  if (shell.length > 0) lines.push(`准备运行命令：${shell.slice(0, 3).join(" | ")}`);
  if (tools.length > 0) lines.push(`准备调用工具：${tools.slice(0, 5).join(", ")}`);
  if (highRisk.length > 0) lines.push(`需要确认：${highRisk.slice(0, 5).join(", ")}`);
  return lines;
}

function plannerStatusLabel(status: string) {
  if (status === "in_progress") return "进行中";
  if (status === "completed") return "已完成";
  if (status === "failed") return "失败";
  if (status === "pending") return "等待中";
  return status;
}

function formatPlannerEntry(event: RuntimeEvent, index: number, plannerSummary: string[]): ActivityEntry {
  if (event.type === "planner_start") {
    return {
      id: `planner:${event.timestamp || index}:start`,
      kind: "planner",
      label: "planner_start",
      detail: plannerSummary.length > 0 ? `正在整理执行计划：\n${plannerSummary.join("\n")}` : "正在确认下一步要调用的工具和执行顺序。",
      timestamp: event.timestamp,
      tone: "running"
    };
  }
  if (event.type === "planner_step" && event.plan_step) {
    const lines = [`步骤：${event.plan_step.title}`];
    if (event.plan_step.tool_name) lines.push(`工具：${event.plan_step.tool_name}`);
    if (event.plan_step.status) lines.push(`状态：${plannerStatusLabel(event.plan_step.status)}`);
    return {
      id: `planner:${event.timestamp || index}:step:${event.plan_step.title}`,
      kind: "planner",
      label: event.plan_step.title,
      detail: lines.join("\n"),
      timestamp: event.timestamp,
      tone: event.plan_step.status === "failed" ? "error" : event.plan_step.status === "in_progress" ? "running" : "success"
    };
  }
  if (event.type === "planner_end") {
    return {
      id: `planner:${event.timestamp || index}:end`,
      kind: "planner",
      label: "planner_end",
      detail: plannerSummary.length > 0 ? plannerSummary.join("\n") : "执行计划已整理完成，准备进入工具调用。",
      timestamp: event.timestamp,
      tone: event.details?.requires_approval ? "warning" : "success"
    };
  }
  return formatRuntimeEntry(event, "planner", index);
}

function formatRuntimeEntry(event: RuntimeEvent, kind: ActivityEntry["kind"], index: number): ActivityEntry {
  const label = event.plan_step?.title || event.tool_name || eventLabel(event);
  const detail = event.message || summarizeEvent(event) || event.type;
  return {
    id: `${kind}:${event.timestamp || index}:${label}`,
    kind,
    label,
    detail,
    timestamp: event.timestamp,
    tone: event.is_error ? "error" : event.type.includes("start") || event.type.includes("progress") ? "running" : "success"
  };
}

function activityEntryDetail(entry: ActivityEntry) {
  const meta = [entry.durationLabel, entry.tone === "running" ? "运行中" : ""].filter(Boolean).join(" · ");
  return `${entry.label}${meta ? ` (${meta})` : ""}\n${entry.detail}`.trim();
}

function firstTimestamp(events: RuntimeEvent[]) {
  return events.find((event) => typeof event.timestamp === "number")?.timestamp;
}

function lastTimestamp(events: RuntimeEvent[]) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (typeof events[index].timestamp === "number") return events[index].timestamp;
  }
  return undefined;
}

function latestTerminalTimestamp(events: RuntimeEvent[]) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if ((event.type === "turn_end" || event.type === "agent_end") && typeof event.timestamp === "number") return event.timestamp;
  }
  return undefined;
}

function formatToolEvent(event: RuntimeEvent) {
  const details = event.details || {};
  const toolName = event.tool_name || "工具";
  const status = toolEventStatus(details, event.is_error);
  const lines = [status, `${toolName}`];
  const path = details.path;
  const command = details.command;
  const token = details.token;
  const output = typeof event.message === "string" ? event.message.trim() : "";
  if (typeof path === "string" && path.trim()) lines.push(`文件：${path}`);
  if (typeof command === "string" && command.trim()) lines.push(`命令：${command}`);
  if (typeof token === "string" && token.trim()) lines.push(`token：${token}`);
  const returncode = details.returncode;
  if (typeof returncode === "number") lines.push(`退出码：${returncode}`);
  if (details.approval_token && typeof details.approval_token === "string") lines.push(`审批 token：${details.approval_token}`);
  if (output) {
    lines.push("");
    lines.push(output);
  }
  return lines.join("\n").trim();
}

function toolResultAttachments(details: Record<string, unknown>): RichAttachment[] {
  const attachments: RichAttachment[] = [];
  const seen = new Set<string>();
  const pushAttachment = (item: Record<string, unknown>, rawUrl: string | undefined) => {
    if (!rawUrl) return;
    const url = sanitizeMediaUrl(rawUrl, { allowRelative: false });
    if (!url || seen.has(url)) return;
    if (looksLikeDecorativeImage(url, firstStringValue(item.title, item.alt) || "")) return;
    seen.add(url);
    attachments.push({
      url,
      alt: firstStringValue(item.title, item.alt),
      title: firstStringValue(item.title),
      name: firstStringValue(item.url),
    });
  };
  for (const result of Array.isArray(details.results) ? details.results : []) {
    if (!result || typeof result !== "object") continue;
    const item = result as Record<string, unknown>;
    const rawUrl = firstStringValue(item.image_url, item.image, item.thumbnail, item.thumbnail_url);
    pushAttachment(item, rawUrl);
    if (attachments.length >= 3) break;
  }
  for (const image of Array.isArray(details.images) ? details.images : []) {
    if (!image || typeof image !== "object") continue;
    const item = image as Record<string, unknown>;
    pushAttachment(item, firstStringValue(item.url, item.src, item.image_url));
    if (attachments.length >= 3) break;
  }
  return attachments;
}

function looksLikeDecorativeImage(url: string, label: string) {
  const value = `${url} ${label}`.toLowerCase();
  if (["logo", "favicon", "icon", "sprite", "placeholder", "blank", "loading", "avatar", "qrcode", "qr-code", "wechat", "weixin", "广告", "二维码", "图标"].some((word) => value.includes(word))) {
    return true;
  }
  return /(^|[/_.-])(ad|ads|advert|banner|sponsor|promo)([/_.-]|$)/.test(value);
}

function firstStringValue(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return undefined;
}

function formatApprovalEvent(event: RuntimeEvent) {
  const details = event.details || {};
  const approvalDetails = (details.approval_details as Record<string, unknown> | undefined) || {};
  const lines: string[] = [];
  const actionType = typeof details.action_type === "string" ? details.action_type : "";
  if (actionType === "run_shell") {
    lines.push("Command completed.");
  } else if (actionType === "write_file" || actionType === "edit_file") {
    const path = approvalDetails.path || approvalDetails.absolute_path || details.path;
    lines.push(typeof path === "string" && path.trim() ? `Applied successfully: ${path}` : "Applied successfully.");
  } else if (actionType === "apply_patch_artifact") {
    const changedPaths = Array.isArray(approvalDetails.changed_paths)
      ? approvalDetails.changed_paths.filter((value): value is string => typeof value === "string" && value.trim().length > 0)
      : [];
    lines.push(changedPaths.length > 0 ? `Patch applied successfully: ${changedPaths.join(", ")}` : "Patch artifact applied successfully.");
  } else if (event.message) {
    lines.push(event.message);
  } else {
    lines.push("Approval completed.");
  }
  const result = details.result;
  if (typeof result === "string" && result.trim()) {
    lines.push("");
    lines.push(result.trim());
  }
  return lines.join("\n").trim();
}

function toolEventStatus(details: Record<string, unknown>, isError?: boolean) {
  if (details.persisted === true) return "已完成";
  if (details.staged === true) return "已进入审批";
  if (details.approval_unavailable === true) return "无法安全执行";
  if (isError) return "执行失败";
  return "执行完成";
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

function runtimeEventDedupeKey(event: RuntimeEvent) {
  const details = event.details || {};
  const trace = details.trace && typeof details.trace === "object" ? details.trace as Record<string, unknown> : {};
  const activity = details.activity && typeof details.activity === "object" ? details.activity as Record<string, unknown> : {};
  const explicit = event.event_id || trace.event_id || activity.event_id || details.event_id;
  if (typeof explicit === "string" && explicit.trim()) return explicit;
  if (typeof explicit === "number") return String(explicit);
  return runtimeEventKey(event);
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

function shouldShowProgressPlaceholder(items: TranscriptItem[], events: RuntimeEvent[]) {
  if (!isTurnInFlight(events)) return false;
  const latestUserIndex = findLastIndex(items, (item) => item.role === "user");
  if (latestUserIndex < 0) return true;
  return !items.slice(latestUserIndex + 1).some((item) => item.role === "assistant" && item.body.text.trim() && item.id !== "progress-placeholder");
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

export function buildActivityItems(events: RuntimeEvent[], snapshot?: SessionSnapshot, approvals?: ApprovalsSummary) {
  return buildActivityRuns(events, snapshot, approvals);
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

function truncateMultiline(value: string, limit: number) {
  const clean = value.trim();
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
  const sessionId = snapshot?.session_id || "";
  const eventTokens = eventPendingTokens(events);
  if (plannerToken) {
    const sourceItems = summary.active_items || summary.items;
    const plannerAction = sourceItems.find(
      (item) => item.action_type === "planner_approval" && item.token === plannerToken && isActionableApproval(item) && approvalBelongsToSession(item, sessionId, eventTokens)
    );
    const plannerEventDetails = latestPlannerApprovalDetails(events, plannerToken);
    return {
      kind: "planner",
      token: plannerToken,
      title: "Step 1 of 2: 确认执行计划",
      description: plannerApprovalDescription(plannerAction, plannerEventDetails),
      approveLabel: "确认计划",
      meta: plannerApprovalMeta(plannerAction, plannerEventDetails)
    };
  }
  const sourceItems = summary.active_items || summary.items;
  const pending = sourceItems.find(
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

function latestPlannerApprovalDetails(events: RuntimeEvent[], token: string): Record<string, unknown> | undefined {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event.type !== "planner_gate_pending" && event.type !== "planner_start" && event.type !== "planner_end") continue;
    const details = event.details || {};
    const eventToken = details.token;
    if (typeof eventToken === "string" && eventToken && eventToken !== token) continue;
    if (Array.isArray(details.summary) || Array.isArray(details.plan_steps) || Array.isArray(details.tools)) return details;
  }
  return undefined;
}

function plannerApprovalDescription(item: PendingAction | undefined, eventDetails: Record<string, unknown> | undefined) {
  const details = item?.details || eventDetails || {};
  const steps = plannerStepSummaries(details);
  if (steps.length > 0) {
    const visible = steps.slice(0, 3).map((step, index) => `${index + 1}. ${step}`).join("  ");
    const suffix = steps.length > 3 ? `  另有 ${steps.length - 3} 步。` : "";
    return `即将执行 ${steps.length} 步：${visible}${suffix}`;
  }
  const tools = stringList(details.tools);
  if (tools.length > 0) return `即将调用工具：${tools.slice(0, 5).join(", ")}。批准后才会进入具体执行。`;
  return "确认模型提出的工具执行计划。批准计划本身不会直接改文件，下一步仍会对具体动作单独确认。";
}

function plannerApprovalMeta(item: PendingAction | undefined, eventDetails: Record<string, unknown> | undefined) {
  const details = item?.details || eventDetails || {};
  const tools = stringList(details.tools);
  const files = stringList(details.files_touched_guess);
  const bits: string[] = [];
  if (tools.length > 0) bits.push(`tools: ${tools.slice(0, 4).join(", ")}${tools.length > 4 ? ", ..." : ""}`);
  if (files.length > 0) bits.push(`files: ${files.slice(0, 3).join(", ")}${files.length > 3 ? ", ..." : ""}`);
  return bits.join(" · ");
}

function plannerStepSummaries(details: Record<string, unknown>) {
  const summary = stringList(details.summary);
  if (summary.length > 0) return summary;
  const planSteps = Array.isArray(details.plan_steps) ? details.plan_steps : [];
  return planSteps
    .map((step) => {
      if (!step || typeof step !== "object") return "";
      const record = step as Record<string, unknown>;
      const title = typeof record.title === "string" ? record.title.trim() : "";
      const tool = typeof record.tool_name === "string" ? record.tool_name.trim() : "";
      if (title && tool) return `${title} [${tool}]`;
      return title || tool;
    })
    .filter((value) => value.length > 0);
}

function stringList(value: unknown) {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item || "").trim()).filter((item) => item.length > 0);
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
    const base = typeof path === "string" && path.trim() ? `Applied successfully: ${path}` : "Applied successfully.";
    return typeof result.result === "string" && result.result.trim() ? `${base}\n\n${result.result.trim()}` : base;
  }
  if (actionType === "run_shell") {
    const output = typeof result.result === "string" ? result.result.trim() : "";
    return output ? `Command completed.\n\n${output}` : "Command completed.";
  }
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
