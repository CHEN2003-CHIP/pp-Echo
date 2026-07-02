import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import {
  Activity,
  ArrowDown,
  Bot,
  BookOpen,
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
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { List, ListItem } from "@/components/ui/list";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, ApprovalActionResponse, ApprovalsSummary, AttachmentRecord, CapabilityInventory, ConfigField, ConfigSnapshot, CoreMemoryAuditRecord, CoreMemoryRecord, CoreMemorySnapshot, LogEntry, MemoryFileRead, MemorySearchResponse, MemoryStatus, ModelProviderPreset, UsageAnalytics, ModelUsageRow, OpenWorkspaceResponse, PendingAction, PersistedActivityBlock, RuntimeEvent, SessionEntry, SessionSnapshot, TimelineEntry, WorkspaceGitStatus, WorkspaceStatus, WorkspacesState } from "./api";
import { DefaultAssistantActions, Message, MessageContent, MessagePlainText, MessageResponse } from "@/components/message";
import { extractMessageBody, RichMessageAttachments, sanitizeMediaUrl, type RichAttachment } from "./rich-text";
import { TraceInspectPage } from "./features/traces/TraceInspectPage";
import { StartupGuidePage } from "./features/onboarding/StartupGuidePage";
import { AttachmentPanel } from "./features/attachments/AttachmentPanel";
import { BotCenterPage } from "./features/bots/BotCenterPage";
import { SettingsCenter } from "./features/settings/SettingsCenter";
import { ActivityCard } from "./features/activity/ActivityCard";
import { ActivityDetailsPanel } from "./features/activity/ActivityDetailsPanel";
import { buildActivityRuns } from "./features/activity/activity-normalizer";
import { presentActivityRun } from "./features/activity/activity-presenter";
import type { ActivityItem, ActivityStatus, ActivityStep } from "./features/activity/activity-types";

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
  turnId?: string;
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
  { title: "执行", views: ["workspace", "tasks", "channels"] },
  { title: "扩展", views: ["plugins", "memory", "model"] },
  { title: "监控", views: ["logs", "attachments", "bots", "traceInspect", "usage", "skills", "users"] }
];

const sidebarNavSections: Array<{ title: string; views: ViewKey[] }> = [
  { title: "Conversations", views: ["chat", "history", "group", "search"] },
  { title: "Runtime", views: ["workspace", "tasks", "channels"] },
  { title: "Extensions", views: ["plugins", "memory", "model", "skills"] },
  { title: "Observability", views: ["logs", "attachments", "traceInspect"] },
  { title: "Bots", views: ["bots"] },
  { title: "Usage", views: ["usage"] },
  { title: "Settings", views: ["users"] }
];

const comingSoonViews = new Set<ViewKey>(["search", "group", "tasks"]);

const inspectorTabs: Array<{ id: InspectorTab; label: string; icon: typeof Activity }> = [
  { id: "status", label: "状态", icon: Activity },
  { id: "tools", label: "工具", icon: Code2 },
  { id: "approvals", label: "审批", icon: ShieldCheck }
];

function BrandLogo() {
  return (
    <div className="brand-mark" aria-hidden="true">
      <svg viewBox="0 0 32 32" role="img">
        <g fill="none" stroke="currentColor" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M23.8 7.8A11.4 11.4 0 1 0 24.6 23.5" />
          <path d="M22 11.3A7.4 7.4 0 1 0 20.4 22.1" />
          <path d="M20.4 16H24.1" />
          <circle cx="26.3" cy="16" r="2.2" />
        </g>
        <circle cx="16" cy="16" r="3" fill="currentColor" />
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
  const middleMode = activeView === "history" ? "sessions" : null;

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
    if (snapshot.activity_blocks?.length) {
      setEvents((current) => ({ ...current, [snapshot.session_id]: current[snapshot.session_id] || [] }));
    } else {
      await hydrateTimelineEvents(snapshot.session_id);
    }
    refreshAttachments(snapshot.session_id);
    stopPollingExcept(snapshot.session_id);
    if (snapshot.history?.source !== "stored") {
      ensureEventPolling(snapshot.session_id);
    }
  }

  async function hydrateTimelineEvents(sessionId: string) {
    try {
      const payload = await api.timeline(sessionId, MAX_SESSION_EVENTS);
      const restored = payload.timeline.map(timelineEntryToRuntimeEvent);
      setEvents((current) => ({ ...current, [sessionId]: mergeRuntimeEvents(current[sessionId] || [], restored) }));
    } catch (error) {
      console.warn("[timeline] failed to hydrate runtime events", { sessionId, error });
      setEvents((current) => ({ ...current, [sessionId]: current[sessionId] || [] }));
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
        {activeView === "chat" || activeView === "history" ? null : (
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
          ) : activeView === "chat" || activeView === "history" ? (
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
          ) : activeView === "usage" ? (
            <UsagePanel />
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
  const [providerPresets, setProviderPresets] = useState<ModelProviderPreset[]>([]);

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
    const [payload, providersPayload] = await Promise.all([
      api.config(sessionId || undefined),
      api.modelProviders()
    ]);
    setSnapshot(payload);
    setProviderPresets(providersPayload.providers);
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

  function updateFieldDraft(field: ConfigField, value: string) {
    if (field.path !== "provider.name") {
      setDrafts((current) => ({ ...current, [field.path]: value }));
      return;
    }
    const preset = providerPresets.find((item) => item.id === value);
    setDrafts((current) => ({
      ...current,
      [field.path]: value,
      ...(preset ? {
        "provider.base_url": preset.default_base_url,
        "provider.api_key_env": preset.default_api_key_env,
        "model.provider": preset.id,
        "model.model": preset.recommended_models[0] || current["model.model"] || ""
      } : {
        "model.provider": value
      })
    }));
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
                  {renderConfigInput(field, drafts[field.path] || "", (value) => updateFieldDraft(field, value))}
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
  const [contextPopoverOpen, setContextPopoverOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const nearBottomRef = useRef(true);
  const turnMarkers = useMemo(() => buildTurnMarkers(transcript), [transcript]);
  const contextSummary = useMemo(() => buildContextSummary(activeSnapshot, activeEvents, activeModel), [activeSnapshot, activeEvents, activeModel]);
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
            <TranscriptMessage item={item} key={item.id} />
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
          <div
            className="composer-context-wrap"
            onMouseEnter={() => setContextPopoverOpen(true)}
            onMouseLeave={() => setContextPopoverOpen(false)}
            onFocusCapture={() => setContextPopoverOpen(true)}
            onBlurCapture={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                setContextPopoverOpen(false);
              }
            }}
          >
            <button
              className="composer-context-button"
              type="button"
              onClick={() => setContextPopoverOpen((current) => !current)}
              title={`Model context: ${contextSummary.modelContextUsage.percentLabel} · ${contextSummary.modelContextUsage.usedLabel} / ${contextSummary.modelContextUsage.totalLabel} tokens\nPipeline budget: ${contextUsageTitle(contextSummary.pipelineBudgetUsage)}`}
              aria-label="Context usage"
            >
              <ContextRing value={contextSummary.modelContextUsage.percent} />
              <span>{contextSummary.modelContextUsage.percentLabel}</span>
            </button>
            {contextPopoverOpen ? (
              <div className="composer-context-popover">
                <div className="composer-context-popover-head">
                  <strong>Context</strong>
                  <span>{contextSummary.pipelineBudgetUsage.source === "actual" ? "Actual report" : "Before build"}</span>
                </div>
                <ContextUsageSection
                  title={contextSummary.modelContextUsage.source === "actual" ? "Model context" : "Estimated model context"}
                  percentLabel={contextSummary.modelContextUsage.percentLabel}
                  detail={`${contextSummary.modelContextUsage.usedLabel} / ${contextSummary.modelContextUsage.totalLabel} tokens`}
                  value={contextSummary.modelContextUsage.percent}
                  badge={contextSummary.modelContextUsage.source === "actual" ? "Actual" : "Estimated"}
                />
                <ContextUsageSection
                  title="Pipeline budget"
                  percentLabel={contextSummary.pipelineBudgetUsage.percentLabel}
                  detail={contextSummary.pipelineBudgetUsage.detailLabel}
                  value={contextSummary.pipelineBudgetUsage.percent}
                  badge={contextSummary.pipelineBudgetUsage.truncated ? "Truncated" : contextSummary.pipelineBudgetUsage.badgeLabel}
                  available={contextSummary.pipelineBudgetUsage.isAvailable}
                />
              </div>
            ) : null}
          </div>
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
  const [providerPresets, setProviderPresets] = useState<ModelProviderPreset[]>([]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [displayModel, setDisplayModel] = useState(activeModel);

  useEffect(() => {
    setDisplayModel(activeModel);
  }, [activeModel]);

  useEffect(() => {
    if (!open) return;
    Promise.all([api.config(activeSessionId || undefined), api.modelProviders()])
      .then(([configPayload, providersPayload]) => {
        setSnapshot(configPayload);
        setProviderPresets(providersPayload.providers);
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [open, activeSessionId]);

  const models = useMemo(() => modelCandidates(snapshot, displayModel, providerPresets), [snapshot, displayModel, providerPresets]);
  const activeProvider = String(readConfigPath(snapshot?.effective_config || {}, "provider.name") || readConfigPath(snapshot?.effective_config || {}, "model.provider") || "");
  const filteredModels = models.filter((candidate) => `${candidate.providerLabel} ${candidate.model}`.toLowerCase().includes(query.trim().toLowerCase()));
  const effortField = snapshot?.schema.fields.find((field) => /reasoning|effort|thinking/i.test(field.path) && field.options?.length);

  async function chooseModel(candidate: ModelCandidate) {
    setBusy(candidate.key);
    setError("");
    try {
      const test = await api.modelTest(
        { name: candidate.providerId, base_url: candidate.baseUrl, api_key_env: candidate.apiKeyEnv },
        { provider: candidate.providerId, model: candidate.model, temperature: 0.2, enable_thinking: false }
      );
      if (test.status !== "ok") {
        const detail = test.safe_detail ? ` ${test.safe_detail}` : "";
        throw new Error(`${test.message}${detail}`);
      }
      if (activeSessionId) {
        await api.setSessionModel(activeSessionId, candidate.model, candidate.providerId || undefined);
      } else {
        const baseHash = snapshot?.config_hash;
        if (candidate.providerId) {
          await api.applyModelPreset(candidate.providerId, candidate.model, baseHash);
        } else {
          await api.configSet("model.model", candidate.model, baseHash);
        }
      }
      setDisplayModel(candidate.model);
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
        <span>{displayModel || "model pending"}</span>
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
            {filteredModels.map((candidate) => (
              <button key={candidate.key} onClick={() => chooseModel(candidate)} disabled={Boolean(busy)} type="button">
                <Monitor size={14} />
                <span>
                  <strong>{candidate.model}</strong>
                  <small>{candidate.providerLabel}</small>
                </span>
                {candidate.model === displayModel && (!candidate.providerId || candidate.providerId === activeProvider) ? <Check size={15} /> : null}
              </button>
            ))}
            {!filteredModels.length ? <div className="composer-popover-empty">No models match this search.</div> : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function UsagePanel() {
  const [rows, setRows] = useState<ModelUsageRow[]>([]);
  const [analytics, setAnalytics] = useState<UsageAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    loadUsage().catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  async function loadUsage() {
    setLoading(true);
    setError('');
    try {
      const payload = await api.modelUsage();
      setRows(payload.models);
      setAnalytics(payload.analytics || null);
    } finally {
      setLoading(false);
    }
  }

  const totals = rows.reduce((acc, row) => ({
    runs: acc.runs + row.runs,
    calls: acc.calls + row.llm_calls,
    tokens: acc.tokens + row.total_tokens,
    cost: acc.cost + (row.total_cost_usd || 0)
  }), { runs: 0, calls: 0, tokens: 0, cost: 0 });
  const configuredCount = rows.filter((row) => row.api_key_configured).length;
  const modelShare = analytics?.model_share?.length
    ? analytics.model_share
    : rows
        .filter((row) => row.total_tokens > 0)
        .map((row) => ({
          provider_id: row.provider_id,
          model: row.model,
          share: totals.tokens ? row.total_tokens / totals.tokens : 0,
          total_tokens: row.total_tokens,
          runs: row.runs
        }))
        .sort((left, right) => right.total_tokens - left.total_tokens);
  const timeline = analytics?.timeline || [];
  const chartSeries = buildUsageChartSeries(analytics, rows);

  return (
    <section className="space-y-4 p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Model Usage</p>
          <h2 className="text-xl font-semibold tracking-tight">Usage dashboard</h2>
          <p className="text-sm text-muted-foreground">Model distribution, token trends, and provider coverage.</p>
        </div>
        <Button variant="outline" size="sm" onClick={loadUsage} disabled={loading}>
          <RefreshCw size={14} />
          Refresh
        </Button>
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Usage load failed</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-3 md:grid-cols-5">
        <UsageMetricCard label="Configured" value={`${configuredCount}/${rows.length}`} />
        <UsageMetricCard label="Runs" value={totals.runs} />
        <UsageMetricCard label="LLM Calls" value={totals.calls} />
        <UsageMetricCard label="Tokens" value={totals.tokens.toLocaleString()} />
        <UsageMetricCard label="Cost" value={totals.cost ? `$${totals.cost.toFixed(6)}` : 'N/A'} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardContent className="space-y-4 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h3 className="text-base font-semibold">Model distribution</h3>
                <p className="text-sm text-muted-foreground">Share by total tokens.</p>
              </div>
              <Badge variant="outline">{modelShare.length} models</Badge>
            </div>
            {loading ? <ChartSkeleton /> : <DonutChart share={modelShare} />}
          </CardContent>
        </Card>

        <Card>
          <CardContent className="space-y-4 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h3 className="text-base font-semibold">Token trend</h3>
                <p className="text-sm text-muted-foreground">Sampled token usage across models.</p>
              </div>
              <Badge variant="outline">{timeline.length} days</Badge>
            </div>
            {loading ? <ChartSkeleton /> : <UsageTrendCard chart={chartSeries} timeline={timeline} />}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="space-y-3 p-4">
              <Skeleton className="h-5 w-56" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : rows.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Provider</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Active</TableHead>
                  <TableHead className="text-right">Runs</TableHead>
                  <TableHead className="text-right">Calls</TableHead>
                  <TableHead className="text-right">Input</TableHead>
                  <TableHead className="text-right">Output</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                  <TableHead className="text-right">Cost</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={`${row.provider_id}:${row.model}`}>
                    <TableCell>
                      <div className="space-y-1">
                        <div className="font-medium">{row.provider_label}</div>
                        <div className="text-xs text-muted-foreground">{row.api_key_env || '-'}</div>
                      </div>
                    </TableCell>
                    <TableCell>{row.model}</TableCell>
                    <TableCell>
                      <Badge variant={row.api_key_configured ? 'secondary' : 'destructive'}>{row.api_key_configured ? 'Configured' : 'Missing env'}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={row.current ? 'default' : 'outline'}>{row.current ? 'Current' : 'Idle'}</Badge>
                    </TableCell>
                    <TableCell className="text-right">{row.runs}</TableCell>
                    <TableCell className="text-right">{row.llm_calls}</TableCell>
                    <TableCell className="text-right">{row.input_tokens.toLocaleString()}</TableCell>
                    <TableCell className="text-right">{row.output_tokens.toLocaleString()}</TableCell>
                    <TableCell className="text-right">{row.total_tokens.toLocaleString()}</TableCell>
                    <TableCell className="text-right">{row.total_cost_usd == null ? 'N/A' : `$${row.total_cost_usd.toFixed(6)}`}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="p-4 text-sm text-muted-foreground">No model usage records.</div>
          )}
        </CardContent>
      </Card>
    </section>
  );
}

function UsageMetricCard({ label, value }: { label: string; value: string | number }) {
  return (
    <Card>
      <CardContent className="space-y-1 p-4">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
        <div className="text-2xl font-semibold tracking-tight">{value}</div>
      </CardContent>
    </Card>
  );
}

function DonutChart({ share }: { share: Array<{ provider_id: string; model: string; share: number; total_tokens: number; runs: number }> }) {
  if (!share.length) {
    return <div className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">No usage data yet.</div>;
  }
  const size = 220;
  const radius = 74;
  const strokeWidth = 24;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  const segments = share.map((item, index) => {
    const dash = item.share * circumference;
    const segment = { ...item, color: USAGE_COLORS[index % USAGE_COLORS.length], dash, gap: circumference - dash, offset };
    offset += dash;
    return segment;
  });
  return (
    <div className="grid gap-4 md:grid-cols-[220px_1fr]">
      <div className="mx-auto flex w-[220px] items-center justify-center">
        <svg viewBox={`0 0 ${size} ${size}`} className="h-[220px] w-[220px]">
          <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="hsl(var(--muted))" strokeWidth={strokeWidth} />
          {segments.map((segment) => (
            <circle
              key={`${segment.provider_id}:${segment.model}`}
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              stroke={segment.color}
              strokeWidth={strokeWidth}
              strokeDasharray={`${segment.dash} ${segment.gap}`}
              strokeDashoffset={-segment.offset}
              strokeLinecap="round"
              transform={`rotate(-90 ${size / 2} ${size / 2})`}
            />
          ))}
        </svg>
      </div>
      <div className="space-y-2">
        {segments.map((segment) => (
          <div key={`${segment.provider_id}:${segment.model}`} className="flex items-center justify-between gap-3 rounded-lg border border-border/60 bg-muted/20 px-3 py-2">
            <div className="flex items-center gap-3">
              <span className="h-3 w-3 rounded-full" style={{ backgroundColor: segment.color }} />
              <div>
                <div className="text-sm font-medium">{segment.model}</div>
                <div className="text-xs text-muted-foreground">{segment.provider_id}</div>
              </div>
            </div>
            <div className="text-right text-sm">
              <div>{Math.round(segment.share * 100)}%</div>
              <div className="text-xs text-muted-foreground">{segment.total_tokens.toLocaleString()} tokens</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function UsageTrendCard({ chart, timeline }: { chart: UsageChart; timeline: Array<{ date: string; runs: number; input_tokens: number; output_tokens: number; total_tokens: number; total_cost_usd: number }> }) {
  return (
    <Card className="usage-trend-card">
      <CardContent className="space-y-3 p-4">
        <h3 className="text-sm font-medium text-foreground">Follower metrics</h3>
        <AreaChart data={chart.data} index="date" categories={chart.categories} colors={chart.colors} showLegend={false} showYAxis={false} showGradient={false} startEndOnly className="h-32" />
        <List className="usage-trend-list">
          {chart.summary.map((item) => (
            <ListItem key={item.name}>
              <span className="usage-trend-name">
                <span className="usage-trend-swatch" style={{ backgroundColor: item.color }} />
                {item.name}
              </span>
              <span className="font-medium text-foreground">{item.value.toLocaleString()}</span>
            </ListItem>
          ))}
        </List>
        <div className="text-xs text-muted-foreground">{timeline.length ? `${formatUsageDateLabel(timeline[0].date)} → ${formatUsageDateLabel(timeline[timeline.length - 1].date)}` : "No timeline data yet."}</div>
      </CardContent>
    </Card>
  );
}

function ContextUsageSection({
  title,
  percentLabel,
  detail,
  value,
  badge,
  available = true
}: {
  title: string;
  percentLabel: string;
  detail: string;
  value?: number;
  badge?: string;
  available?: boolean;
}) {
  return (
    <section className={available ? "composer-context-section" : "composer-context-section unavailable"}>
      <div className="composer-context-section-head">
        <span>{title}</span>
        {badge ? <em>{badge}</em> : null}
      </div>
      <div className="composer-context-popover-percent">
        <strong>{percentLabel}</strong>
        <span>{detail}</span>
      </div>
      {available && typeof value === "number" ? (
        <div className="composer-context-popover-bar" aria-hidden="true">
          <span style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
        </div>
      ) : null}
    </section>
  );
}

function TranscriptMessage({ item, onRetry }: { item: TranscriptItem; onRetry?: () => void }) {
  const [copied, setCopied] = useState(false);
  const from = normalizeMessageRole(item.role);
  const isAssistant = from === "assistant";
  const isUser = from === "user";
  const isActivity = from === "activity";
  const text = item.body.text;

  async function copyMessage() {
    if (!text.trim()) return;
    try {
      await navigator.clipboard?.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  }

  return (
    <Message from={from} streaming={item.streaming} data-transcript-id={item.id}>
      <div className="pp-message-avatar" aria-hidden="true">
        {isAssistant ? <Bot size={16} /> : isActivity ? <Code2 size={15} /> : <MessageSquare size={15} />}
      </div>
      <MessageContent from={from}>
        {isActivity && item.activity ? (
          <ActivityCard item={item.activity} />
        ) : isAssistant ? (
          <>
            <MessageResponse streaming={item.streaming}>{text}</MessageResponse>
            {!item.streaming ? <RichMessageAttachments attachments={item.body.attachments} /> : null}
            {!item.streaming ? <DefaultAssistantActions text={text} copied={copied} onCopy={copyMessage} onRetry={onRetry} /> : null}
          </>
        ) : isUser ? (
          <>
            <MessagePlainText>{text}</MessagePlainText>
            <RichMessageAttachments attachments={item.body.attachments} />
          </>
        ) : (
          <>
            <span className="pp-message-role-label">{roleLabel(from)}</span>
            <MessageResponse>{text}</MessageResponse>
            <RichMessageAttachments attachments={item.body.attachments} />
          </>
        )}
      </MessageContent>
    </Message>
  );
}

function buildUsageChartSeries(analytics: UsageAnalytics | null, rows: ModelUsageRow[]): UsageChart {
  const series = analytics?.series || [];
  const timeline = analytics?.timeline || [];
  const grouped = new Map<string, { provider_id: string; model: string }>();
  series.forEach((point: UsageAnalytics["series"][number]) => {
    const key = usageSeriesKey(point.provider_id, point.model);
    if (!grouped.has(key)) grouped.set(key, { provider_id: point.provider_id, model: point.model });
  });
  if (!grouped.size) {
    rows.filter((row) => row.total_tokens > 0).forEach((row) => {
      const key = usageSeriesKey(row.provider_id, row.model);
      if (!grouped.has(key)) grouped.set(key, { provider_id: row.provider_id, model: row.model });
    });
  }
  const entries = Array.from(grouped.values());
  const categories = entries.map((item) => usageSeriesKey(item.provider_id, item.model));
  const colors = entries.map((_, index) => USAGE_COLORS[index % USAGE_COLORS.length]);
  const data = timeline.map((day: UsageAnalytics["timeline"][number]) => {
    const row: Record<string, string | number> = { date: day.date };
    categories.forEach((category) => {
      row[category] = 0;
    });
    return row;
  });
  series.forEach((point: UsageAnalytics["series"][number]) => {
    const category = usageSeriesKey(point.provider_id, point.model);
    const dayRow = data.find((entry) => entry.date === point.date);
    if (dayRow) dayRow[category] = point.total_tokens;
  });
  const summary = entries.map((item, index) => {
    const category = usageSeriesKey(item.provider_id, item.model);
    const value = data.reduce((total, row) => total + Number(row[category] || 0), 0) || rows.find((row) => row.provider_id === item.provider_id && row.model === item.model)?.total_tokens || 0;
    return { name: item.model, value, color: colors[index] };
  });
  return { data, categories, colors, summary, timeline };
}

function usageSeriesKey(providerId: string, model: string) {
  return `${providerId}_${model}`.replace(/[^a-zA-Z0-9_]/g, "_");
}

function formatUsageDateLabel(value: string) {
  if (!value) return "-";
  const numeric = Number(value);
  if (Number.isFinite(numeric)) {
    const normalized = numeric > 10_000_000_000 ? numeric : numeric * 1000;
    const date = new Date(normalized);
    if (!Number.isNaN(date.getTime())) return date.toLocaleDateString();
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

type UsageChart = {
  data: Array<Record<string, string | number>>;
  categories: string[];
  colors: string[];
  summary: Array<{ name: string; value: number; color: string }>;
  timeline: Array<{ date: string; runs: number; input_tokens: number; output_tokens: number; total_tokens: number; total_cost_usd: number }>;
};

function AreaChart({
  data,
  index,
  categories,
  colors,
  showLegend = false,
  showYAxis = false,
  showGradient = false,
  startEndOnly = false,
  className = ""
}: {
  data: Array<Record<string, string | number>>;
  index: string;
  categories: string[];
  colors: string[];
  showLegend?: boolean;
  showYAxis?: boolean;
  showGradient?: boolean;
  startEndOnly?: boolean;
  className?: string;
}) {
  if (!data.length || !categories.length) {
    return <div className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">No usage data yet.</div>;
  }
  const width = 720;
  const height = 132;
  const paddingX = 18;
  const paddingY = 10;
  const xStep = data.length > 1 ? (width - paddingX * 2) / (data.length - 1) : 0;
  const values = data.flatMap((row: Record<string, string | number>) => categories.map((category: string) => Number(row[category] || 0)));
  const maxValue = Math.max(1, ...values);
  const yScale = (value: number) => height - paddingY - (value / maxValue) * (height - paddingY * 2);
  const buildPath = (category: string) => {
    const points = data.map((row: Record<string, string | number>, pointIndex: number) => `${pointIndex === 0 ? "M" : "L"} ${paddingX + pointIndex * xStep} ${yScale(Number(row[category] || 0))}`).join(" ");
    const firstX = paddingX;
    const lastX = paddingX + (data.length - 1) * xStep;
    if (data.length === 1) {
      const y = yScale(Number(data[0][category] || 0));
      return `M ${firstX} ${y} L ${firstX + 1} ${y}`;
    }
    return `${points} L ${lastX} ${height - paddingY} L ${firstX} ${height - paddingY} Z`;
  };
  return (
    <div className={className ? `space-y-3 ${className}` : "space-y-3"}>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-32 w-full overflow-visible">
        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => (
          <line
            key={ratio}
            x1={paddingX}
            x2={width - paddingX}
            y1={paddingY + ratio * (height - paddingY * 2)}
            y2={paddingY + ratio * (height - paddingY * 2)}
            stroke="var(--border)"
            strokeWidth="1"
            strokeDasharray="4 4"
            opacity={ratio === 1 || ratio === 0 ? 0.6 : 0.35}
          />
        ))}
        {categories.map((category, index) => (
          <path key={category} d={buildPath(category)} fill={colors[index % colors.length]} opacity={0.14 + index * 0.03} />
        ))}
        {categories.map((category, index) => (
          <path
            key={`${category}-line`}
            d={data.map((row, pointIndex) => `${pointIndex === 0 ? "M" : "L"} ${paddingX + pointIndex * xStep} ${yScale(Number(row[category] || 0))}`).join(" ")}
            fill="none"
            stroke={colors[index % colors.length]}
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ))}
        {data.map((row, pointIndex) => (
          <g key={String(row[index])}>
            {categories.map((category, categoryIndex) => {
              const value = Number(row[category] || 0);
              if (!value) return null;
              return <circle key={`${category}-${pointIndex}`} cx={paddingX + pointIndex * xStep} cy={yScale(value)} r={data.length === 1 ? 4 : 3} fill={colors[categoryIndex % colors.length]} />;
            })}
          </g>
        ))}
        {data.length > 0 ? (
          <>
            <text x={paddingX} y={height - 2} className="fill-muted-foreground text-[10px]">
              {String(data[0][index])}
            </text>
            {data.length > 1 ? (
              <text x={width - paddingX} y={height - 2} textAnchor="end" className="fill-muted-foreground text-[10px]">
                {String(data[data.length - 1][index])}
              </text>
            ) : null}
          </>
        ) : null}
      </svg>
    </div>
  );
}

function ChartSkeleton() {
  return <div className="h-[220px] animate-pulse rounded-lg border border-dashed bg-muted/20" />;
}

const USAGE_COLORS = ['#6366f1', '#14b8a6', '#f59e0b', '#ef4444', '#8b5cf6', '#22c55e', '#06b6d4'];

type ModelCandidate = {
  key: string;
  providerId: string;
  providerLabel: string;
  model: string;
  baseUrl: string;
  apiKeyEnv: string;
};

function modelCandidates(snapshot: ConfigSnapshot | null, activeModel: string, providerPresets: ModelProviderPreset[]): ModelCandidate[] {
  const values = new Map<string, ModelCandidate>();
  providerPresets.forEach((provider) => {
    provider.recommended_models.forEach((model) => {
      const key = `${provider.id}:${model}`;
      values.set(key, { key, providerId: provider.id, providerLabel: provider.label, model, baseUrl: provider.default_base_url, apiKeyEnv: provider.default_api_key_env });
    });
  });
  const configuredProvider = String(readConfigPath(snapshot?.effective_config || {}, "provider.name") || readConfigPath(snapshot?.effective_config || {}, "model.provider") || "");
  const configuredProviderLabel = providerPresets.find((provider) => provider.id === configuredProvider)?.label || modelProviderLabel(configuredProvider);
  const modelField = snapshot?.schema.fields.find((field) => field.path === "model.model");
  modelField?.options?.forEach((option) => {
    const key = `${configuredProvider || "current"}:${option}`;
    if (!values.has(key)) values.set(key, { key, providerId: configuredProvider, providerLabel: configuredProviderLabel, model: option, baseUrl: String(readConfigPath(snapshot?.effective_config || {}, "provider.base_url") || ""), apiKeyEnv: String(readConfigPath(snapshot?.effective_config || {}, "provider.api_key_env") || "") });
  });
  const configured = snapshot ? readConfigPath(snapshot.effective_config, "model.model") : "";
  if (typeof configured === "string" && configured.trim()) {
    const model = configured.trim();
    const key = `${configuredProvider || "current"}:${model}`;
    if (!values.has(key)) values.set(key, { key, providerId: configuredProvider, providerLabel: configuredProviderLabel, model, baseUrl: String(readConfigPath(snapshot?.effective_config || {}, "provider.base_url") || ""), apiKeyEnv: String(readConfigPath(snapshot?.effective_config || {}, "provider.api_key_env") || "") });
  }
  if (activeModel.trim()) {
    const model = activeModel.trim();
    const key = `${configuredProvider || "current"}:${model}`;
    if (!values.has(key)) values.set(key, { key, providerId: configuredProvider, providerLabel: configuredProviderLabel, model, baseUrl: String(readConfigPath(snapshot?.effective_config || {}, "provider.base_url") || ""), apiKeyEnv: String(readConfigPath(snapshot?.effective_config || {}, "provider.api_key_env") || "") });
  }
  return Array.from(values.values()).filter((candidate) => candidate.model);
}

function modelProviderLabel(model: string) {
  const lower = model.toLowerCase();
  if (lower.includes("qwen")) return "Qwen";
  if (lower.includes("mimo")) return "Xiaomi MiMo";
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
  const narrative = activity.narrative || activity.summary || activity.detail || "";
  const detailText = entries
    .map((entry) => entry.narrative || entry.detail)
    .filter((value): value is string => Boolean(value && value.trim()))
    .join("\n\n");
  return (
    <div className={`tool-activity ${activity.tone || "success"}`}>
      <div className="tool-activity-head">
        <span className="tool-activity-status">{activity.title}</span>
        {activity.durationLabel ? <span className="tool-activity-duration">· {activity.durationLabel}</span> : null}
      </div>
      {narrative ? <p className="tool-activity-narrative">{narrative}</p> : null}
      {commandCount > 0 ? <p className="tool-activity-command-count">已运行 {commandCount} 条命令</p> : null}
      {detailText ? <p className="tool-activity-detail-text">{detailText}</p> : null}
      {entries.length === 0 ? <RichMessageAttachments attachments={item.body.attachments} /> : null}
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
              <span className="capability-card-menu" aria-hidden="true">?</span>
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

function normalizeMessageRole(role: string) {
  if (role === "assistant" || role === "user" || role === "activity" || role === "error" || role === "tool" || role === "system") return role;
  return role.includes("tool") ? "tool" : role.includes("system") ? "system" : role;
}

export function buildTranscript(snapshot?: SessionSnapshot, events: RuntimeEvent[] = []): TranscriptItem[] {
  const committedMessages = snapshot?.messages || [];
  const persistedActivityBlocks = snapshot?.activity_blocks || [];
  const hasPersistedActivityBlocks = persistedActivityBlocks.length > 0;
  const stored: TranscriptItem[] = committedMessages
    .filter((message) => message.role === "user" || message.role === "assistant")
    .map((message, index) => ({
      id: `stored:${index}`,
      role: message.role,
      body: extractMessageBody(message),
      timestamp: typeof message.timestamp === "number" ? message.timestamp : index + 1,
      turnId: inferredMessageTurnId(message, index, committedMessages)
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
      if (!hasPersistedActivityBlocks) appendActivityEvent(event);
      continue;
    }
    if (event.type === "turn_end" || event.type === "agent_end") {
      flushStream();
      if (!hasPersistedActivityBlocks) {
        appendActivityEvent(event);
        flushActivityGroup();
      }
      continue;
    }
    if (event.is_error && event.message) {
      flushStream();
      if (isActivityEvent(event) && !hasPersistedActivityBlocks) {
        appendActivityEvent(event);
      } else {
        runtime.push({ id: `error:${runtime.length}`, role: "error", body: { text: formatErrorEvent(event), attachments: [] }, timestamp: event.timestamp });
      }
      continue;
    }
    if (isActivityEvent(event)) {
      flushStream();
      if (!hasPersistedActivityBlocks) appendActivityEvent(event);
      continue;
    }
  }

  flushStream();
  flushActivityGroup();
  if (!hasPersistedActivityBlocks) activityGroups.forEach((group, index) => {
    const activity = combineActivityItemsForTranscript(buildActivityRuns(group), group);
    if (!activity) return;
    const bodyText = [activity.narrative || activity.summary || activity.detail, activity.detail].filter(Boolean).join("\n\n");
    const turnId = groupTurnId(group);
    runtime.push({
      id: `activity-turn:${index}:${activity.startedAt || activity.endedAt || runtime.length}`,
      role: "activity",
      body: { text: bodyText, attachments: activity.entries?.flatMap((entry) => entry.attachments || []) || [] },
      timestamp: activity.endedAt || activity.startedAt,
      activity,
      turnId
    });
  });
  const baseItems = [...stored, ...runtime].sort((left, right) => {
    const leftTime = left.timestamp || 0;
    const rightTime = right.timestamp || 0;
    if (leftTime !== rightTime) return leftTime - rightTime;
    return 0;
  });
  const persistedItems = persistedActivityBlocks.map(persistedActivityBlockToTranscriptItem);
  const items = insertActivityItemsBeforeAssistant(baseItems, persistedItems);
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
  const phase = items.some((item) => item.phase === "preparing" || item.phase === "analyzing" || item.phase === "finalizing") ? "analyzing" : items.some((item) => item.phase === "planning") ? "planning" : "tool";
  const narrative = presentActivityRun(`turn-activity:${startedAt || items[0].id}`, phase, status, events, entries);
  return {
    id: `turn-activity:${startedAt || items[0].id}`,
    phase,
    status,
    tone: status,
    title: narrative.title,
    summary: narrative.summary,
    narrative: narrative.narrative,
    display: narrative.display,
    detail: narrative.detail || detail,
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

function persistedActivityBlockToTranscriptItem(block: PersistedActivityBlock): TranscriptItem {
  const timestamp = normalizePersistedTimestamp(block.created_at);
  const status = block.status === "error" ? "error" : block.status === "running" ? "running" : "success";
  const entries = (block.items || []).map((item, index) => {
    const entryStatus: ActivityStatus = item.status === "error" ? "error" : item.status === "running" ? "running" : "success";
    const entryTimestamp = normalizePersistedTimestamp(item.timestamp);
    return {
      id: `${block.id || block.turn_id}:item:${index}`,
      kind: persistedActivityStepKind(item.kind),
      label: item.title || item.kind || "Activity",
      detail: item.detail || item.summary || "",
      narrative: item.summary || item.detail || "",
      timestamp: entryTimestamp,
      startedAt: entryTimestamp,
      endedAt: entryStatus === "running" ? undefined : entryTimestamp,
      status: entryStatus,
      tone: entryStatus,
      rawType: item.kind,
    };
  });
  const detail = entries.map((entry) => [entry.label, entry.detail].filter(Boolean).join("\n")).filter(Boolean).join("\n\n");
  const durationLabel = typeof block.duration_ms === "number" && block.duration_ms > 0 ? formatDuration(block.duration_ms) : "";
  const activity: ActivityItem = {
    id: `activity-block:${block.id || block.turn_id}`,
    activityId: block.id || block.turn_id,
    phase: entries.some((entry) => entry.kind === "tool" || entry.kind === "command") ? "tool" : entries.some((entry) => entry.kind === "planner") ? "planning" : "analyzing",
    status,
    tone: status,
    title: block.title || "分析进展",
    summary: block.summary || "我已经记录了本轮的公开运行过程。",
    narrative: block.summary,
    detail: detail || block.summary || "",
    timestamp,
    startedAt: entries.find((entry) => typeof entry.timestamp === "number")?.timestamp || timestamp,
    endedAt: status === "running" ? undefined : timestamp,
    durationMs: block.duration_ms || undefined,
    durationLabel,
    running: status === "running",
    entries,
    eventCount: block.event_count || entries.length,
    toolCount: entries.filter((entry) => entry.kind === "tool" || entry.kind === "command").length,
    approvalCount: entries.filter((entry) => entry.kind === "approval").length,
    errorCount: status === "error" ? 1 : entries.filter((entry) => entry.status === "error").length,
  };
  return {
    id: `persisted-activity:${block.id || block.turn_id}`,
    role: "activity",
    body: { text: [activity.summary, activity.detail].filter(Boolean).join("\n\n"), attachments: [] },
    timestamp,
    activity,
    turnId: normalizeTurnId(block.turn_id),
  };
}

function insertActivityItemsBeforeAssistant(items: TranscriptItem[], persisted: TranscriptItem[]) {
  const activityItems = [...persisted, ...items.filter((item) => item.role === "activity")];
  const nonActivityItems = items.filter((item) => item.role !== "activity");
  const activityByTurn = new Map<string, TranscriptItem[]>();
  const orphanActivities: TranscriptItem[] = [];
  for (const item of activityItems) {
    const turnId = normalizeTurnId(item.turnId);
    if (turnId) {
      const bucket = activityByTurn.get(turnId) || [];
      bucket.push(item);
      activityByTurn.set(turnId, bucket);
    } else {
      orphanActivities.push(item);
    }
  }
  activityByTurn.forEach((bucket) => bucket.sort(activityDisplayOrder));
  orphanActivities.sort(activityDisplayOrder);

  const result: TranscriptItem[] = [];
  const used = new Set<string>();
  for (const item of nonActivityItems) {
    if (item.role === "assistant") {
      const turnId = normalizeTurnId(item.turnId);
      const matches = turnId ? activityByTurn.get(turnId) || [] : [];
      for (const activity of matches) {
        if (used.has(activity.id)) continue;
        result.push(activity);
        used.add(activity.id);
      }
      if (!turnId && orphanActivities.length) {
        const activity = orphanActivities.shift();
        if (activity && !used.has(activity.id)) {
          result.push(activity);
          used.add(activity.id);
        }
      }
    }
    result.push(item);
  }
  const remaining = [...activityByTurn.values()].flat().filter((item) => !used.has(item.id));
  for (const item of [...orphanActivities, ...remaining].sort(activityDisplayOrder)) {
    insertOrphanActivityBeforeNearestAssistant(result, item);
    used.add(item.id);
  }
  return result;
}

function insertOrphanActivityBeforeNearestAssistant(items: TranscriptItem[], activity: TranscriptItem) {
  const activityTime = activity.timestamp || 0;
  let bestIndex = -1;
  let bestDistance = Number.POSITIVE_INFINITY;
  items.forEach((item, index) => {
    if (item.role !== "assistant") return;
    const distance = Math.abs((item.timestamp || 0) - activityTime);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  });
  if (bestIndex >= 0) {
    items.splice(bestIndex, 0, activity);
    return;
  }
  const sortedIndex = items.findIndex((item) => (item.timestamp || 0) > activityTime);
  if (sortedIndex >= 0) items.splice(sortedIndex, 0, activity);
  else items.push(activity);
}

function activityDisplayOrder(left: TranscriptItem, right: TranscriptItem) {
  return (left.timestamp || 0) - (right.timestamp || 0);
}

function persistedActivityStepKind(kind: string): ActivityStep["kind"] {
  if (kind === "tool" || kind === "command" || kind === "planner" || kind === "subagent" || kind === "checkpoint" || kind === "approval" || kind === "memory" || kind === "system" || kind === "message" || kind === "event") return kind;
  if (kind === "progress" || kind === "context") return "progress";
  return "event";
}

function normalizePersistedTimestamp(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value > 10_000_000_000 ? value / 1000 : value;
  if (typeof value === "string") {
    const asNumeric = Number(value);
    if (Number.isFinite(asNumeric)) return asNumeric > 10_000_000_000 ? asNumeric / 1000 : asNumeric;
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed)) return parsed / 1000;
  }
  return undefined;
}

function inferredMessageTurnId(message: SessionSnapshot["messages"][number], index: number, messages: SessionSnapshot["messages"]) {
  const explicit = normalizeTurnId(readMessageTurnId(message));
  if (explicit) return explicit;
  let turn = 0;
  for (let current = 0; current <= index; current += 1) {
    const item = messages[current];
    if (item.role === "user") turn += 1;
    if (current === index) break;
  }
  return turn > 0 ? String(turn) : "";
}

function readMessageTurnId(message: SessionSnapshot["messages"][number]) {
  const direct = (message as unknown as Record<string, unknown>).turn_id;
  if (direct != null) return direct;
  const metadata = message.metadata || {};
  return metadata.turn_id ?? metadata.turnId;
}

function groupTurnId(events: RuntimeEvent[]) {
  for (const event of events) {
    const turnId = normalizeTurnId(event.turn_id ?? event.details?.turn_id);
    if (turnId) return turnId;
  }
  return "";
}

function normalizeTurnId(value: unknown) {
  if (value === undefined || value === null) return "";
  const text = String(value).trim();
  if (!text) return "";
  const match = text.match(/^turn-(\d+)$/i);
  return match ? match[1] : text;
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

export function timelineEntryToRuntimeEvent(entry: TimelineEntry): RuntimeEvent {
  const details = parseDetailsSafely(entry.details);
  const embedded = isRecord(details.runtime_event)
    ? details.runtime_event
    : isRecord(details.event)
      ? details.event
      : {};
  const nestedDetails = isRecord(embedded.details) ? embedded.details : isRecord(details.details) ? details.details : {};
  const rawType =
    asString(embedded.type) ||
    asString(details.type) ||
    asString(details.runtime_event_type) ||
    asString(entry.event_type);
  const type = normalizeTimelineRuntimeType(rawType, entry, details);

  return {
    ...embedded,
    type,
    session_id: entry.session_id,
    timestamp: normalizeRuntimeTimestamp(
      asNumber(embedded.timestamp) ??
      asNumber(details.timestamp) ??
      entry.created_at
    ),
    turn_id: asNumber(embedded.turn_id) ?? asNumber(details.turn_id) ?? entry.turn_id ?? null,
    phase: asString(embedded.phase) ?? asString(details.phase) ?? entry.phase ?? null,
    tool_name: asString(embedded.tool_name) ?? asString(details.tool_name) ?? entry.tool_name ?? null,
    message: asString(embedded.message) ?? asString(details.message) ?? entry.message ?? null,
    is_error: Boolean(embedded.is_error ?? details.is_error ?? entry.is_error),
    plan_step: isPlanStep(embedded.plan_step) ? embedded.plan_step : isPlanStep(details.plan_step) ? details.plan_step : entry.plan_step ?? null,
    details: {
      ...details,
      ...nestedDetails,
      timeline_id: entry.id,
      timeline_entry_id: entry.id,
      timeline_event_type: entry.event_type,
    },
  };
}

export function mergeRuntimeEvents(existing: RuntimeEvent[], incoming: RuntimeEvent[]) {
  const merged = new Map<string, RuntimeEvent>();
  for (const event of [...existing, ...incoming]) {
    const key = runtimeEventDedupeKey(event);
    if (merged.has(key)) continue;
    merged.set(key, event);
  }
  return [...merged.values()]
    .sort((left, right) => (left.timestamp || 0) - (right.timestamp || 0))
    .slice(-MAX_SESSION_EVENTS);
}

function runtimeEventDedupeKey(event: RuntimeEvent) {
  const details = event.details || {};
  const trace = details.trace && typeof details.trace === "object" ? details.trace as Record<string, unknown> : {};
  const activity = details.activity && typeof details.activity === "object" ? details.activity as Record<string, unknown> : {};
  const explicit = event.event_id || details.timeline_id || details.timeline_entry_id || trace.event_id || activity.event_id || details.event_id;
  if (typeof explicit === "string" && explicit.trim()) return explicit;
  if (typeof explicit === "number") return String(explicit);
  return runtimeEventKey(event);
}

function parseDetailsSafely(details: unknown): Record<string, unknown> {
  if (isRecord(details)) return details;
  if (typeof details !== "string") return {};
  try {
    const parsed = JSON.parse(details);
    return isRecord(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function normalizeTimelineRuntimeType(rawType: string | undefined, entry: TimelineEntry, details: Record<string, unknown>) {
  const type = rawType || "";
  if (
    type.startsWith("reasoning_") ||
    type.startsWith("planner_") ||
    type.startsWith("tool_") ||
    type === "before_provider_request" ||
    type === "provider_response" ||
    type === "context_built" ||
    type === "approval_gate" ||
    type === "approval_result" ||
    type === "error"
  ) {
    return type;
  }

  const text = `${entry.event_type ?? ""} ${entry.phase ?? ""} ${entry.message ?? ""} ${asString(details.phase) ?? ""} ${asString(details.message) ?? ""}`.toLowerCase();
  if (entry.tool_name || details.tool_name) {
    if (
      details.result ||
      details.output ||
      details.stdout ||
      details.stderr ||
      text.includes("result") ||
      text.includes("finish") ||
      text.includes("complete")
    ) {
      return "tool_result";
    }
    return "tool_start";
  }
  if (text.includes("reasoning")) return "reasoning_summary";
  if (text.includes("planner") || text.includes("plan")) return "planner_update";
  if (text.includes("provider")) return "provider_response";
  if (text.includes("context")) return "context_built";
  if (text.includes("approval")) return "approval_gate";
  if (text.includes("error") || entry.is_error || details.is_error) return "error";
  return type || "runtime_event";
}

function normalizeRuntimeTimestamp(value: unknown) {
  const numeric = asNumber(value);
  if (numeric != null) return numeric > 10_000_000_000 ? numeric / 1000 : numeric;
  if (typeof value === "string") {
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed)) return parsed / 1000;
  }
  return Date.now() / 1000;
}

function asString(value: unknown) {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function asNumber(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isPlanStep(value: unknown): value is RuntimeEvent["plan_step"] {
  return isRecord(value) && typeof value.title === "string";
}

type ContextUsageSource = "actual" | "configured" | "estimated" | "unavailable";

type ContextSummary = {
  modelContextUsage: {
    usedTokens: number;
    totalTokens: number;
    percent: number;
    percentLabel: string;
    usedLabel: string;
    totalLabel: string;
    source: ContextUsageSource;
    isAvailable: boolean;
  };
  pipelineBudgetUsage: {
    usedChars?: number;
    totalChars?: number;
    percent?: number;
    percentLabel: string;
    usedLabel: string;
    totalLabel: string;
    detailLabel: string;
    badgeLabel?: string;
    source: ContextUsageSource;
    isAvailable: boolean;
    truncated: boolean;
  };
};

export function buildContextSummary(snapshot?: SessionSnapshot, events: RuntimeEvent[] = [], activeModel = ""): ContextSummary {
  const totalTokens = Math.max(1, firstNumber(latestContextValue(events, "context_window_tokens"), latestContextValue(events, "context_window"), inferModelContextWindowTokens(activeModel), 128_000) || 128_000);
  const actualInputTokens = firstNumber(latestContextValue(events, "input_tokens"), latestContextValue(events, "prompt_tokens"));
  const estimatedInputTokens = estimateModelInputTokens(snapshot, events);
  const usedTokens = Math.max(0, actualInputTokens ?? estimatedInputTokens);
  const modelPercent = totalTokens > 0 ? Math.min(1, usedTokens / totalTokens) : 0;

  const actualPipelineTotal = latestContextValue(events, "context_total_budget", "context_built");
  const actualPipelineUsed = latestContextValue(events, "context_used", "context_built");
  const configuredPipelineTotal = latestConfiguredPipelineBudget(snapshot, events);
  const pipelineTruncated = Boolean(actualPipelineTotal != null && (latestContextFlag(events, "truncated") || latestContextDroppedCount(events) > 0));
  const pipelineTotal = actualPipelineTotal ?? configuredPipelineTotal;
  const pipelineUsed = actualPipelineTotal != null ? Math.max(0, actualPipelineUsed ?? 0) : undefined;
  const pipelinePercent = pipelineTotal && pipelineUsed != null ? Math.min(1, pipelineUsed / pipelineTotal) : undefined;
  const pipelineSource: ContextUsageSource = actualPipelineTotal != null ? "actual" : configuredPipelineTotal != null ? "configured" : "unavailable";
  const pipelineAvailable = pipelineSource !== "unavailable";
  const pipelineDetailLabel = pipelineSource === "actual" && pipelineUsed != null && pipelineTotal != null
    ? `${formatCompactNumber(pipelineUsed)} / ${formatCompactNumber(pipelineTotal)} chars`
    : pipelineSource === "configured" && pipelineTotal != null
      ? `${formatCompactNumber(pipelineTotal)} chars configured`
      : "Will appear after context is built";

  return {
    modelContextUsage: {
      usedTokens,
      totalTokens,
      percent: modelPercent,
      percentLabel: formatPercent(modelPercent),
      usedLabel: formatCompactNumber(usedTokens),
      totalLabel: formatCompactNumber(totalTokens),
      source: actualInputTokens != null ? "actual" : "estimated",
      isAvailable: true,
    },
    pipelineBudgetUsage: {
      usedChars: pipelineUsed,
      totalChars: pipelineTotal,
      percent: pipelinePercent,
      percentLabel: pipelinePercent != null ? formatPercent(pipelinePercent) : "Not built yet",
      usedLabel: pipelineUsed != null ? formatCompactNumber(pipelineUsed) : "",
      totalLabel: pipelineTotal != null ? formatCompactNumber(pipelineTotal) : "Not built yet",
      detailLabel: pipelineDetailLabel,
      badgeLabel: pipelineSource === "actual" ? "Actual" : pipelineSource === "configured" ? "Configured" : "Not built",
      source: pipelineSource,
      isAvailable: pipelineAvailable,
      truncated: pipelineTruncated,
    },
  };
}

function latestContextValue(events: RuntimeEvent[], key: "context_used" | "context_total_budget" | "context_window" | "context_window_tokens" | "input_tokens" | "prompt_tokens" | "output_tokens" | "total_cost_usd", eventType?: "context_built") {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    const details = event.details || {};
    const isContextBuilt = event.type === "context_built" || event.type === "context.build";
    if (isContextBuilt || (!eventType && event.type === "provider_response")) {
      const value = details[key] ?? contextValueAlias(details, key);
      const n = typeof value === "number" ? value : typeof value === "string" ? Number(value) : NaN;
      if (Number.isFinite(n)) return n;
      const context = details.context && typeof details.context === "object" ? details.context as Record<string, unknown> : {};
      const report = context.budget_report && typeof context.budget_report === "object" ? context.budget_report as Record<string, unknown> : {};
      const fallback = report[key === "context_used" ? "used" : key === "context_total_budget" ? "total_budget" : key] ?? contextValueAlias(report, key);
      const fallbackNumber = typeof fallback === "number" ? fallback : typeof fallback === "string" ? Number(fallback) : NaN;
      if (Number.isFinite(fallbackNumber)) return fallbackNumber;
    }
  }
  return undefined;
}

function contextValueAlias(source: Record<string, unknown>, key: "context_used" | "context_total_budget" | "context_window" | "context_window_tokens" | "input_tokens" | "prompt_tokens" | "output_tokens" | "total_cost_usd") {
  if (key === "context_used") return source.used ?? source.total_used ?? source.packed_size ?? source.estimated_chars;
  if (key === "context_total_budget") return source.total_budget;
  return undefined;
}

function latestConfiguredPipelineBudget(snapshot?: SessionSnapshot, events: RuntimeEvent[] = []) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const details = events[index].details || {};
    const configured = firstNumber(
      readNumberPath(details, ["context_pipeline", "total_budget"]),
      readNumberPath(details, ["contextPipeline", "totalBudget"]),
      readNumberPath(details, ["config", "context_pipeline", "total_budget"]),
      readNumberPath(details, ["settings", "context_pipeline", "total_budget"]),
      readNumberPath(details, ["effective_config", "context_pipeline", "total_budget"]),
    );
    if (configured != null) return configured;
  }
  const snapshotRecord = snapshot as unknown as Record<string, unknown> | undefined;
  return firstNumber(
    readNumberPath(snapshotRecord, ["context_pipeline", "total_budget"]),
    readNumberPath(snapshotRecord, ["config", "context_pipeline", "total_budget"]),
    readNumberPath(snapshotRecord, ["settings", "context_pipeline", "total_budget"]),
    readNumberPath(snapshotRecord, ["effective_config", "context_pipeline", "total_budget"]),
  );
}

function readNumberPath(source: unknown, path: string[]) {
  let current = source;
  for (const part of path) {
    if (!isRecord(current)) return undefined;
    current = current[part];
  }
  return asNumber(current);
}

function contextUsageTitle(usage: ContextSummary["pipelineBudgetUsage"]) {
  if (usage.source === "actual" && usage.percentLabel && usage.usedLabel && usage.totalLabel) {
    return `${usage.percentLabel} · ${usage.usedLabel} / ${usage.totalLabel} chars`;
  }
  if (usage.source === "configured" && usage.totalLabel) return `${usage.totalLabel} chars configured`;
  return "Not built yet";
}

function latestContextFlag(events: RuntimeEvent[], key: "truncated") {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    const details = event.details || {};
    if (event.type !== "context_built" && event.type !== "context.build") continue;
    const direct = details[key];
    if (typeof direct === "boolean") return direct;
    const context = details.context && typeof details.context === "object" ? details.context as Record<string, unknown> : {};
    const report = context.budget_report && typeof context.budget_report === "object" ? context.budget_report as Record<string, unknown> : {};
    const fromContext = context[key];
    if (typeof fromContext === "boolean") return fromContext;
    const fromReport = report[key];
    if (typeof fromReport === "boolean") return fromReport;
  }
  return false;
}

function latestContextDroppedCount(events: RuntimeEvent[]) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    const details = event.details || {};
    if (event.type !== "context_built" && event.type !== "context.build") continue;
    const context = details.context && typeof details.context === "object" ? details.context as Record<string, unknown> : {};
    const report = context.budget_report && typeof context.budget_report === "object" ? context.budget_report as Record<string, unknown> : {};
    const droppedSources = context.dropped_sources;
    if (Array.isArray(droppedSources)) return droppedSources.length;
    const droppedItems = report.dropped_items;
    if (Array.isArray(droppedItems)) return droppedItems.length;
  }
  return 0;
}

function estimateModelInputTokens(snapshot?: SessionSnapshot, events: RuntimeEvent[] = []) {
  const estimatedContextTokens = firstNumber(latestContextValue(events, "context_used"));
  if (estimatedContextTokens != null) return Math.ceil(estimatedContextTokens / 4);
  const textChars = (snapshot?.messages || []).reduce((total, message) => {
    const parts = Array.isArray(message.content) ? message.content : [];
    return total + parts.reduce((innerTotal, part) => innerTotal + (part.type === "text" && typeof part.text === "string" ? part.text.length : 0), 0);
  }, 0);
  if (textChars > 0) return Math.ceil(textChars / 4);
  return Math.max(0, (snapshot?.history?.visible_message_count || snapshot?.history?.returned_message_count || 0) * 250);
}

function inferModelContextWindowTokens(model: string) {
  const lowered = model.toLowerCase();
  const explicit = lowered.match(/(\d+(?:\.\d+)?)\s*(m|k)\b/);
  if (explicit) {
    const value = Number(explicit[1]);
    if (Number.isFinite(value)) return Math.round(value * (explicit[2] === "m" ? 1_000_000 : 1_000));
  }
  if (lowered.includes("qwen3-max") || lowered.includes("qwen-max") || lowered.includes("qwen-plus")) return 320_000;
  if (lowered.includes("gpt-4.1")) return 1_000_000;
  if (lowered.includes("gpt-4o")) return 128_000;
  if (lowered.includes("claude")) return 200_000;
  if (lowered.includes("deepseek")) return 128_000;
  if (lowered.includes("mimo")) return 128_000;
  return undefined;
}

function firstNumber(...values: Array<number | undefined>) {
  for (const value of values) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return undefined;
}

function formatCompactNumber(value: number) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${Math.round(value / 1_000)}K`;
  return String(Math.round(value));
}

function formatPercent(value: number) {
  return `${(Math.max(0, Math.min(1, value)) * 100).toFixed(1)}%`;
}

function ContextRing({ value }: { value: number }) {
  const radius = 10;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference * (1 - Math.max(0, Math.min(1, value)));
  return (
    <svg aria-hidden="true" height="20" viewBox="0 0 24 24" width="20">
      <circle cx="12" cy="12" fill="none" opacity="0.22" r={radius} stroke="currentColor" strokeWidth="2" />
      <circle
        cx="12"
        cy="12"
        fill="none"
        opacity="0.92"
        r={radius}
        stroke="currentColor"
        strokeDasharray={`${circumference} ${circumference}`}
        strokeDashoffset={dashOffset}
        strokeLinecap="round"
        strokeWidth="2"
        style={{ transform: "rotate(-90deg)", transformOrigin: "center" }}
      />
    </svg>
  );
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


