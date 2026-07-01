"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.App = App;
exports.buildTranscript = buildTranscript;
exports.buildTurnMarkers = buildTurnMarkers;
exports.runtimeIsBusy = runtimeIsBusy;
exports.runtimeDisplayStatus = runtimeDisplayStatus;
exports.isTurnInFlight = isTurnInFlight;
exports.buildActivityItems = buildActivityItems;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
const lucide_react_1 = require("lucide-react");
const api_1 = require("./api");
const rich_text_1 = require("./rich-text");
const TraceInspectPage_1 = require("./features/traces/TraceInspectPage");
const StartupGuidePage_1 = require("./features/onboarding/StartupGuidePage");
const AttachmentPanel_1 = require("./features/attachments/AttachmentPanel");
const BotCenterPage_1 = require("./features/bots/BotCenterPage");
const SettingsCenter_1 = require("./features/settings/SettingsCenter");
const ActivityCard_1 = require("./features/activity/ActivityCard");
const ActivityDetailsPanel_1 = require("./features/activity/ActivityDetailsPanel");
const activity_normalizer_1 = require("./features/activity/activity-normalizer");
const codingTaskApi_1 = require("./lib/codingTaskApi");
const MAX_SESSION_EVENTS = 2000;
const SCROLL_BOTTOM_THRESHOLD = 96;
const ACTIONABLE_APPROVAL_STATES = new Set(["", "staged_not_granted", "grant_attached"]);
const STORAGE_THEME_KEY = "pp-echo-web-theme";
const STORAGE_ACTIVE_VIEW_KEY = "pp-echo-web-view";
const STORAGE_ACTIVE_SESSION_KEY = "pp-echo-web-session";
const navItems = [
    { view: "chat", label: "会话", icon: lucide_react_1.MessageSquare, description: "聊天与当前会话" },
    { view: "history", label: "历史", icon: lucide_react_1.Clock3, description: "会话历史与回看" },
    { view: "group", label: "群聊", icon: lucide_react_1.Users, description: "多会话协作" },
    { view: "search", label: "搜索", icon: lucide_react_1.Search, description: "会话检索" },
    { view: "workspace", label: "工作区", icon: lucide_react_1.FolderOpen, description: "工作区切换" },
    { view: "tasks", label: "任务", icon: lucide_react_1.LayoutDashboard, description: "审批与待办" },
    { view: "board", label: "看板", icon: lucide_react_1.Boxes, description: "运行概览" },
    { view: "channels", label: "频道", icon: lucide_react_1.Bot, description: "MCP 与通道" },
    { view: "plugins", label: "插件", icon: lucide_react_1.Sparkles, description: "能力扩展" },
    { view: "memory", label: "记忆", icon: lucide_react_1.BookOpen, description: "记忆视图" },
    { view: "model", label: "模型", icon: lucide_react_1.Monitor, description: "模型与环境" },
    { view: "logs", label: "日志", icon: lucide_react_1.FileText, description: "时间线与日志" },
    { view: "attachments", label: "附件", icon: lucide_react_1.Paperclip, description: "上传文件、检索、导入与记忆写入" },
    { view: "bots", label: "Bots", icon: lucide_react_1.Bot, description: "Bot Gateway and external message entry points" },
    { view: "traceInspect", label: "TraceInspect", icon: lucide_react_1.Activity, description: "Agent Trace 审计与回放" },
    { view: "usage", label: "用量", icon: lucide_react_1.Database, description: "运行统计" },
    { view: "skills", label: "技能", icon: lucide_react_1.ShieldCheck, description: "技能与规则" },
    { view: "users", label: "设置", icon: lucide_react_1.Settings, description: "系统设置" }
];
const shellNavGroups = [
    { title: "对话", views: ["chat", "history", "group", "search"] },
    { title: "执行", views: ["workspace", "tasks", "board", "channels"] },
    { title: "扩展", views: ["plugins", "memory", "model"] },
    { title: "监控", views: ["logs", "attachments", "bots", "traceInspect", "usage", "skills", "users"] }
];
const sidebarNavSections = [
    { title: "Conversations", views: ["chat", "history", "group", "search"] },
    { title: "Runtime", views: ["workspace", "tasks", "board", "channels"] },
    { title: "Extensions", views: ["plugins", "memory", "model", "skills"] },
    { title: "Observability", views: ["logs", "attachments", "traceInspect"] },
    { title: "Bots", views: ["bots"] },
    { title: "Usage", views: ["usage"] },
    { title: "Settings", views: ["users"] }
];
const comingSoonViews = new Set(["search", "group", "tasks"]);
const inspectorTabs = [
    { id: "status", label: "状态", icon: lucide_react_1.Activity },
    { id: "tools", label: "工具", icon: lucide_react_1.Code2 },
    { id: "approvals", label: "审批", icon: lucide_react_1.ShieldCheck }
];
function BrandLogo() {
    return ((0, jsx_runtime_1.jsx)("div", { className: "brand-mark", "aria-hidden": "true", children: (0, jsx_runtime_1.jsxs)("svg", { viewBox: "0 0 32 32", role: "img", children: [(0, jsx_runtime_1.jsxs)("g", { fill: "none", stroke: "currentColor", strokeWidth: "2.8", strokeLinecap: "round", strokeLinejoin: "round", children: [(0, jsx_runtime_1.jsx)("path", { d: "M23.8 7.8A11.4 11.4 0 1 0 24.6 23.5" }), (0, jsx_runtime_1.jsx)("path", { d: "M22 11.3A7.4 7.4 0 1 0 20.4 22.1" }), (0, jsx_runtime_1.jsx)("path", { d: "M20.4 16H24.1" }), (0, jsx_runtime_1.jsx)("circle", { cx: "26.3", cy: "16", r: "2.2" })] }), (0, jsx_runtime_1.jsx)("circle", { cx: "16", cy: "16", r: "3", fill: "currentColor" })] }) }));
}
function App() {
    const [theme, setTheme] = (0, react_1.useState)(() => readTheme());
    const [sidebarCollapsed, setSidebarCollapsed] = (0, react_1.useState)(false);
    const [openNavGroup, setOpenNavGroup] = (0, react_1.useState)("0");
    const [workspace, setWorkspace] = (0, react_1.useState)({ active: { name: "pp-Echo", path: "", exists: true, is_dir: true }, recent: [] });
    const [workspaceStatus, setWorkspaceStatus] = (0, react_1.useState)(null);
    const [sessions, setSessions] = (0, react_1.useState)([]);
    const [activeView, setActiveView] = (0, react_1.useState)(() => readStoredView());
    const [activeSessionId, setActiveSessionId] = (0, react_1.useState)(() => window.localStorage.getItem(STORAGE_ACTIVE_SESSION_KEY) || "");
    const [snapshots, setSnapshots] = (0, react_1.useState)({});
    const [events, setEvents] = (0, react_1.useState)({});
    const [prompt, setPrompt] = (0, react_1.useState)("");
    const [status, setStatus] = (0, react_1.useState)("Ready");
    const [approvalSummary, setApprovalSummary] = (0, react_1.useState)({ count: 0, items: [] });
    const [approvalAction, setApprovalAction] = (0, react_1.useState)(null);
    const [approvalFeedback, setApprovalFeedback] = (0, react_1.useState)("");
    const [workspaceDraft, setWorkspaceDraft] = (0, react_1.useState)("");
    const [pendingWorkspace, setPendingWorkspace] = (0, react_1.useState)(null);
    const [promptSubmitting, setPromptSubmitting] = (0, react_1.useState)(false);
    const [notice, setNotice] = (0, react_1.useState)(null);
    const [inspectorTab, setInspectorTab] = (0, react_1.useState)("status");
    const [inspectorOpen, setInspectorOpen] = (0, react_1.useState)(false);
    const [workspaceDialogOpen, setWorkspaceDialogOpen] = (0, react_1.useState)(false);
    const [settingsDialogOpen, setSettingsDialogOpen] = (0, react_1.useState)(false);
    const [settingsFocus, setSettingsFocus] = (0, react_1.useState)("general");
    const [searchQuery, setSearchQuery] = (0, react_1.useState)("");
    const [timeline, setTimeline] = (0, react_1.useState)([]);
    const [attachments, setAttachments] = (0, react_1.useState)({});
    const [attachmentUploading, setAttachmentUploading] = (0, react_1.useState)(false);
    const pollers = (0, react_1.useRef)({});
    const eventSockets = (0, react_1.useRef)({});
    const transcriptRef = (0, react_1.useRef)(null);
    const noticeTimer = (0, react_1.useRef)(null);
    (0, react_1.useEffect)(() => {
        document.documentElement.dataset.theme = theme;
        window.localStorage.setItem(STORAGE_THEME_KEY, theme);
    }, [theme]);
    (0, react_1.useEffect)(() => {
        refreshAll().catch(() => undefined);
        return () => {
            stopPolling();
            if (noticeTimer.current)
                window.clearTimeout(noticeTimer.current);
        };
    }, []);
    (0, react_1.useEffect)(() => {
        if (!activeView)
            return;
        window.localStorage.setItem(STORAGE_ACTIVE_VIEW_KEY, activeView);
    }, [activeView]);
    (0, react_1.useEffect)(() => {
        const groupIndex = sidebarNavSections.findIndex((group) => group.views.includes(activeView));
        if (groupIndex >= 0)
            setOpenNavGroup(String(groupIndex));
    }, [activeView]);
    (0, react_1.useEffect)(() => {
        if (!activeSessionId)
            return;
        window.localStorage.setItem(STORAGE_ACTIVE_SESSION_KEY, activeSessionId);
    }, [activeSessionId]);
    (0, react_1.useEffect)(() => {
        if (activeView !== "logs")
            return;
        refreshTimeline().catch(() => undefined);
    }, [activeView, activeSessionId]);
    (0, react_1.useEffect)(() => {
        const target = transcriptRef.current;
        if (target)
            target.scrollTop = target.scrollHeight;
    }, [activeSessionId, sessions.length, notice?.id]);
    const activeSnapshot = activeSessionId ? snapshots[activeSessionId] : undefined;
    const activeSession = activeSessionId ? sessions.find((session) => session.id === activeSessionId) : undefined;
    const activeEvents = activeSessionId ? events[activeSessionId] || [] : [];
    const transcript = (0, react_1.useMemo)(() => buildTranscript(activeSnapshot, activeEvents), [activeSnapshot, activeEvents]);
    const activityItems = (0, react_1.useMemo)(() => buildActivityItems(activeEvents, activeSnapshot, approvalSummary), [activeEvents, activeSnapshot, approvalSummary]);
    const activeApproval = (0, react_1.useMemo)(() => buildActiveApproval(activeSnapshot, activeEvents, approvalSummary), [activeSnapshot, activeEvents, approvalSummary]);
    const busy = runtimeIsBusy(activeSnapshot, activeEvents);
    const displayStatus = runtimeDisplayStatus(status, activeSnapshot, activeEvents);
    const filteredSessions = (0, react_1.useMemo)(() => filterSessions(sessions, searchQuery), [sessions, searchQuery]);
    const sessionStats = (0, react_1.useMemo)(() => computeSessionStats(sessions), [sessions]);
    const viewLabel = navItems.find((item) => item.view === activeView)?.label || "会话";
    const viewMeta = navItems.find((item) => item.view === activeView);
    const middleMode = activeView === "history" ? "sessions" : activeView === "board" ? "observer" : null;
    async function refreshAll() {
        const [workspaceState, workspaceMeta, sessionList, approvals] = await Promise.all([api_1.api.workspaces(), api_1.api.workspaceStatus(), api_1.api.sessions(), api_1.api.approvals()]);
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
        }
        else if (activeSessionId && !sessionList.sessions.some((session) => session.id === activeSessionId)) {
            setActiveSessionId(nextSessionId);
        }
    }
    async function refreshTimeline() {
        const payload = await api_1.api.timeline(activeSessionId || undefined, 120);
        setTimeline(payload.timeline);
    }
    async function openSession(sessionId) {
        setActiveView("chat");
        await hydrateSession(sessionId);
        setNotice(null);
    }
    async function hydrateSession(sessionId) {
        let snapshot;
        try {
            snapshot = await api_1.api.snapshot(sessionId);
        }
        catch (error) {
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
        const created = await api_1.api.createSession();
        await refreshAll();
        await openSession(created.session_id);
    }
    function ensureEventPolling(sessionId) {
        if (eventSockets.current[sessionId] || pollers.current[sessionId])
            return;
        if (connectEventSocket(sessionId))
            return;
        startEventPolling(sessionId);
    }
    function connectEventSocket(sessionId) {
        if (!("WebSocket" in window))
            return false;
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
                    const event = JSON.parse(message.data);
                    appendEvent(sessionId, event);
                    if (event.type === "turn_end" || event.type === "agent_end" || event.type === "error" || event.type.includes("gate")) {
                        refreshSessionState(sessionId).catch(() => undefined);
                    }
                }
                catch {
                    // Ignore malformed websocket payloads and let the next event/snapshot recover the UI.
                }
            };
            socket.onerror = () => {
                socket.close();
            };
            socket.onclose = () => {
                if (eventSockets.current[sessionId] === socket)
                    delete eventSockets.current[sessionId];
                if (!pollers.current[sessionId])
                    startEventPolling(sessionId);
            };
            return true;
        }
        catch {
            return false;
        }
    }
    function startEventPolling(sessionId) {
        if (pollers.current[sessionId])
            return;
        const poll = async () => {
            try {
                const payload = await api_1.api.events(sessionId);
                payload.events.forEach((event) => appendEvent(sessionId, event));
                const refreshed = await refreshSessionState(sessionId);
                if (!refreshed)
                    stopSessionPolling(sessionId);
            }
            catch (error) {
                stopSessionPolling(sessionId);
                setStatus(`Stopped polling ${shortId(sessionId)}: ${error instanceof Error ? error.message : String(error)}`);
            }
        };
        poll();
        pollers.current[sessionId] = window.setInterval(poll, 700);
    }
    function appendEvent(sessionId, event) {
        setEvents((current) => {
            const existing = current[sessionId] || [];
            const key = runtimeEventDedupeKey(event);
            if (key && existing.some((item) => runtimeEventDedupeKey(item) === key))
                return current;
            return { ...current, [sessionId]: [...existing, event].slice(-MAX_SESSION_EVENTS) };
        });
        setStatus(event.message || event.type);
    }
    async function refreshSessionState(sessionId) {
        try {
            const snapshot = await api_1.api.snapshot(sessionId);
            setSnapshots((current) => ({ ...current, [sessionId]: snapshot }));
        }
        catch (error) {
            setStatus(`Session ${shortId(sessionId)} refresh failed: ${error instanceof Error ? error.message : String(error)}`);
            return false;
        }
        api_1.api.sessions().then((payload) => setSessions(sortSessionsByUpdatedAt(payload.sessions))).catch(() => undefined);
        refreshApprovals();
        return true;
    }
    function refreshApprovals() {
        return api_1.api.approvals().then(setApprovalSummary).catch(() => undefined);
    }
    async function refreshAttachments(sessionId) {
        if (!sessionId)
            return;
        try {
            const payload = await api_1.api.listAttachments(sessionId);
            setAttachments((current) => ({ ...current, [sessionId]: payload.attachments }));
        }
        catch {
            setAttachments((current) => ({ ...current, [sessionId]: current[sessionId] || [] }));
        }
    }
    async function uploadAttachment(file) {
        if (!activeSessionId || attachmentUploading)
            return;
        setAttachmentUploading(true);
        try {
            await api_1.api.uploadAttachment(activeSessionId, file);
            await refreshAttachments(activeSessionId);
            showNotice("Attachment uploaded", "success");
        }
        catch (error) {
            showNotice(error instanceof Error ? error.message : String(error), "warning");
        }
        finally {
            setAttachmentUploading(false);
        }
    }
    async function deleteAttachment(attachmentId) {
        if (!activeSessionId)
            return;
        try {
            await api_1.api.deleteAttachment(activeSessionId, attachmentId);
            await refreshAttachments(activeSessionId);
            showNotice("Attachment deleted", "success");
        }
        catch (error) {
            showNotice(error instanceof Error ? error.message : String(error), "warning");
        }
    }
    function openView(view) {
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
                if (firstSession)
                    hydrateSession(firstSession).catch(() => undefined);
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
            if (activeSessionId)
                return;
            const firstSession = sessions[0]?.id;
            if (firstSession) {
                openSession(firstSession).catch(() => undefined);
                return;
            }
            showNotice("还没有会话，先新建一个吧", "info");
            return;
        }
        const item = navItems.find((entry) => entry.view === view);
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
    function stopSessionPolling(sessionId) {
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
    function stopPollingExcept(sessionId) {
        Object.entries(pollers.current).forEach(([key, poller]) => {
            if (key === sessionId)
                return;
            window.clearInterval(poller);
            delete pollers.current[key];
        });
        Object.entries(eventSockets.current).forEach(([key, socket]) => {
            if (key === sessionId)
                return;
            delete eventSockets.current[key];
            socket.close();
        });
    }
    async function reloadWorkspaceAfterSwitch(workspaceState) {
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
        const [workspaceMeta, sessionList, approvals] = await Promise.all([api_1.api.workspaceStatus(), api_1.api.sessions(), api_1.api.approvals()]);
        setWorkspaceStatus(workspaceMeta);
        const sorted = sortSessionsByUpdatedAt(sessionList.sessions);
        setSessions(sorted);
        setApprovalSummary(approvals);
        if (sorted[0]) {
            await hydrateSession(sorted[0].id);
        }
    }
    async function openWorkspace(path, confirmed = false) {
        const target = path.trim();
        if (!target) {
            showNotice("请输入工作区路径", "warning");
            return;
        }
        try {
            const response = await api_1.api.openWorkspace(target, confirmed);
            if (response.requires_confirmation) {
                setPendingWorkspace(response);
                return;
            }
            setPendingWorkspace(null);
            setWorkspaceDraft("");
            setWorkspaceDialogOpen(false);
            await reloadWorkspaceAfterSwitch(response);
            showNotice("工作区已切换", "success");
        }
        catch (error) {
            showNotice(workspaceErrorMessage(error, target), "warning");
        }
    }
    async function sendPrompt() {
        if (!activeSessionId || !prompt.trim() || promptSubmitting || busy || activeApproval)
            return;
        const text = prompt;
        setPromptSubmitting(true);
        setPrompt("");
        appendEvent(activeSessionId, { type: "local_user_prompt", session_id: activeSessionId, message: text, timestamp: Date.now() / 1000 });
        try {
            await api_1.api.prompt(activeSessionId, text);
            ensureEventPolling(activeSessionId);
            await refreshSessionState(activeSessionId);
        }
        catch (error) {
            setPrompt(text);
            showNotice(error instanceof Error ? error.message : String(error), "warning");
        }
        finally {
            setPromptSubmitting(false);
        }
    }
    async function cancelActiveSession() {
        if (!activeSessionId || !busy)
            return;
        appendEvent(activeSessionId, {
            type: "cancel_requested",
            session_id: activeSessionId,
            message: "Cancel requested for the running turn.",
            timestamp: Date.now() / 1000,
            details: { cancel_requested: true }
        });
        await api_1.api.cancel(activeSessionId);
        ensureEventPolling(activeSessionId);
        refreshSessionState(activeSessionId);
        showNotice("已请求停止当前会话", "info");
    }
    async function approve() {
        if (!activeApproval)
            return;
        const approval = activeApproval;
        let approvalTargetSessionId = activeSessionId;
        setApprovalAction({ token: approval.token, action: "approve" });
        setApprovalFeedback("");
        try {
            if (approval.kind === "planner" && activeSessionId) {
                await api_1.api.approve(activeSessionId);
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
            }
            else {
                const result = await api_1.api.approvePending(approval.token);
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
                            await api_1.api.continueSession(activeSessionId);
                            ensureEventPolling(activeSessionId);
                        }
                        catch (continueError) {
                            const continueMessage = continueError instanceof Error ? continueError.message : String(continueError);
                            setStatus(`Approved, but continue failed: ${continueMessage}`);
                            showNotice(`审批已执行，但自动继续失败：${continueMessage}`, "warning");
                        }
                    }
                }
                if (result.resumed === false && result.session_id) {
                    await api_1.api.continueSession(result.session_id);
                    ensureEventPolling(result.session_id);
                }
            }
            await refreshApprovals();
            if (approvalTargetSessionId)
                await refreshSessionState(approvalTargetSessionId);
            if (activeSessionId && activeSessionId !== approvalTargetSessionId)
                await refreshSessionState(activeSessionId);
            showNotice("审批已通过", "success");
        }
        catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            setApprovalFeedback(message);
            setStatus(message);
            showNotice(message, "warning");
        }
        finally {
            setApprovalAction(null);
        }
    }
    async function reject() {
        if (!activeApproval)
            return;
        const approval = activeApproval;
        setApprovalAction({ token: approval.token, action: "reject" });
        setApprovalFeedback("");
        try {
            if (approval.kind === "planner" && activeSessionId) {
                await api_1.api.reject(activeSessionId);
                clearPlannerToken(activeSessionId);
                ensureEventPolling(activeSessionId);
            }
            else {
                await api_1.api.rejectPending(approval.token);
                removeApproval(approval.token);
            }
            setApprovalFeedback("Approval rejected.");
            setStatus("Approval rejected");
            await refreshApprovals();
            if (activeSessionId)
                await refreshSessionState(activeSessionId);
            showNotice("审批已拒绝", "info");
        }
        catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            setApprovalFeedback(message);
            setStatus(message);
            showNotice(message, "warning");
        }
        finally {
            setApprovalAction(null);
        }
    }
    function clearPlannerToken(sessionId) {
        setSnapshots((current) => {
            const snapshot = current[sessionId];
            return snapshot ? { ...current, [sessionId]: { ...snapshot, pending_plan_token: null } } : current;
        });
    }
    function removeApproval(token) {
        setApprovalSummary((current) => ({
            ...current,
            count: Math.max(0, current.count - 1),
            items: current.items.filter((item) => item.token !== token)
        }));
    }
    function showNotice(message, tone = "info") {
        setNotice({ id: `notice-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, message, tone });
        if (noticeTimer.current)
            window.clearTimeout(noticeTimer.current);
        noticeTimer.current = window.setTimeout(() => setNotice(null), 2200);
    }
    function handleComingSoon(label) {
        showNotice(`${label} 功能开发中，敬请期待`, "info");
    }
    return ((0, jsx_runtime_1.jsxs)("div", { className: `app-shell theme-${theme} ${middleMode ? `mode-${middleMode}` : "mode-chat"} ${sidebarCollapsed ? "sidebar-collapsed" : ""}`, children: [(0, jsx_runtime_1.jsxs)("aside", { className: "app-nav", children: [(0, jsx_runtime_1.jsxs)("div", { className: "app-brand", children: [(0, jsx_runtime_1.jsxs)("button", { className: "brand-button", onClick: () => openView("startupGuide"), title: "\u542F\u52A8\u6307\u5F15", children: [(0, jsx_runtime_1.jsx)(BrandLogo, {}), (0, jsx_runtime_1.jsxs)("div", { className: "brand-copy", children: [(0, jsx_runtime_1.jsx)("strong", { children: "pp-Echo" }), (0, jsx_runtime_1.jsx)("span", { children: workspace.active.path || "本地工作区" })] })] }), (0, jsx_runtime_1.jsx)("button", { className: "icon-button", onClick: () => setTheme(theme === "dark" ? "light" : "dark"), title: "\u5207\u6362\u4E3B\u9898", children: (0, jsx_runtime_1.jsx)(lucide_react_1.Sun, { size: 15 }) }), (0, jsx_runtime_1.jsx)("button", { className: "icon-button", onClick: () => setSidebarCollapsed((current) => !current), title: sidebarCollapsed ? "Open sidebar" : "Close sidebar", children: sidebarCollapsed ? (0, jsx_runtime_1.jsx)(lucide_react_1.PanelLeftOpen, { size: 15 }) : (0, jsx_runtime_1.jsx)(lucide_react_1.PanelLeftClose, { size: 15 }) })] }), (0, jsx_runtime_1.jsx)("nav", { className: "nav-groups", children: sidebarNavSections.map((group, index) => {
                            const groupKey = String(index);
                            const isOpen = openNavGroup === groupKey;
                            const firstItem = navItems.find((entry) => entry.view === group.views[0]);
                            const GroupIcon = firstItem.icon;
                            const groupActive = group.views.includes(activeView);
                            const isSingleItem = group.views.length === 1;
                            return ((0, jsx_runtime_1.jsxs)("section", { className: groupActive ? "nav-group active" : "nav-group", children: [(0, jsx_runtime_1.jsxs)("button", { className: isOpen || groupActive ? "nav-parent open" : "nav-parent", type: "button", onClick: () => {
                                            if (isSingleItem) {
                                                openView(group.views[0]);
                                                return;
                                            }
                                            setOpenNavGroup(isOpen ? "" : groupKey);
                                        }, children: [(0, jsx_runtime_1.jsx)(GroupIcon, { size: 16 }), (0, jsx_runtime_1.jsx)("span", { children: group.title }), isSingleItem ? (0, jsx_runtime_1.jsx)(lucide_react_1.ChevronRight, { size: 14 }) : isOpen ? (0, jsx_runtime_1.jsx)(lucide_react_1.ChevronDown, { size: 14 }) : (0, jsx_runtime_1.jsx)(lucide_react_1.ChevronRight, { size: 14 })] }), isOpen && !isSingleItem && !sidebarCollapsed ? (0, jsx_runtime_1.jsx)("div", { className: "nav-group-items", children: group.views.map((view) => {
                                            const item = navItems.find((entry) => entry.view === view);
                                            const Icon = item.icon;
                                            return ((0, jsx_runtime_1.jsxs)("button", { className: activeView === item.view ? "nav-entry active" : "nav-entry", title: item.description, onClick: () => openView(item.view), children: [(0, jsx_runtime_1.jsx)(Icon, { size: 16 }), (0, jsx_runtime_1.jsx)("span", { children: item.label }), (0, jsx_runtime_1.jsx)(lucide_react_1.ChevronRight, { size: 13 })] }, item.view));
                                        }) }) : null] }, group.title));
                        }) }), (0, jsx_runtime_1.jsxs)("div", { className: "app-nav-footer", children: [(0, jsx_runtime_1.jsxs)("button", { className: "team-switcher-card", onClick: () => openView("workspace"), type: "button", children: [(0, jsx_runtime_1.jsx)("div", { className: "team-icon", children: (0, jsx_runtime_1.jsx)(lucide_react_1.FolderOpen, { size: 15 }) }), (0, jsx_runtime_1.jsxs)("div", { className: "team-copy", children: [(0, jsx_runtime_1.jsx)("strong", { children: workspaceStatus?.name || workspace.active.name || "pp-Echo" }), (0, jsx_runtime_1.jsx)("span", { children: workspaceStatus?.git_branch || "workspace" })] }), (0, jsx_runtime_1.jsx)(lucide_react_1.ChevronsUpDown, { size: 14 })] }), (0, jsx_runtime_1.jsxs)("button", { className: "footer-line", onClick: refreshAll, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.RefreshCw, { size: 15 }), (0, jsx_runtime_1.jsx)("span", { children: "\u5237\u65B0" })] }), (0, jsx_runtime_1.jsxs)("button", { className: "footer-line", onClick: createSession, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Plus, { size: 15 }), (0, jsx_runtime_1.jsx)("span", { children: "\u65B0\u4F1A\u8BDD" })] }), (0, jsx_runtime_1.jsxs)("div", { className: "footer-meta", children: [(0, jsx_runtime_1.jsxs)("span", { children: [sessionStats.total, " \u4F1A\u8BDD"] }), (0, jsx_runtime_1.jsxs)("span", { children: [sessionStats.active, " \u6D3B\u8DC3"] })] })] })] }), (0, jsx_runtime_1.jsxs)("section", { className: "session-rail", children: [(0, jsx_runtime_1.jsxs)("div", { className: "session-rail-head", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("small", { children: "SESSIONS" }), (0, jsx_runtime_1.jsx)("h2", { children: "\u4F1A\u8BDD\u5217\u8868" })] }), (0, jsx_runtime_1.jsx)("button", { className: "icon-button", onClick: () => openView("search"), title: "\u641C\u7D22", children: (0, jsx_runtime_1.jsx)(lucide_react_1.Search, { size: 16 }) })] }), (0, jsx_runtime_1.jsxs)("div", { className: "session-rail-toolbar", children: [(0, jsx_runtime_1.jsxs)("button", { className: "session-toolbar-btn", onClick: createSession, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Plus, { size: 14 }), (0, jsx_runtime_1.jsx)("span", { children: "\u65B0\u5EFA" })] }), (0, jsx_runtime_1.jsxs)("button", { className: "session-toolbar-btn", onClick: refreshAll, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.RefreshCw, { size: 14 }), (0, jsx_runtime_1.jsx)("span", { children: "\u5237\u65B0" })] })] }), (0, jsx_runtime_1.jsxs)("label", { className: "session-search", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Search, { size: 15 }), (0, jsx_runtime_1.jsx)("input", { value: searchQuery, onChange: (event) => setSearchQuery(event.target.value), placeholder: "\u641C\u7D22\u4F1A\u8BDD" })] }), (0, jsx_runtime_1.jsxs)("div", { className: "session-meta", children: [(0, jsx_runtime_1.jsxs)("span", { children: [sessionStats.total, " \u4F1A\u8BDD"] }), (0, jsx_runtime_1.jsxs)("span", { children: [sessionStats.active, " \u6D3B\u8DC3"] })] }), (0, jsx_runtime_1.jsx)("div", { className: "session-stack", children: filteredSessions.slice(0, 14).map((session) => ((0, jsx_runtime_1.jsxs)("button", { className: activeSessionId === session.id ? "session-row active" : "session-row", onClick: () => hydrateSession(session.id), children: [(0, jsx_runtime_1.jsx)(lucide_react_1.MessageSquare, { size: 15 }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("strong", { children: session.last_user_preview || session.summary_preview || shortId(session.id) }), (0, jsx_runtime_1.jsxs)("span", { children: [session.turn_count, " turns \u00B7 ", session.model] })] }), session.pending_plan_token ? (0, jsx_runtime_1.jsx)("em", { children: "\u5BA1\u6279\u4E2D" }) : null] }, session.id))) })] }), (0, jsx_runtime_1.jsxs)("main", { className: "content-canvas", children: [activeView === "chat" || activeView === "history" || activeView === "board" ? null : ((0, jsx_runtime_1.jsxs)("header", { className: "canvas-header", children: [(0, jsx_runtime_1.jsxs)("div", { className: "canvas-header-copy", children: [(0, jsx_runtime_1.jsxs)("div", { className: "canvas-crumbs", children: [(0, jsx_runtime_1.jsxs)("span", { children: ["PP-ECHO / ", viewLabel.toUpperCase()] }), (0, jsx_runtime_1.jsx)("span", { children: activeSessionId ? shortId(activeSessionId) : "session" })] }), (0, jsx_runtime_1.jsx)("h1", { children: viewLabel }), (0, jsx_runtime_1.jsx)("p", { children: viewMeta?.description || workspace.active.path || "功能开发中，敬请期待" })] }), (0, jsx_runtime_1.jsxs)("div", { className: "canvas-actions", children: [(0, jsx_runtime_1.jsx)("button", { className: "icon-button", onClick: refreshAll, title: "\u5237\u65B0", children: (0, jsx_runtime_1.jsx)(lucide_react_1.RefreshCw, { size: 16 }) }), (0, jsx_runtime_1.jsx)("button", { className: "icon-button", onClick: createSession, title: "\u65B0\u4F1A\u8BDD", children: (0, jsx_runtime_1.jsx)(lucide_react_1.Plus, { size: 16 }) }), (0, jsx_runtime_1.jsx)("button", { className: "icon-button", onClick: cancelActiveSession, disabled: !activeSessionId || !busy, title: "\u505C\u6B62", children: (0, jsx_runtime_1.jsx)(lucide_react_1.Square, { size: 15 }) }), (0, jsx_runtime_1.jsx)("button", { className: inspectorOpen ? "icon-button active" : "icon-button", onClick: () => setInspectorOpen((current) => !current), title: "\u89C2\u5BDF\u7A97", children: (0, jsx_runtime_1.jsx)(lucide_react_1.Activity, { size: 16 }) })] })] })), (0, jsx_runtime_1.jsx)("div", { className: `canvas-body canvas-body-${activeView}`, children: activeView === "startupGuide" ? ((0, jsx_runtime_1.jsx)(StartupGuidePage_1.StartupGuidePage, { onBack: () => setActiveView("chat"), onOpenTrace: () => setActiveView("traceInspect"), onOpenChat: () => setActiveView("chat") })) : activeView === "chat" || activeView === "history" || activeView === "board" ? ((0, jsx_runtime_1.jsx)(ChatWorkspace, { transcriptRef: transcriptRef, transcript: transcript, activeSnapshot: activeSnapshot, workspace: workspace, workspaceStatus: workspaceStatus, activeModel: activeSession?.model || "", activeSessionId: activeSessionId, displayStatus: displayStatus, busy: busy, prompt: prompt, promptSubmitting: promptSubmitting, activeApproval: activeApproval, setPrompt: setPrompt, sendPrompt: sendPrompt, cancelActiveSession: cancelActiveSession, activityItems: activityItems, approvalSummary: approvalSummary, approvalAction: approvalAction, approvalFeedback: approvalFeedback, attachments: activeSessionId ? attachments[activeSessionId] || [] : [], attachmentUploading: attachmentUploading, approve: approve, reject: reject, refreshAttachments: () => activeSessionId ? refreshAttachments(activeSessionId) : undefined, uploadAttachment: uploadAttachment, deleteAttachment: deleteAttachment, openAttachments: () => setActiveView("attachments"), inspectorTab: inspectorTab, setInspectorTab: setInspectorTab, activeEvents: activeEvents, notice: notice, inspectorOpen: inspectorOpen, setInspectorOpen: setInspectorOpen, onWorkspaceChanged: () => refreshAll().catch(() => undefined), onModelChanged: () => {
                                refreshAll().catch(() => undefined);
                                if (activeSessionId)
                                    refreshSessionState(activeSessionId).catch(() => undefined);
                            } })) : activeView === "traceInspect" ? ((0, jsx_runtime_1.jsx)(TraceInspectPage_1.TraceInspectPage, { activeSessionId: activeSessionId, onBack: () => setActiveView("chat") })) : activeView === "attachments" ? ((0, jsx_runtime_1.jsx)(AttachmentWorkbench, { activeSessionId: activeSessionId, attachments: activeSessionId ? attachments[activeSessionId] || [] : [], uploading: attachmentUploading, onRefresh: () => activeSessionId ? refreshAttachments(activeSessionId) : undefined, onDelete: deleteAttachment, onUpload: uploadAttachment })) : activeView === "bots" ? ((0, jsx_runtime_1.jsx)(BotCenterPage_1.BotCenterPage, {})) : activeView === "logs" ? ((0, jsx_runtime_1.jsx)(ObservabilityPanel, { activeSessionId: activeSessionId, timeline: timeline, activeEvents: activeEvents, onReload: refreshTimeline })) : activeView === "skills" || activeView === "plugins" || activeView === "channels" ? ((0, jsx_runtime_1.jsx)(CapabilityWorkbench, { initialTab: activeView === "skills" ? "skills" : activeView === "plugins" ? "plugins" : "mcp", workspaceStatus: workspaceStatus, activeSessionId: activeSessionId })) : activeView === "memory" ? ((0, jsx_runtime_1.jsx)(MemoryWorkbench, {})) : activeView === "usage" ? ((0, jsx_runtime_1.jsx)(UsagePanel, {})) : activeView === "users" ? ((0, jsx_runtime_1.jsx)(SettingsCenter_1.SettingsCenter, { sessionId: activeSessionId, initialCategory: settingsFocus, onOpenCapabilities: () => setActiveView("channels"), onSaved: () => {
                                refreshAll().catch(() => undefined);
                                if (activeSessionId)
                                    refreshSessionState(activeSessionId).catch(() => undefined);
                            } })) : ((0, jsx_runtime_1.jsx)(ComingSoonPanel, { title: viewLabel, onComingSoon: handleComingSoon, onReload: refreshAll })) })] }), (0, jsx_runtime_1.jsxs)("div", { className: inspectorOpen ? "inspector-drawer open" : "inspector-drawer", children: [(0, jsx_runtime_1.jsxs)("div", { className: "inspector-drawer-head", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("small", { children: "INSPECTOR" }), (0, jsx_runtime_1.jsx)("h2", { children: "\u72B6\u6001 / \u5DE5\u5177 / \u5BA1\u6279" })] }), (0, jsx_runtime_1.jsx)("button", { className: "icon-button", onClick: () => setInspectorOpen(false), title: "\u6536\u8D77", children: (0, jsx_runtime_1.jsx)(lucide_react_1.X, { size: 16 }) })] }), (0, jsx_runtime_1.jsx)("div", { className: "inspector-tabs", children: inspectorTabs.map((tab) => ((0, jsx_runtime_1.jsxs)("button", { className: inspectorTab === tab.id ? "inspector-tab active" : "inspector-tab", onClick: () => setInspectorTab(tab.id), children: [(0, jsx_runtime_1.jsx)(tab.icon, { size: 15 }), (0, jsx_runtime_1.jsx)("span", { children: tab.label })] }, tab.id))) }), (0, jsx_runtime_1.jsxs)("div", { className: "inspector-panel", children: [inspectorTab === "status" && ((0, jsx_runtime_1.jsx)(InspectorCard, { title: "\u8FD0\u884C\u72B6\u6001", icon: lucide_react_1.Activity, children: (0, jsx_runtime_1.jsx)(StatGrid, { items: [
                                        ["Status", displayStatus],
                                        ["Session", shortId(activeSessionId)],
                                        ["Phase", activeSnapshot?.runtime_control?.status || activeSnapshot?.turn?.phase || "idle"],
                                        ["Queue", String(activeSnapshot?.queued_message_count || 0)],
                                        ["Artifacts", String(activeSnapshot?.runtime_control?.pending_artifact_count || 0)],
                                        ["Mode", activeSnapshot?.cancel_requested ? "Canceling" : busy ? "Working" : "Idle"]
                                    ] }) })), inspectorTab === "tools" && ((0, jsx_runtime_1.jsx)(ActivityDetailsPanel_1.ActivityDetailsPanel, { items: activityItems })), inspectorTab === "approvals" && ((0, jsx_runtime_1.jsx)(InspectorCard, { title: "\u5BA1\u6279\u6D41", icon: lucide_react_1.ShieldCheck, children: activeApproval ? ((0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsx)("p", { className: "approval-kind", children: activeApproval.title }), (0, jsx_runtime_1.jsx)("p", { className: "muted", children: activeApproval.description }), activeApproval.meta && (0, jsx_runtime_1.jsx)("small", { className: "approval-meta", children: activeApproval.meta }), (0, jsx_runtime_1.jsx)("code", { children: String(activeApproval.token).slice(0, 18) }), (0, jsx_runtime_1.jsxs)("div", { className: "split-actions", children: [(0, jsx_runtime_1.jsxs)("button", { disabled: Boolean(approvalAction), onClick: approve, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Check, { size: 15 }), " ", approvalAction?.token === activeApproval.token && approvalAction.action === "approve" ? "处理中..." : activeApproval.approveLabel] }), (0, jsx_runtime_1.jsxs)("button", { disabled: Boolean(approvalAction), onClick: reject, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.X, { size: 15 }), " ", approvalAction?.token === activeApproval.token && approvalAction.action === "reject" ? "处理中..." : "拒绝"] })] })] })) : ((0, jsx_runtime_1.jsx)("p", { className: "muted", children: approvalFeedback || approvalEmptyText(busy, approvalSummary.active_count ?? approvalSummary.count) })) })), (0, jsx_runtime_1.jsx)(InspectorCard, { title: "\u6982\u89C8", icon: lucide_react_1.Monitor, children: (0, jsx_runtime_1.jsxs)("dl", { className: "compact-meta", children: [(0, jsx_runtime_1.jsx)("dt", { children: "\u6D88\u606F" }), (0, jsx_runtime_1.jsx)("dd", { children: activeSnapshot?.messages?.length || 0 }), (0, jsx_runtime_1.jsx)("dt", { children: "\u4E8B\u4EF6" }), (0, jsx_runtime_1.jsx)("dd", { children: activeEvents.length }), (0, jsx_runtime_1.jsx)("dt", { children: "\u5BA1\u6279" }), (0, jsx_runtime_1.jsx)("dd", { children: approvalSummary.active_count ?? approvalSummary.count }), (0, jsx_runtime_1.jsx)("dt", { children: "\u72B6\u6001" }), (0, jsx_runtime_1.jsx)("dd", { children: displayStatus })] }) })] })] }), workspaceDialogOpen ? ((0, jsx_runtime_1.jsx)(WorkspaceDialog, { currentPath: workspace.active.path || "", value: workspaceDraft, pendingWorkspace: pendingWorkspace, onChange: (value) => {
                    setWorkspaceDraft(value);
                    setPendingWorkspace(null);
                }, onClose: () => {
                    setWorkspaceDialogOpen(false);
                    setPendingWorkspace(null);
                }, onOpen: () => openWorkspace(workspaceDraft), onOpenPath: (path) => openWorkspace(path), onConfirm: () => pendingWorkspace?.candidate?.path ? openWorkspace(pendingWorkspace.candidate.path, true) : undefined })) : null, settingsDialogOpen ? ((0, jsx_runtime_1.jsx)(DynamicSettingsDialog, { sessionId: activeSessionId, initialCategory: settingsFocus, onClose: () => setSettingsDialogOpen(false), onSaved: () => {
                    refreshAll().catch(() => undefined);
                    if (activeSessionId)
                        refreshSessionState(activeSessionId).catch(() => undefined);
                } })) : null, notice ? ((0, jsx_runtime_1.jsx)("div", { className: `toast toast-${notice.tone}`, children: (0, jsx_runtime_1.jsx)("span", { children: notice.message }) })) : null] }));
}
const settingsCategoryLabels = {
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
function DynamicSettingsDialog({ sessionId, initialCategory, onClose, onSaved }) {
    const [snapshot, setSnapshot] = (0, react_1.useState)(null);
    const [category, setCategory] = (0, react_1.useState)(initialCategory);
    const [scope, setScope] = (0, react_1.useState)(sessionId ? "session" : "project");
    const [profileDraft, setProfileDraft] = (0, react_1.useState)("");
    const [drafts, setDrafts] = (0, react_1.useState)({});
    const [saving, setSaving] = (0, react_1.useState)(false);
    const [error, setError] = (0, react_1.useState)("");
    const [fieldErrors, setFieldErrors] = (0, react_1.useState)({});
    const [advancedOpen, setAdvancedOpen] = (0, react_1.useState)(false);
    const [jsonDraft, setJsonDraft] = (0, react_1.useState)("");
    const [notice, setNotice] = (0, react_1.useState)("");
    const [providerPresets, setProviderPresets] = (0, react_1.useState)([]);
    (0, react_1.useEffect)(() => {
        setCategory(initialCategory);
    }, [initialCategory]);
    (0, react_1.useEffect)(() => {
        loadConfig().catch((err) => applyConfigError(err, setError, setFieldErrors));
    }, [sessionId]);
    (0, react_1.useEffect)(() => {
        if (!snapshot)
            return;
        setJsonDraft(JSON.stringify(readScopeConfig(snapshot, scope, profileDraft), null, 2));
    }, [scope, profileDraft, snapshot]);
    async function loadConfig() {
        const [payload, providersPayload] = await Promise.all([
            api_1.api.config(sessionId || undefined),
            api_1.api.modelProviders()
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
        if (!snapshot)
            return;
        const dirtyFields = fields.filter((field) => isFieldDirty(snapshot, drafts, field, scope, profileDraft));
        if (!dirtyFields.length)
            return;
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
                    updated = await api_1.api.sessionConfigSet(sessionId, field.path, value);
                }
                else if (scope === "profile") {
                    updated = await api_1.api.configProfileSet(profileName, field.path, value, baseHash, sessionId || undefined);
                }
                else {
                    updated = await api_1.api.configSet(field.path, value, baseHash);
                }
                baseHash = updated.config_hash;
            }
            setSnapshot(updated);
            setDrafts(buildConfigDrafts(updated));
            setProfileDraft(updated.active_profile || profileName || updated.profiles[0] || "default");
            setNotice(scope === "session" ? "Session override saved; takes effect on the next turn." : "Configuration saved.");
            onSaved();
        }
        catch (err) {
            applyConfigError(err, setError, setFieldErrors);
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
        setFieldErrors({});
        try {
            const parsed = JSON.parse(jsonDraft || "{}");
            if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
                throw new Error("JSON must be an object.");
            const updated = await api_1.api.configPatch(parsed, snapshot.config_hash);
            setSnapshot(updated);
            setDrafts(buildConfigDrafts(updated));
            setNotice("JSON patch saved.");
            onSaved();
        }
        catch (err) {
            applyConfigError(err, setError, setFieldErrors);
        }
        finally {
            setSaving(false);
        }
    }
    async function switchProfile(value) {
        if (!snapshot)
            return;
        setSaving(true);
        setError("");
        setFieldErrors({});
        try {
            const nextProfile = value || null;
            const updated = scope === "session" && sessionId
                ? await api_1.api.setSessionProfile(sessionId, nextProfile)
                : await api_1.api.setProjectProfile(nextProfile, snapshot.config_hash, sessionId || undefined);
            setSnapshot(updated);
            setProfileDraft(updated.active_profile || "");
            setDrafts(buildConfigDrafts(updated));
            setNotice(nextProfile ? `Profile switched to ${nextProfile}.` : "Profile cleared.");
            onSaved();
        }
        catch (err) {
            applyConfigError(err, setError, setFieldErrors);
        }
        finally {
            setSaving(false);
        }
    }
    function revertDrafts() {
        if (!snapshot)
            return;
        setDrafts(buildConfigDrafts(snapshot));
        setJsonDraft(JSON.stringify(readScopeConfig(snapshot, scope, profileDraft), null, 2));
        setError("");
        setFieldErrors({});
    }
    function updateFieldDraft(field, value) {
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
    async function saveField(field) {
        if (!snapshot)
            return;
        setSaving(true);
        setError("");
        try {
            const value = parseFieldDraft(drafts[field.path], field.type);
            const updated = field.path === "model.model" && sessionId
                ? await api_1.api.setSessionModel(sessionId, String(value))
                : await api_1.api.configSet(field.path, value, snapshot.config_hash);
            setSnapshot(updated);
            setDrafts(buildConfigDrafts(updated));
            onSaved();
        }
        catch (err) {
            applyConfigError(err, setError, setFieldErrors);
        }
        finally {
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
    return ((0, jsx_runtime_1.jsx)("div", { className: "settings-dialog-backdrop", children: (0, jsx_runtime_1.jsxs)("section", { className: "settings-dialog settings-workbench", children: [(0, jsx_runtime_1.jsxs)("header", { className: "settings-dialog-head", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("small", { children: "CONFIG" }), (0, jsx_runtime_1.jsx)("h2", { children: "Dynamic settings" }), (0, jsx_runtime_1.jsx)("p", { children: snapshot ? `effective ${snapshot.effective_hash.slice(0, 12)} · project ${snapshot.config_hash.slice(0, 12)}` : "Loading" })] }), snapshot ? ((0, jsx_runtime_1.jsxs)("div", { className: "settings-head-meta", children: [(0, jsx_runtime_1.jsx)("span", { className: `reload-badge reload-${reloadTone}`, children: snapshot.reload_policy }), (0, jsx_runtime_1.jsx)("span", { children: snapshot.active_profile || "no profile" })] })) : null, (0, jsx_runtime_1.jsx)("button", { className: "icon-button", onClick: onClose, title: "Close", children: (0, jsx_runtime_1.jsx)(lucide_react_1.X, { size: 16 }) })] }), (0, jsx_runtime_1.jsxs)("div", { className: "settings-dialog-body", children: [(0, jsx_runtime_1.jsxs)("nav", { className: "settings-category-list", children: [(0, jsx_runtime_1.jsxs)("div", { className: "settings-scope-panel", children: [(0, jsx_runtime_1.jsx)("span", { children: "Scope" }), (0, jsx_runtime_1.jsxs)("div", { className: "segmented-control", children: [(0, jsx_runtime_1.jsx)("button", { className: scope === "project" ? "active" : "", onClick: () => setScope("project"), children: "Project" }), (0, jsx_runtime_1.jsx)("button", { className: scope === "profile" ? "active" : "", onClick: () => setScope("profile"), children: "Profile" }), (0, jsx_runtime_1.jsx)("button", { className: scope === "session" ? "active" : "", onClick: () => setScope("session"), disabled: !sessionId, children: "Session" })] }), (0, jsx_runtime_1.jsxs)("select", { value: snapshot?.active_profile || "", onChange: (event) => switchProfile(event.target.value), disabled: !snapshot || saving, children: [(0, jsx_runtime_1.jsx)("option", { value: "", children: "No active profile" }), (snapshot?.profiles || []).map((profile) => (0, jsx_runtime_1.jsx)("option", { value: profile, children: profile }, profile))] }), scope === "profile" ? ((0, jsx_runtime_1.jsx)("input", { value: profileDraft, onChange: (event) => setProfileDraft(event.target.value), placeholder: "profile name" })) : null] }), categories.map((item) => ((0, jsx_runtime_1.jsx)("button", { className: category === item ? "active" : "", onClick: () => setCategory(item), children: settingsCategoryLabels[item] || item }, item)))] }), (0, jsx_runtime_1.jsxs)("div", { className: "settings-editor", children: [(0, jsx_runtime_1.jsxs)("div", { className: "settings-editor-toolbar", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("strong", { children: settingsCategoryLabels[category] || category }), (0, jsx_runtime_1.jsx)("span", { children: scopeLabel(scope, profileDraft, sessionId) })] }), (0, jsx_runtime_1.jsxs)("button", { onClick: loadConfig, disabled: saving, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.RefreshCw, { size: 14 }), " Reload"] })] }), error ? (0, jsx_runtime_1.jsx)("p", { className: "settings-error", children: error }) : null, notice ? (0, jsx_runtime_1.jsx)("p", { className: "settings-success", children: notice }) : null, snapshot?.pending_effects?.length ? ((0, jsx_runtime_1.jsx)("div", { className: "settings-pending", children: snapshot.pending_effects.slice(0, 5).map((effect) => (0, jsx_runtime_1.jsx)("span", { children: effect }, effect)) })) : null, !snapshot ? (0, jsx_runtime_1.jsx)("p", { className: "muted", children: "Loading config..." }) : null, snapshot && visibleFields.map((field) => {
                                    const dirty = isFieldDirty(snapshot, drafts, field, scope, profileDraft);
                                    const source = snapshot.source_map[field.path] || "default/env";
                                    const fieldError = fieldErrors[field.path];
                                    return ((0, jsx_runtime_1.jsxs)("div", { className: `settings-field ${dirty ? "dirty" : ""} ${fieldError ? "invalid" : ""}`, children: [(0, jsx_runtime_1.jsxs)("div", { className: "settings-field-copy", children: [(0, jsx_runtime_1.jsx)("strong", { children: field.path }), (0, jsx_runtime_1.jsxs)("span", { children: [source, " \u00B7 ", field.reload_policy] }), field.description ? (0, jsx_runtime_1.jsx)("em", { children: field.description }) : null, fieldError ? (0, jsx_runtime_1.jsx)("b", { children: fieldError }) : null] }), renderConfigInput(field, drafts[field.path] || "", (value) => updateFieldDraft(field, value)), (0, jsx_runtime_1.jsx)("span", { className: "settings-field-state", children: dirty ? "Changed" : "Synced" })] }, field.path));
                                }), advancedOpen && snapshot ? ((0, jsx_runtime_1.jsxs)("div", { className: "settings-json-editor", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("strong", { children: "Advanced JSON" }), (0, jsx_runtime_1.jsx)("span", { children: scope === "project" ? "Project patch editor" : "Read-only layer preview" })] }), (0, jsx_runtime_1.jsx)("textarea", { value: jsonDraft, onChange: (event) => setJsonDraft(event.target.value), readOnly: scope !== "project" }), scope === "project" ? (0, jsx_runtime_1.jsx)("button", { onClick: applyJson, disabled: saving, children: "Apply JSON" }) : null] })) : null] })] }), (0, jsx_runtime_1.jsxs)("footer", { className: "settings-action-bar", children: [(0, jsx_runtime_1.jsx)("button", { onClick: () => setAdvancedOpen((value) => !value), children: advancedOpen ? "Hide JSON" : "Advanced JSON" }), (0, jsx_runtime_1.jsxs)("span", { children: [dirtyCount, " pending change", dirtyCount === 1 ? "" : "s"] }), (0, jsx_runtime_1.jsx)("button", { onClick: revertDrafts, disabled: !dirtyCount || saving, children: "Revert" }), (0, jsx_runtime_1.jsx)("button", { onClick: revertDrafts, disabled: !dirtyCount || saving, children: "Reset" }), (0, jsx_runtime_1.jsx)("button", { className: "primary", onClick: applyChanges, disabled: !dirtyCount || saving, children: saving ? "Applying" : "Apply" })] })] }) }));
}
function SettingsDialog({ sessionId, initialCategory, onClose, onSaved }) {
    const [snapshot, setSnapshot] = (0, react_1.useState)(null);
    const [category, setCategory] = (0, react_1.useState)(initialCategory);
    const [scope, setScope] = (0, react_1.useState)(sessionId ? "session" : "project");
    const [profileDraft, setProfileDraft] = (0, react_1.useState)("");
    const [drafts, setDrafts] = (0, react_1.useState)({});
    const [saving, setSaving] = (0, react_1.useState)(false);
    const [error, setError] = (0, react_1.useState)("");
    const [fieldErrors, setFieldErrors] = (0, react_1.useState)({});
    const [advancedOpen, setAdvancedOpen] = (0, react_1.useState)(false);
    const [jsonDraft, setJsonDraft] = (0, react_1.useState)("");
    (0, react_1.useEffect)(() => {
        setCategory(initialCategory);
    }, [initialCategory]);
    (0, react_1.useEffect)(() => {
        loadConfig().catch((err) => setError(err instanceof Error ? err.message : String(err)));
    }, [sessionId]);
    async function loadConfig() {
        const payload = await api_1.api.config(sessionId || undefined);
        setSnapshot(payload);
        setProfileDraft(payload.active_profile || payload.profiles[0] || "default");
        setDrafts(buildConfigDrafts(payload));
        setJsonDraft(JSON.stringify(readScopeConfig(payload, scope), null, 2));
        setError("");
        setFieldErrors({});
    }
    (0, react_1.useEffect)(() => {
        if (!snapshot)
            return;
        setJsonDraft(JSON.stringify(readScopeConfig(snapshot, scope, profileDraft), null, 2));
    }, [scope, profileDraft, snapshot]);
    async function applyChanges() {
        if (!snapshot)
            return;
        const dirtyFields = fields.filter((field) => isFieldDirty(snapshot, drafts, field, scope, profileDraft));
        if (dirtyFields.length === 0)
            return;
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
                    updated = await api_1.api.sessionConfigSet(sessionId, field.path, value);
                }
                else if (scope === "profile") {
                    updated = await api_1.api.configProfileSet(profileName, field.path, value, baseHash, sessionId || undefined);
                }
                else {
                    updated = await api_1.api.configSet(field.path, value, baseHash);
                }
                baseHash = updated.config_hash;
            }
            setSnapshot(updated);
            setDrafts(buildConfigDrafts(updated));
            setProfileDraft(updated.active_profile || profileName || updated.profiles[0] || "default");
            onSaved();
        }
        catch (err) {
            applyConfigError(err, setError, setFieldErrors);
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
        setFieldErrors({});
        try {
            const parsed = JSON.parse(jsonDraft || "{}");
            if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
                throw new Error("JSON must be an object.");
            const updated = await api_1.api.configPatch(parsed, snapshot.config_hash);
            setSnapshot(updated);
            setDrafts(buildConfigDrafts(updated));
            onSaved();
        }
        catch (err) {
            applyConfigError(err, setError, setFieldErrors);
        }
        finally {
            setSaving(false);
        }
    }
    async function switchProfile(value) {
        if (!snapshot)
            return;
        setSaving(true);
        setError("");
        try {
            const nextProfile = value || null;
            const updated = scope === "session" && sessionId
                ? await api_1.api.setSessionProfile(sessionId, nextProfile)
                : await api_1.api.setProjectProfile(nextProfile, snapshot.config_hash, sessionId || undefined);
            setSnapshot(updated);
            setProfileDraft(updated.active_profile || "");
            setDrafts(buildConfigDrafts(updated));
            onSaved();
        }
        catch (err) {
            applyConfigError(err, setError, setFieldErrors);
        }
        finally {
            setSaving(false);
        }
    }
    function revertDrafts() {
        if (!snapshot)
            return;
        setDrafts(buildConfigDrafts(snapshot));
        setJsonDraft(JSON.stringify(readScopeConfig(snapshot, scope, profileDraft), null, 2));
        setError("");
        setFieldErrors({});
    }
    const savingPath = saving ? "__batch__" : "";
    async function saveField(field) {
        if (!snapshot)
            return;
        setSaving(true);
        setError("");
        try {
            const value = parseFieldDraft(drafts[field.path], field.type);
            const updated = field.path === "model.model" && sessionId
                ? await api_1.api.setSessionModel(sessionId, String(value))
                : await api_1.api.configSet(field.path, value, snapshot.config_hash);
            setSnapshot(updated);
            setDrafts(buildConfigDrafts(updated));
            onSaved();
        }
        catch (err) {
            applyConfigError(err, setError, setFieldErrors);
        }
        finally {
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
    return ((0, jsx_runtime_1.jsx)("div", { className: "settings-dialog-backdrop", children: (0, jsx_runtime_1.jsxs)("section", { className: "settings-dialog", children: [(0, jsx_runtime_1.jsxs)("header", { className: "settings-dialog-head", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("small", { children: "CONFIG" }), (0, jsx_runtime_1.jsx)("h2", { children: "Dynamic settings" }), (0, jsx_runtime_1.jsx)("p", { children: snapshot ? `hash ${snapshot.config_hash.slice(0, 12)} · ${snapshot.reload_policy}` : "Loading" })] }), (0, jsx_runtime_1.jsx)("button", { className: "icon-button", onClick: onClose, title: "Close", children: (0, jsx_runtime_1.jsx)(lucide_react_1.X, { size: 16 }) })] }), (0, jsx_runtime_1.jsxs)("div", { className: "settings-dialog-body", children: [(0, jsx_runtime_1.jsx)("nav", { className: "settings-category-list", children: categories.map((item) => ((0, jsx_runtime_1.jsx)("button", { className: category === item ? "active" : "", onClick: () => setCategory(item), children: settingsCategoryLabels[item] || item }, item))) }), (0, jsx_runtime_1.jsxs)("div", { className: "settings-editor", children: [(0, jsx_runtime_1.jsxs)("div", { className: "settings-editor-toolbar", children: [(0, jsx_runtime_1.jsx)("strong", { children: settingsCategoryLabels[category] || category }), (0, jsx_runtime_1.jsxs)("button", { onClick: loadConfig, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.RefreshCw, { size: 14 }), " Reload"] })] }), error ? (0, jsx_runtime_1.jsx)("p", { className: "settings-error", children: error }) : null, !snapshot ? (0, jsx_runtime_1.jsx)("p", { className: "muted", children: "Loading config..." }) : null, snapshot && visibleFields.map((field) => {
                                    const dirty = drafts[field.path] !== stringifyConfigValue(readConfigPath(snapshot.settings, field.path));
                                    const source = snapshot.source_map[field.path] || "default/env";
                                    return ((0, jsx_runtime_1.jsxs)("div", { className: "settings-field", children: [(0, jsx_runtime_1.jsxs)("div", { className: "settings-field-copy", children: [(0, jsx_runtime_1.jsx)("strong", { children: field.path }), (0, jsx_runtime_1.jsxs)("span", { children: [source, " \u00B7 ", field.reload_policy] })] }), field.type === "boolean" ? ((0, jsx_runtime_1.jsx)("label", { className: "settings-toggle", children: (0, jsx_runtime_1.jsx)("input", { type: "checkbox", checked: drafts[field.path] === "true", onChange: (event) => setDrafts((current) => ({ ...current, [field.path]: String(event.target.checked) })) }) })) : ((0, jsx_runtime_1.jsx)("input", { value: drafts[field.path] || "", onChange: (event) => setDrafts((current) => ({ ...current, [field.path]: event.target.value })) })), (0, jsx_runtime_1.jsx)("button", { disabled: !dirty || savingPath === field.path, onClick: () => saveField(field), children: savingPath === field.path ? "Saving" : "Save" })] }, field.path));
                                })] })] })] }) }));
}
function ChatWorkspace({ transcriptRef, transcript, activeSnapshot, workspace, workspaceStatus, activeModel, activeSessionId, displayStatus, busy, prompt, promptSubmitting, activeApproval, setPrompt, sendPrompt, cancelActiveSession, activityItems, approvalSummary, approvalAction, approvalFeedback, attachments, attachmentUploading, approve, reject, refreshAttachments, uploadAttachment, deleteAttachment, openAttachments, inspectorTab, setInspectorTab, activeEvents, notice, inspectorOpen, setInspectorOpen, onWorkspaceChanged, onModelChanged }) {
    const [showScrollToBottom, setShowScrollToBottom] = (0, react_1.useState)(false);
    const [activeTurnId, setActiveTurnId] = (0, react_1.useState)("");
    const [workspaceTask, setWorkspaceTask] = (0, react_1.useState)(codingTaskApi_1.emptyCodingTaskState);
    const [workspaceTaskPhase, setWorkspaceTaskPhase] = (0, react_1.useState)("idle");
    const [workspaceTaskError, setWorkspaceTaskError] = (0, react_1.useState)("");
    const [workspaceTaskPrompt, setWorkspaceTaskPrompt] = (0, react_1.useState)("");
    const fileInputRef = (0, react_1.useRef)(null);
    const textareaRef = (0, react_1.useRef)(null);
    const nearBottomRef = (0, react_1.useRef)(true);
    const codingTaskClient = (0, react_1.useMemo)(() => (0, codingTaskApi_1.createCodingTaskClient)(import.meta.env), []);
    const workspaceTranscript = (0, react_1.useMemo)(() => buildWorkspaceTranscript(workspaceTask, workspaceTaskPrompt, workspaceTaskPhase, workspaceTaskError), [workspaceTask, workspaceTaskPrompt, workspaceTaskPhase, workspaceTaskError]);
    const unifiedTranscript = (0, react_1.useMemo)(() => [...transcript, ...workspaceTranscript], [transcript, workspaceTranscript]);
    const turnMarkers = (0, react_1.useMemo)(() => buildTurnMarkers(unifiedTranscript), [unifiedTranscript]);
    const transcriptTailKey = (0, react_1.useMemo)(() => {
        const tail = unifiedTranscript[unifiedTranscript.length - 1];
        return tail ? `${tail.id}:${tail.body.text.length}:${tail.streaming ? "streaming" : "done"}` : "empty";
    }, [unifiedTranscript]);
    (0, react_1.useEffect)(() => {
        const target = transcriptRef.current;
        if (!target)
            return;
        const updateScrollState = () => {
            const distanceFromBottom = target.scrollHeight - target.scrollTop - target.clientHeight;
            const nearBottom = distanceFromBottom <= SCROLL_BOTTOM_THRESHOLD;
            nearBottomRef.current = nearBottom;
            setShowScrollToBottom(!nearBottom && unifiedTranscript.length > 0);
            setActiveTurnId(findActiveTurnId(target, turnMarkers));
        };
        updateScrollState();
        target.addEventListener("scroll", updateScrollState, { passive: true });
        return () => target.removeEventListener("scroll", updateScrollState);
    }, [transcriptRef, unifiedTranscript.length, turnMarkers]);
    (0, react_1.useEffect)(() => {
        const target = transcriptRef.current;
        if (!target || !nearBottomRef.current)
            return;
        window.requestAnimationFrame(() => {
            target.scrollTo({ top: target.scrollHeight, behavior: "smooth" });
        });
    }, [transcriptRef, transcriptTailKey]);
    (0, react_1.useEffect)(() => {
        const target = textareaRef.current;
        if (!target)
            return;
        target.style.height = "auto";
        target.style.height = `${target.scrollHeight}px`;
    }, [prompt]);
    (0, react_1.useEffect)(() => {
        const target = transcriptRef.current;
        if (!target)
            return;
        window.requestAnimationFrame(() => {
            target.scrollTop = target.scrollHeight;
            nearBottomRef.current = true;
            setShowScrollToBottom(false);
            setActiveTurnId(turnMarkers[turnMarkers.length - 1]?.id || "");
        });
    }, [activeSessionId, transcriptRef]);
    const scrollToBottom = () => {
        const target = transcriptRef.current;
        if (!target)
            return;
        target.scrollTo({ top: target.scrollHeight, behavior: "smooth" });
    };
    const jumpToTurn = (marker) => {
        const target = transcriptRef.current;
        const element = target ? findTranscriptElement(target, marker.id) : null;
        if (!target || !element)
            return;
        target.scrollTo({ top: Math.max(0, element.offsetTop - 16), behavior: "smooth" });
        setActiveTurnId(marker.id);
    };
    async function submitUnifiedPrompt() {
        if (!prompt.trim() || promptSubmitting || busy || activeApproval)
            return;
        if (!shouldUseCodingWorkflowMock(prompt)) {
            sendPrompt();
            return;
        }
        const text = prompt;
        setPrompt("");
        setWorkspaceTaskPrompt(text);
        setWorkspaceTask(codingTaskApi_1.emptyCodingTaskState);
        setWorkspaceTaskError("");
        setWorkspaceTaskPhase("loading");
        try {
            const state = await codingTaskClient.startTask(text);
            setWorkspaceTask(state);
            setWorkspaceTaskPhase("success");
        }
        catch (error) {
            setPrompt(text);
            setWorkspaceTaskPhase("error");
            setWorkspaceTaskError(error instanceof Error ? error.message : String(error));
        }
    }
    return ((0, jsx_runtime_1.jsx)("div", { className: inspectorOpen ? "chat-layout with-inspector" : "chat-layout", children: (0, jsx_runtime_1.jsxs)("section", { className: "chat-stage", children: [(0, jsx_runtime_1.jsxs)("header", { className: "chat-header", children: [(0, jsx_runtime_1.jsxs)("div", { className: "chat-header-copy", children: [(0, jsx_runtime_1.jsxs)("div", { className: "crumbs", children: [(0, jsx_runtime_1.jsx)("span", { children: "PP-ECHO / CHAT" }), (0, jsx_runtime_1.jsx)("span", { children: shortId(activeSessionId) })] }), (0, jsx_runtime_1.jsx)("h2", { children: activeSnapshot?.history?.source === "stored" ? "历史会话" : "当前会话" }), (0, jsx_runtime_1.jsx)("p", { children: activeSnapshot?.messages?.length ? `${activeSnapshot.messages.length} 条消息` : "尚无消息" })] }), (0, jsx_runtime_1.jsxs)("div", { className: "chat-header-actions", children: [(0, jsx_runtime_1.jsx)("span", { className: "status-pill", children: displayStatus }), (0, jsx_runtime_1.jsx)("button", { className: "icon-button", onClick: () => setInspectorOpen((current) => !current), title: inspectorOpen ? "收起观察窗" : "展开观察窗", children: (0, jsx_runtime_1.jsx)(lucide_react_1.Activity, { size: 15 }) }), (0, jsx_runtime_1.jsxs)("button", { onClick: cancelActiveSession, disabled: !busy, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Square, { size: 14 }), "\u505C\u6B62"] })] })] }), notice ? (0, jsx_runtime_1.jsx)("div", { className: "inline-hint", children: notice.message }) : null, (0, jsx_runtime_1.jsxs)("section", { className: "transcript", ref: transcriptRef, children: [unifiedTranscript.length === 0 && ((0, jsx_runtime_1.jsxs)("div", { className: "empty", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Sparkles, { size: 26 }), (0, jsx_runtime_1.jsx)("h2", { children: "Unified Agent Workspace" }), (0, jsx_runtime_1.jsx)("p", { children: "Ask pp-Echo to explain, edit, test, or inspect this repo from one input." })] })), unifiedTranscript.map((item) => ((0, jsx_runtime_1.jsxs)("article", { className: `message ${item.role}${item.streaming ? " streaming" : ""}`, "data-transcript-id": item.id, children: [(0, jsx_runtime_1.jsx)("div", { className: "avatar", children: item.role === "assistant" ? (0, jsx_runtime_1.jsx)(lucide_react_1.Bot, { size: 16 }) : item.role === "activity" ? (0, jsx_runtime_1.jsx)(lucide_react_1.Code2, { size: 15 }) : (0, jsx_runtime_1.jsx)(lucide_react_1.MessageSquare, { size: 15 }) }), item.role === "workspace" ? ((0, jsx_runtime_1.jsx)(AgentWorkspaceResult, { state: workspaceTask, phase: workspaceTaskPhase, error: workspaceTaskError })) : item.role === "activity" && item.activity ? ((0, jsx_runtime_1.jsx)(ActivityCard_1.ActivityCard, { item: item.activity })) : ((0, jsx_runtime_1.jsxs)("div", { className: "bubble", children: [(0, jsx_runtime_1.jsx)("span", { children: roleLabel(item.role) }), (0, jsx_runtime_1.jsx)(rich_text_1.RichMessageContent, { text: item.body.text, attachments: item.body.attachments, streaming: item.streaming, plain: activeSnapshot?.history?.source === "stored" && !item.streaming })] }))] }, item.id)))] }), (0, jsx_runtime_1.jsx)(ConversationTurnRail, { markers: turnMarkers, activeTurnId: activeTurnId, onJump: jumpToTurn }), showScrollToBottom ? ((0, jsx_runtime_1.jsx)("button", { className: "scroll-to-bottom", onClick: scrollToBottom, title: "\u6EDA\u52A8\u5230\u5E95\u90E8", "aria-label": "\u6EDA\u52A8\u5230\u5E95\u90E8", children: (0, jsx_runtime_1.jsx)(lucide_react_1.ArrowDown, { size: 17 }) })) : null, activeApproval ? ((0, jsx_runtime_1.jsxs)("section", { className: "composer-approval", "aria-live": "polite", children: [(0, jsx_runtime_1.jsxs)("div", { className: "composer-approval-copy", children: [(0, jsx_runtime_1.jsx)("p", { className: "approval-kind", children: activeApproval.title }), (0, jsx_runtime_1.jsx)("p", { children: activeApproval.description }), (0, jsx_runtime_1.jsxs)("div", { className: "composer-approval-meta", children: [activeApproval.meta ? (0, jsx_runtime_1.jsx)("small", { children: activeApproval.meta }) : null, (0, jsx_runtime_1.jsx)("code", { children: String(activeApproval.token).slice(0, 18) })] })] }), (0, jsx_runtime_1.jsxs)("div", { className: "split-actions", children: [(0, jsx_runtime_1.jsxs)("button", { disabled: Boolean(approvalAction), onClick: approve, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Check, { size: 15 }), " ", approvalAction?.token === activeApproval.token && approvalAction.action === "approve" ? "处理中..." : activeApproval.approveLabel] }), (0, jsx_runtime_1.jsxs)("button", { disabled: Boolean(approvalAction), onClick: reject, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.X, { size: 15 }), " ", approvalAction?.token === activeApproval.token && approvalAction.action === "reject" ? "处理中..." : "拒绝"] })] })] })) : null, (0, jsx_runtime_1.jsx)("footer", { className: "composer-shell", children: (0, jsx_runtime_1.jsxs)("div", { className: "composer-input-card", children: [(0, jsx_runtime_1.jsx)("input", { ref: fileInputRef, type: "file", className: "attachment-input", onChange: (event) => {
                                    const file = event.target.files?.[0];
                                    if (file)
                                        uploadAttachment(file);
                                    event.currentTarget.value = "";
                                } }), (0, jsx_runtime_1.jsx)("button", { className: "composer-icon-button", disabled: !activeSessionId || busy || Boolean(activeApproval) || attachmentUploading, onClick: () => fileInputRef.current?.click(), title: "Upload attachment", type: "button", children: (0, jsx_runtime_1.jsx)(lucide_react_1.Plus, { size: 15 }) }), (0, jsx_runtime_1.jsxs)("button", { className: "composer-pill-button", disabled: !activeSessionId, onClick: openAttachments, title: "Open attachments", type: "button", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.FileText, { size: 14 }), (0, jsx_runtime_1.jsx)("span", { children: "Files" })] }), (0, jsx_runtime_1.jsx)("textarea", { ref: textareaRef, value: prompt, onChange: (event) => setPrompt(event.target.value), onInput: (event) => {
                                    const target = event.currentTarget;
                                    target.style.height = "auto";
                                    target.style.height = `${target.scrollHeight}px`;
                                }, onKeyDown: (event) => {
                                    if (event.key === "Enter" && !event.shiftKey) {
                                        event.preventDefault();
                                        submitUnifiedPrompt();
                                    }
                                }, placeholder: "Ask pp-Echo to explain, edit, test, or inspect this repo...", disabled: !activeSessionId || busy || Boolean(activeApproval), rows: 1 }), (0, jsx_runtime_1.jsx)("button", { className: "composer-send-button", disabled: !activeSessionId || !prompt.trim() || Boolean(activeApproval) || busy || promptSubmitting || workspaceTaskPhase === "loading", onClick: submitUnifiedPrompt, title: "Send message", type: "button", children: (0, jsx_runtime_1.jsx)(lucide_react_1.Send, { size: 14 }) })] }) }), (0, jsx_runtime_1.jsx)(AttachmentStrip, { attachments: attachments, uploading: attachmentUploading, onDelete: deleteAttachment }), (0, jsx_runtime_1.jsxs)("div", { className: "composer-statusbar", children: [(0, jsx_runtime_1.jsxs)("span", { children: [(0, jsx_runtime_1.jsx)(lucide_react_1.FolderOpen, { size: 14 }), workspaceStatus?.name || workspace.active.name || "workspace"] }), (0, jsx_runtime_1.jsx)(ComposerGitBranchButton, { workspaceStatus: workspaceStatus, onChanged: onWorkspaceChanged }), (0, jsx_runtime_1.jsx)(ComposerModelButton, { activeSessionId: activeSessionId, activeModel: activeModel, onChanged: onModelChanged })] })] }) }));
}
function ComposerGitBranchButton({ workspaceStatus, onChanged }) {
    const [open, setOpen] = (0, react_1.useState)(false);
    const [git, setGit] = (0, react_1.useState)(null);
    const [query, setQuery] = (0, react_1.useState)("");
    const [newBranch, setNewBranch] = (0, react_1.useState)("");
    const [busy, setBusy] = (0, react_1.useState)("");
    const [error, setError] = (0, react_1.useState)("");
    (0, react_1.useEffect)(() => {
        if (!open)
            return;
        loadGit();
    }, [open]);
    async function loadGit() {
        setError("");
        try {
            setGit(await api_1.api.workspaceGit());
        }
        catch (err) {
            setError(err instanceof Error ? err.message : String(err));
        }
    }
    async function switchBranch(branch) {
        if (git?.dirty_count && !window.confirm("Workspace has local changes. Git switch will keep them, but conflicts can still block the switch. Continue?"))
            return;
        setBusy(branch);
        setError("");
        try {
            const next = await api_1.api.switchGitBranch(branch);
            setGit(next);
            onChanged();
            setOpen(false);
        }
        catch (err) {
            setError(err instanceof Error ? err.message : String(err));
        }
        finally {
            setBusy("");
        }
    }
    async function createBranch() {
        const branch = newBranch.trim();
        if (!branch)
            return;
        setBusy("create");
        setError("");
        try {
            const next = await api_1.api.createGitBranch(branch);
            setGit(next);
            setNewBranch("");
            onChanged();
            setOpen(false);
        }
        catch (err) {
            setError(err instanceof Error ? err.message : String(err));
        }
        finally {
            setBusy("");
        }
    }
    const branches = (git?.branches || []).filter((branch) => branch.name.toLowerCase().includes(query.trim().toLowerCase()));
    const label = git?.current_branch || workspaceStatus?.git_branch || "no branch";
    const dirty = git?.dirty_count ?? workspaceStatus?.git_dirty_count ?? 0;
    return ((0, jsx_runtime_1.jsxs)("div", { className: "composer-popover-wrap", children: [(0, jsx_runtime_1.jsxs)("button", { className: "composer-status-button", onClick: () => setOpen((current) => !current), type: "button", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.GitBranch, { size: 14 }), (0, jsx_runtime_1.jsx)("span", { children: label }), dirty ? (0, jsx_runtime_1.jsx)("em", { children: dirty }) : null, (0, jsx_runtime_1.jsx)(lucide_react_1.ChevronDown, { size: 13 })] }), open ? ((0, jsx_runtime_1.jsxs)("div", { className: "composer-popover branch-popover", children: [(0, jsx_runtime_1.jsxs)("label", { className: "composer-popover-search", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Search, { size: 14 }), (0, jsx_runtime_1.jsx)("input", { value: query, onChange: (event) => setQuery(event.target.value), placeholder: "Search branches" })] }), error ? (0, jsx_runtime_1.jsx)("div", { className: "composer-popover-error", children: error }) : null, !git?.is_repo ? (0, jsx_runtime_1.jsx)("div", { className: "composer-popover-empty", children: "This workspace is not a git repository." }) : null, git?.is_repo ? ((0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsx)("div", { className: "composer-popover-section", children: "Branches" }), (0, jsx_runtime_1.jsx)("div", { className: "composer-popover-list", children: branches.map((branch) => ((0, jsx_runtime_1.jsxs)("button", { onClick: () => switchBranch(branch.name), disabled: Boolean(busy), type: "button", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.GitBranch, { size: 14 }), (0, jsx_runtime_1.jsxs)("span", { children: [(0, jsx_runtime_1.jsx)("strong", { children: branch.name }), (0, jsx_runtime_1.jsx)("small", { children: branch.upstream || (git.dirty_count ? `${git.dirty_count} changed files` : "clean") })] }), branch.current ? (0, jsx_runtime_1.jsx)(lucide_react_1.Check, { size: 15 }) : null] }, branch.name))) }), (0, jsx_runtime_1.jsxs)("div", { className: "composer-popover-create", children: [(0, jsx_runtime_1.jsx)("input", { value: newBranch, onChange: (event) => setNewBranch(event.target.value), placeholder: "Create new branch" }), (0, jsx_runtime_1.jsxs)("button", { onClick: createBranch, disabled: !newBranch.trim() || Boolean(busy), type: "button", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Plus, { size: 14 }), " Create"] })] })] })) : null] })) : null] }));
}
function AgentWorkspaceResult({ state, phase, error }) {
    if (phase === "loading") {
        return ((0, jsx_runtime_1.jsxs)("div", { className: "agent-workspace-card loading", "aria-live": "polite", children: [(0, jsx_runtime_1.jsxs)("div", { className: "agent-workspace-head", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("span", { children: "Agent Workspace" }), (0, jsx_runtime_1.jsx)("h3", { children: "Preparing controlled workflow" })] }), (0, jsx_runtime_1.jsx)(BadgeTone, { tone: "running", children: "loading" })] }), (0, jsx_runtime_1.jsx)("div", { className: "workspace-skeleton" }), (0, jsx_runtime_1.jsx)("div", { className: "workspace-skeleton short" })] }));
    }
    if (phase === "error") {
        return ((0, jsx_runtime_1.jsxs)("div", { className: "agent-workspace-card error", role: "alert", children: [(0, jsx_runtime_1.jsxs)("div", { className: "agent-workspace-head", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("span", { children: "Agent Workspace" }), (0, jsx_runtime_1.jsx)("h3", { children: "Workflow preview failed" })] }), (0, jsx_runtime_1.jsx)(BadgeTone, { tone: "error", children: "error" })] }), (0, jsx_runtime_1.jsx)("p", { children: error || "Could not prepare the workspace task." })] }));
    }
    const emptyTimeline = state.timeline_blocks.length === 0;
    return ((0, jsx_runtime_1.jsxs)("div", { className: `agent-workspace-card ${state.status === "awaiting_approval" ? "awaiting" : ""}`, children: [(0, jsx_runtime_1.jsxs)("div", { className: "agent-workspace-head", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("span", { children: "Agent Workspace" }), (0, jsx_runtime_1.jsx)("h3", { children: state.task || "Workspace task" })] }), (0, jsx_runtime_1.jsx)(BadgeTone, { tone: state.status === "awaiting_approval" ? "warning" : "success", children: state.status })] }), state.workflow_summary ? (0, jsx_runtime_1.jsx)("p", { className: "agent-workspace-summary", children: state.workflow_summary }) : null, (0, jsx_runtime_1.jsxs)("div", { className: "agent-workspace-counters", children: [(0, jsx_runtime_1.jsxs)("span", { children: ["tools ", state.runtime_counters.tool_calls ?? 0] }), (0, jsx_runtime_1.jsxs)("span", { children: ["shell ", state.runtime_counters.shell_commands ?? 0] }), (0, jsx_runtime_1.jsxs)("span", { children: ["patches ", state.runtime_counters.patch_candidates ?? 0] }), state.stop_reason ? (0, jsx_runtime_1.jsx)("span", { children: state.stop_reason }) : null] }), (0, jsx_runtime_1.jsxs)("section", { className: "workspace-section", children: [(0, jsx_runtime_1.jsxs)("div", { className: "workspace-section-title", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Code2, { size: 15 }), (0, jsx_runtime_1.jsx)("strong", { children: "Timeline" })] }), emptyTimeline ? (0, jsx_runtime_1.jsx)("p", { className: "muted", children: "No timeline blocks yet." }) : ((0, jsx_runtime_1.jsx)("div", { className: "workspace-timeline-list", children: state.timeline_blocks.map((block, index) => (0, jsx_runtime_1.jsx)(TimelineBlockCard, { block: block }, `${block.type}-${index}`)) }))] }), (0, jsx_runtime_1.jsxs)("section", { className: "workspace-section", children: [(0, jsx_runtime_1.jsxs)("div", { className: "workspace-section-title", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.ShieldCheck, { size: 15 }), (0, jsx_runtime_1.jsx)("strong", { children: "Pending approvals" })] }), state.pending_approvals.length === 0 ? (0, jsx_runtime_1.jsx)("p", { className: "muted", children: "No pending approvals." }) : ((0, jsx_runtime_1.jsx)("div", { className: "workspace-approval-list", children: state.pending_approvals.map((approval) => (0, jsx_runtime_1.jsx)(PendingApprovalCard, { approval: approval }, approval.token)) }))] }), (0, jsx_runtime_1.jsxs)("section", { className: "workspace-section", children: [(0, jsx_runtime_1.jsxs)("div", { className: "workspace-section-title", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Check, { size: 15 }), (0, jsx_runtime_1.jsx)("strong", { children: "Validation commands" })] }), state.validation_commands.length === 0 ? (0, jsx_runtime_1.jsx)("p", { className: "muted", children: "No validation commands inferred." }) : ((0, jsx_runtime_1.jsx)("div", { className: "validation-command-list", children: state.validation_commands.map((command) => (0, jsx_runtime_1.jsx)(ValidationCommandCard, { command: command }, command.command)) }))] }), state.warnings.length > 0 ? ((0, jsx_runtime_1.jsx)("div", { className: "workspace-alert", children: state.warnings.slice(0, 3).map((warning) => (0, jsx_runtime_1.jsx)("span", { children: warning }, warning)) })) : null] }));
}
function TimelineBlockCard({ block }) {
    return ((0, jsx_runtime_1.jsxs)("article", { className: "workspace-timeline-card", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)(BadgeTone, { tone: timelineTone(block.status), children: timelineLabel(block.type) }), (0, jsx_runtime_1.jsx)("strong", { children: block.title || timelineLabel(block.type) })] }), block.summary ? (0, jsx_runtime_1.jsx)("p", { children: block.summary }) : null, block.details ? (0, jsx_runtime_1.jsx)("small", { children: compactDetails(block.details) }) : null] }));
}
function PendingApprovalCard({ approval }) {
    return ((0, jsx_runtime_1.jsxs)("article", { className: "workspace-approval-card", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)(BadgeTone, { tone: "warning", children: approval.action_type }), (0, jsx_runtime_1.jsx)("strong", { children: approval.summary || approval.tool_name || approval.action_type })] }), (0, jsx_runtime_1.jsxs)("dl", { children: [(0, jsx_runtime_1.jsx)("dt", { children: "tool" }), (0, jsx_runtime_1.jsx)("dd", { children: approval.tool_name || "unknown" }), (0, jsx_runtime_1.jsx)("dt", { children: "token" }), (0, jsx_runtime_1.jsx)("dd", { children: approval.token }), approval.command ? (0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsx)("dt", { children: "command" }), (0, jsx_runtime_1.jsx)("dd", { children: (0, jsx_runtime_1.jsx)("code", { children: approval.command }) })] }) : null, approval.changed_files.length ? (0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsx)("dt", { children: "files" }), (0, jsx_runtime_1.jsx)("dd", { children: approval.changed_files.join(", ") })] }) : null, approval.scope_check ? (0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsx)("dt", { children: "scope" }), (0, jsx_runtime_1.jsxs)("dd", { children: [String(approval.scope_check.allowed), " ", approval.scope_check.reason ? `- ${approval.scope_check.reason}` : ""] })] }) : null] }), (0, jsx_runtime_1.jsxs)("div", { className: "split-actions", children: [(0, jsx_runtime_1.jsx)("button", { disabled: true, title: "Approve wiring will use the existing approval flow later", children: "Approve" }), (0, jsx_runtime_1.jsx)("button", { disabled: true, title: "Reject wiring will use the existing approval flow later", children: "Reject" })] })] }));
}
function ValidationCommandCard({ command }) {
    return ((0, jsx_runtime_1.jsxs)("article", { className: "validation-command-card", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)(BadgeTone, { tone: command.priority === "full" ? "warning" : "success", children: command.priority || command.kind || "command" }), (0, jsx_runtime_1.jsx)("code", { children: command.command })] }), command.reason ? (0, jsx_runtime_1.jsx)("p", { children: command.reason }) : null] }));
}
function BadgeTone({ tone, children }) {
    return (0, jsx_runtime_1.jsx)("span", { className: `workspace-badge ${tone}`, children: children });
}
function buildWorkspaceTranscript(state, task, phase, error) {
    if (phase === "idle" || !task.trim())
        return [];
    return [
        {
            id: `workspace-user:${state.task_id}:${task}`,
            role: "user",
            body: { text: task, attachments: [] }
        },
        {
            id: `workspace-state:${state.task_id}:${phase}`,
            role: "workspace",
            body: { text: error || state.workflow_summary || state.status || "Workspace task", attachments: [] },
            streaming: phase === "loading"
        }
    ];
}
function shouldUseCodingWorkflowMock(value) {
    return /\b(code|coding|edit|test|inspect|repo|repository|file|build|fix|refactor|implement)\b/i.test(value);
}
function timelineLabel(type) {
    const labels = {
        repository_analysis: "已分析仓库结构",
        plan: "已生成任务计划",
        task_scope: "已生成任务范围",
        change_impact: "已分析变更影响",
        validation_plan: "已生成验证计划",
        execution_session: "执行会话",
        controlled_tool_loop: "执行状态"
    };
    return labels[type] || type.replace(/_/g, " ");
}
function timelineTone(status) {
    if (status === "waiting_approval")
        return "warning";
    if (status === "failed" || status === "error")
        return "error";
    if (status === "running")
        return "running";
    return "success";
}
function compactDetails(details) {
    const bits = Object.entries(details)
        .filter(([key, value]) => value !== null && value !== undefined && !["payload", "diff", "manifest", "content_text"].includes(key))
        .slice(0, 4)
        .map(([key, value]) => `${key}: ${typeof value === "object" ? JSON.stringify(value) : String(value)}`);
    return bits.join(" · ");
}
function ComposerModelButton({ activeSessionId, activeModel, onChanged }) {
    const [open, setOpen] = (0, react_1.useState)(false);
    const [snapshot, setSnapshot] = (0, react_1.useState)(null);
    const [providerPresets, setProviderPresets] = (0, react_1.useState)([]);
    const [query, setQuery] = (0, react_1.useState)("");
    const [busy, setBusy] = (0, react_1.useState)("");
    const [error, setError] = (0, react_1.useState)("");
    const [displayModel, setDisplayModel] = (0, react_1.useState)(activeModel);
    (0, react_1.useEffect)(() => {
        setDisplayModel(activeModel);
    }, [activeModel]);
    (0, react_1.useEffect)(() => {
        if (!open)
            return;
        Promise.all([api_1.api.config(activeSessionId || undefined), api_1.api.modelProviders()])
            .then(([configPayload, providersPayload]) => {
            setSnapshot(configPayload);
            setProviderPresets(providersPayload.providers);
        })
            .catch((err) => setError(err instanceof Error ? err.message : String(err)));
    }, [open, activeSessionId]);
    const models = (0, react_1.useMemo)(() => modelCandidates(snapshot, displayModel, providerPresets), [snapshot, displayModel, providerPresets]);
    const activeProvider = String(readConfigPath(snapshot?.effective_config || {}, "provider.name") || readConfigPath(snapshot?.effective_config || {}, "model.provider") || "");
    const filteredModels = models.filter((candidate) => `${candidate.providerLabel} ${candidate.model}`.toLowerCase().includes(query.trim().toLowerCase()));
    const effortField = snapshot?.schema.fields.find((field) => /reasoning|effort|thinking/i.test(field.path) && field.options?.length);
    async function chooseModel(candidate) {
        setBusy(candidate.key);
        setError("");
        try {
            const test = await api_1.api.modelTest({ name: candidate.providerId, base_url: candidate.baseUrl, api_key_env: candidate.apiKeyEnv }, { provider: candidate.providerId, model: candidate.model, temperature: 0.2, enable_thinking: false });
            if (test.status !== "ok") {
                const detail = test.safe_detail ? ` ${test.safe_detail}` : "";
                throw new Error(`${test.message}${detail}`);
            }
            if (activeSessionId) {
                await api_1.api.setSessionModel(activeSessionId, candidate.model, candidate.providerId || undefined);
            }
            else {
                const baseHash = snapshot?.config_hash;
                if (candidate.providerId) {
                    await api_1.api.applyModelPreset(candidate.providerId, candidate.model, baseHash);
                }
                else {
                    await api_1.api.configSet("model.model", candidate.model, baseHash);
                }
            }
            setDisplayModel(candidate.model);
            onChanged();
            setOpen(false);
        }
        catch (err) {
            setError(err instanceof Error ? err.message : String(err));
        }
        finally {
            setBusy("");
        }
    }
    async function chooseEffort(value) {
        if (!effortField || !snapshot)
            return;
        setBusy(value);
        setError("");
        try {
            if (activeSessionId && effortField.session_override) {
                await api_1.api.sessionConfigSet(activeSessionId, effortField.path, value);
            }
            else {
                await api_1.api.configSet(effortField.path, value, snapshot.config_hash);
            }
            onChanged();
            setSnapshot(await api_1.api.config(activeSessionId || undefined));
        }
        catch (err) {
            setError(err instanceof Error ? err.message : String(err));
        }
        finally {
            setBusy("");
        }
    }
    return ((0, jsx_runtime_1.jsxs)("div", { className: "composer-popover-wrap", children: [(0, jsx_runtime_1.jsxs)("button", { className: "composer-status-button", onClick: () => setOpen((current) => !current), type: "button", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Monitor, { size: 14 }), (0, jsx_runtime_1.jsx)("span", { children: displayModel || "model pending" }), (0, jsx_runtime_1.jsx)(lucide_react_1.ChevronDown, { size: 13 })] }), open ? ((0, jsx_runtime_1.jsxs)("div", { className: "composer-popover model-popover", children: [(0, jsx_runtime_1.jsxs)("label", { className: "composer-popover-search", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Search, { size: 14 }), (0, jsx_runtime_1.jsx)("input", { value: query, onChange: (event) => setQuery(event.target.value), placeholder: "Search models" })] }), error ? (0, jsx_runtime_1.jsx)("div", { className: "composer-popover-error", children: error }) : null, effortField?.options?.length ? ((0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsx)("div", { className: "composer-popover-section", children: "Reasoning" }), (0, jsx_runtime_1.jsx)("div", { className: "composer-segment-row", children: effortField.options.map((option) => ((0, jsx_runtime_1.jsx)("button", { onClick: () => chooseEffort(option), disabled: Boolean(busy), type: "button", children: option }, option))) })] })) : null, (0, jsx_runtime_1.jsx)("div", { className: "composer-popover-section", children: "Models" }), (0, jsx_runtime_1.jsxs)("div", { className: "composer-popover-list", children: [filteredModels.map((candidate) => ((0, jsx_runtime_1.jsxs)("button", { onClick: () => chooseModel(candidate), disabled: Boolean(busy), type: "button", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Monitor, { size: 14 }), (0, jsx_runtime_1.jsxs)("span", { children: [(0, jsx_runtime_1.jsx)("strong", { children: candidate.model }), (0, jsx_runtime_1.jsx)("small", { children: candidate.providerLabel })] }), candidate.model === displayModel && (!candidate.providerId || candidate.providerId === activeProvider) ? (0, jsx_runtime_1.jsx)(lucide_react_1.Check, { size: 15 }) : null] }, candidate.key))), !filteredModels.length ? (0, jsx_runtime_1.jsx)("div", { className: "composer-popover-empty", children: "No models match this search." }) : null] })] })) : null] }));
}
function UsagePanel() {
    const [rows, setRows] = (0, react_1.useState)([]);
    const [error, setError] = (0, react_1.useState)("");
    const [loading, setLoading] = (0, react_1.useState)(true);
    (0, react_1.useEffect)(() => {
        loadUsage().catch((err) => setError(err instanceof Error ? err.message : String(err)));
    }, []);
    async function loadUsage() {
        setLoading(true);
        setError("");
        try {
            const payload = await api_1.api.modelUsage();
            setRows(payload.models);
        }
        finally {
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
    return ((0, jsx_runtime_1.jsxs)("section", { className: "usage-panel", children: [(0, jsx_runtime_1.jsxs)("div", { className: "usage-head", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("small", { children: "MODEL USAGE" }), (0, jsx_runtime_1.jsx)("h2", { children: "Configured models" }), (0, jsx_runtime_1.jsx)("p", { children: "Provider presets with visible API key env status and trace usage totals." })] }), (0, jsx_runtime_1.jsxs)("button", { onClick: loadUsage, disabled: loading, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.RefreshCw, { size: 14 }), " Refresh"] })] }), error ? (0, jsx_runtime_1.jsx)("p", { className: "settings-error", children: error }) : null, (0, jsx_runtime_1.jsxs)("div", { className: "usage-summary-grid", children: [(0, jsx_runtime_1.jsx)(MetricCard, { label: "Configured", value: `${configuredCount}/${rows.length}` }), (0, jsx_runtime_1.jsx)(MetricCard, { label: "Runs", value: totals.runs }), (0, jsx_runtime_1.jsx)(MetricCard, { label: "LLM Calls", value: totals.calls }), (0, jsx_runtime_1.jsx)(MetricCard, { label: "Tokens", value: totals.tokens.toLocaleString() }), (0, jsx_runtime_1.jsx)(MetricCard, { label: "Cost", value: totals.cost ? `$${totals.cost.toFixed(6)}` : "N/A" })] }), (0, jsx_runtime_1.jsxs)("div", { className: "usage-table-wrap", children: [(0, jsx_runtime_1.jsxs)("table", { className: "usage-table", children: [(0, jsx_runtime_1.jsx)("thead", { children: (0, jsx_runtime_1.jsxs)("tr", { children: [(0, jsx_runtime_1.jsx)("th", { children: "Provider" }), (0, jsx_runtime_1.jsx)("th", { children: "Model" }), (0, jsx_runtime_1.jsx)("th", { children: "Configured" }), (0, jsx_runtime_1.jsx)("th", { children: "Active" }), (0, jsx_runtime_1.jsx)("th", { children: "Runs" }), (0, jsx_runtime_1.jsx)("th", { children: "Calls" }), (0, jsx_runtime_1.jsx)("th", { children: "Input" }), (0, jsx_runtime_1.jsx)("th", { children: "Output" }), (0, jsx_runtime_1.jsx)("th", { children: "Total" }), (0, jsx_runtime_1.jsx)("th", { children: "Cost" })] }) }), (0, jsx_runtime_1.jsx)("tbody", { children: rows.map((row) => ((0, jsx_runtime_1.jsxs)("tr", { children: [(0, jsx_runtime_1.jsxs)("td", { children: [(0, jsx_runtime_1.jsx)("strong", { children: row.provider_label }), (0, jsx_runtime_1.jsx)("small", { children: row.api_key_env || "-" })] }), (0, jsx_runtime_1.jsx)("td", { children: row.model }), (0, jsx_runtime_1.jsx)("td", { children: row.api_key_configured ? "Yes" : "Missing env" }), (0, jsx_runtime_1.jsx)("td", { children: row.current ? "Current" : "-" }), (0, jsx_runtime_1.jsx)("td", { children: row.runs }), (0, jsx_runtime_1.jsx)("td", { children: row.llm_calls }), (0, jsx_runtime_1.jsx)("td", { children: row.input_tokens.toLocaleString() }), (0, jsx_runtime_1.jsx)("td", { children: row.output_tokens.toLocaleString() }), (0, jsx_runtime_1.jsx)("td", { children: row.total_tokens.toLocaleString() }), (0, jsx_runtime_1.jsx)("td", { children: row.total_cost_usd == null ? "N/A" : `$${row.total_cost_usd.toFixed(6)}` })] }, `${row.provider_id}:${row.model}`))) })] }), !rows.length && !loading ? (0, jsx_runtime_1.jsx)("p", { className: "muted", children: "No model usage records." }) : null, loading ? (0, jsx_runtime_1.jsx)("p", { className: "muted", children: "Loading usage..." }) : null] })] }));
}
function MetricCard({ label, value }) {
    return ((0, jsx_runtime_1.jsxs)("div", { className: "usage-metric", children: [(0, jsx_runtime_1.jsx)("span", { children: label }), (0, jsx_runtime_1.jsx)("strong", { children: value })] }));
}
function modelCandidates(snapshot, activeModel, providerPresets) {
    const values = new Map();
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
        if (!values.has(key))
            values.set(key, { key, providerId: configuredProvider, providerLabel: configuredProviderLabel, model: option, baseUrl: String(readConfigPath(snapshot?.effective_config || {}, "provider.base_url") || ""), apiKeyEnv: String(readConfigPath(snapshot?.effective_config || {}, "provider.api_key_env") || "") });
    });
    const configured = snapshot ? readConfigPath(snapshot.effective_config, "model.model") : "";
    if (typeof configured === "string" && configured.trim()) {
        const model = configured.trim();
        const key = `${configuredProvider || "current"}:${model}`;
        if (!values.has(key))
            values.set(key, { key, providerId: configuredProvider, providerLabel: configuredProviderLabel, model, baseUrl: String(readConfigPath(snapshot?.effective_config || {}, "provider.base_url") || ""), apiKeyEnv: String(readConfigPath(snapshot?.effective_config || {}, "provider.api_key_env") || "") });
    }
    if (activeModel.trim()) {
        const model = activeModel.trim();
        const key = `${configuredProvider || "current"}:${model}`;
        if (!values.has(key))
            values.set(key, { key, providerId: configuredProvider, providerLabel: configuredProviderLabel, model, baseUrl: String(readConfigPath(snapshot?.effective_config || {}, "provider.base_url") || ""), apiKeyEnv: String(readConfigPath(snapshot?.effective_config || {}, "provider.api_key_env") || "") });
    }
    return Array.from(values.values()).filter((candidate) => candidate.model);
}
function modelProviderLabel(model) {
    const lower = model.toLowerCase();
    if (lower.includes("qwen"))
        return "Qwen";
    if (lower.includes("mimo"))
        return "Xiaomi MiMo";
    if (lower.includes("deepseek"))
        return "DeepSeek";
    if (lower.includes("gpt") || lower.includes("o3") || lower.includes("o4"))
        return "OpenAI";
    if (lower.includes("claude"))
        return "Anthropic";
    return "Model";
}
function ConversationTurnRail({ markers, activeTurnId, onJump }) {
    if (markers.length < 2)
        return null;
    return ((0, jsx_runtime_1.jsx)("nav", { className: "turn-rail", "aria-label": "\u5BF9\u8BDD\u8F6E\u6B21\u5BFC\u822A", children: markers.map((marker) => ((0, jsx_runtime_1.jsxs)("button", { className: `turn-marker${marker.id === activeTurnId ? " active" : ""}`, onClick: () => onJump(marker), title: `第 ${marker.turnNumber} 轮`, "aria-label": `跳转到第 ${marker.turnNumber} 轮`, children: [(0, jsx_runtime_1.jsx)("span", { className: "turn-marker-line" }), (0, jsx_runtime_1.jsxs)("span", { className: "turn-preview", role: "tooltip", children: [(0, jsx_runtime_1.jsxs)("strong", { children: ["\u7B2C ", marker.turnNumber, " \u8F6E"] }), (0, jsx_runtime_1.jsx)("span", { children: marker.userPreview || "用户消息" }), marker.assistantPreview ? (0, jsx_runtime_1.jsx)("em", { children: marker.assistantPreview }) : null] })] }, marker.id))) }));
}
function AttachmentWorkbench({ activeSessionId, attachments, uploading, onRefresh, onDelete, onUpload }) {
    const inputRef = (0, react_1.useRef)(null);
    return ((0, jsx_runtime_1.jsxs)("section", { className: "attachment-workbench", children: [(0, jsx_runtime_1.jsx)("input", { ref: inputRef, type: "file", className: "attachment-input", onChange: (event) => {
                    const file = event.target.files?.[0];
                    if (file)
                        onUpload(file);
                    event.currentTarget.value = "";
                } }), (0, jsx_runtime_1.jsxs)("div", { className: "attachment-workbench-toolbar", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsxs)("strong", { children: [attachments.length, " attachments"] }), (0, jsx_runtime_1.jsx)("span", { children: activeSessionId ? shortId(activeSessionId) : "no active session" })] }), (0, jsx_runtime_1.jsxs)("button", { type: "button", onClick: () => inputRef.current?.click(), disabled: !activeSessionId || uploading, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Paperclip, { size: 15 }), " Upload"] }), (0, jsx_runtime_1.jsxs)("button", { type: "button", onClick: onRefresh, disabled: !activeSessionId, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.RefreshCw, { size: 15 }), " Refresh"] })] }), activeSessionId ? ((0, jsx_runtime_1.jsx)(AttachmentPanel_1.AttachmentPanel, { sessionId: activeSessionId, attachments: attachments, onRefresh: onRefresh, onDelete: onDelete })) : ((0, jsx_runtime_1.jsx)("div", { className: "empty-state", children: "Create or select a session before uploading attachments." }))] }));
}
function AttachmentStrip({ attachments, uploading, onDelete }) {
    if (!uploading && attachments.length === 0)
        return null;
    return ((0, jsx_runtime_1.jsxs)("div", { className: "attachment-strip", "aria-live": "polite", children: [uploading ? ((0, jsx_runtime_1.jsxs)("span", { className: "attachment-chip loading", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Paperclip, { size: 14 }), "Uploading"] })) : null, attachments.map((attachment) => ((0, jsx_runtime_1.jsxs)("span", { className: `attachment-chip ${attachment.status}`, title: attachment.text_preview || attachment.error || attachment.stored_filename, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Paperclip, { size: 14 }), (0, jsx_runtime_1.jsxs)("span", { className: "attachment-chip-main", children: [(0, jsx_runtime_1.jsx)("strong", { children: attachment.stored_filename }), (0, jsx_runtime_1.jsxs)("small", { children: [attachment.kind, " \u00B7 ", formatBytes(attachment.size_bytes), " \u00B7 ", attachment.status] })] }), (0, jsx_runtime_1.jsx)("button", { type: "button", onClick: () => onDelete(attachment.attachment_id), title: "Delete attachment", children: (0, jsx_runtime_1.jsx)(lucide_react_1.Trash2, { size: 13 }) })] }, attachment.attachment_id)))] }));
}
function ToolActivityBlock({ item }) {
    const activity = item.activity;
    if (!activity)
        return null;
    const entries = activity.entries || [];
    const commandCount = entries.filter((entry) => entry.kind === "command").length;
    return ((0, jsx_runtime_1.jsxs)("details", { className: `tool-activity ${activity.tone || "success"}`, children: [(0, jsx_runtime_1.jsxs)("summary", { children: [(0, jsx_runtime_1.jsx)("span", { className: "tool-activity-status", children: activity.title }), (0, jsx_runtime_1.jsx)(lucide_react_1.ChevronRight, { size: 14 })] }), (0, jsx_runtime_1.jsxs)("div", { className: "tool-activity-detail", children: [activity.summary ? (0, jsx_runtime_1.jsx)("p", { className: "tool-activity-summary", children: activity.summary }) : null, commandCount > 0 ? (0, jsx_runtime_1.jsxs)("p", { className: "tool-activity-command-count", children: ["\u5DF2\u8FD0\u884C ", commandCount, " \u6761\u547D\u4EE4"] }) : null, entries.length > 0 ? ((0, jsx_runtime_1.jsx)("ol", { className: "tool-activity-steps", children: entries.map((entry) => ((0, jsx_runtime_1.jsxs)("li", { className: `tool-activity-step ${entry.tone || "success"}`, children: [(0, jsx_runtime_1.jsxs)("div", { className: "tool-activity-step-head", children: [(0, jsx_runtime_1.jsx)("span", { children: entry.label }), entry.durationLabel ? (0, jsx_runtime_1.jsx)("small", { children: entry.durationLabel }) : null, entry.tone === "running" ? (0, jsx_runtime_1.jsx)("small", { children: "\u8FD0\u884C\u4E2D" }) : null] }), entry.detail ? (0, jsx_runtime_1.jsx)("pre", { children: entry.detail }) : null, entry.attachments?.length ? (0, jsx_runtime_1.jsx)(rich_text_1.RichMessageAttachments, { attachments: entry.attachments }) : null] }, entry.id))) })) : ((0, jsx_runtime_1.jsx)("pre", { children: activity.detail }))] }), entries.length === 0 ? (0, jsx_runtime_1.jsx)(rich_text_1.RichMessageAttachments, { attachments: item.body.attachments }) : null] }));
}
function ComingSoonPanel({ title, onComingSoon, onReload }) {
    return ((0, jsx_runtime_1.jsxs)("section", { className: "panel-page", children: [(0, jsx_runtime_1.jsxs)("header", { className: "panel-header", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("h2", { children: title }), (0, jsx_runtime_1.jsx)("p", { children: "\u529F\u80FD\u5F00\u53D1\u4E2D\uFF0C\u656C\u8BF7\u671F\u5F85" })] }), (0, jsx_runtime_1.jsxs)("button", { onClick: onReload, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.RefreshCw, { size: 16 }), "\u5237\u65B0"] })] }), (0, jsx_runtime_1.jsxs)("div", { className: "coming-soon", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Sparkles, { size: 28 }), (0, jsx_runtime_1.jsx)("h3", { children: "\u529F\u80FD\u5F00\u53D1\u4E2D\uFF0C\u656C\u8BF7\u671F\u5F85" }), (0, jsx_runtime_1.jsx)("p", { children: "\u8FD9\u4E2A\u9875\u9762\u5DF2\u7ECF\u4FDD\u7559\uFF0C\u540E\u7EED\u4F1A\u7EE7\u7EED\u8865\u9F50\u3002" }), (0, jsx_runtime_1.jsx)("button", { onClick: () => onComingSoon(title), children: "\u63D0\u793A\u4E00\u4E0B" })] })] }));
}
function ObservabilityPanel({ activeSessionId, timeline, activeEvents, onReload }) {
    const [tab, setTab] = (0, react_1.useState)("timeline");
    const [logs, setLogs] = (0, react_1.useState)([]);
    const [sources, setSources] = (0, react_1.useState)([]);
    const [level, setLevel] = (0, react_1.useState)("all");
    const [source, setSource] = (0, react_1.useState)("all");
    const [search, setSearch] = (0, react_1.useState)("");
    const [follow, setFollow] = (0, react_1.useState)(true);
    const [selectedLogKey, setSelectedLogKey] = (0, react_1.useState)("");
    const [error, setError] = (0, react_1.useState)("");
    const liveEvents = activeEvents.map(runtimeEventToTimelineLike);
    const items = latestAgentLoopItems([...timeline, ...liveEvents]);
    const text = formatTimelineText(items);
    async function reloadLogs() {
        try {
            setError("");
            const payload = await api_1.api.logs({ level, source, search, sessionId: activeSessionId || undefined, limit: 300 });
            setLogs(payload.logs);
            setSources(payload.sources);
            if (follow) {
                setSelectedLogKey(payload.logs.length ? logEntryKey(payload.logs[payload.logs.length - 1], payload.logs.length - 1) : "");
            }
            else if (selectedLogKey && !payload.logs.some((entry, index) => logEntryKey(entry, index) === selectedLogKey)) {
                setSelectedLogKey(payload.logs.length ? logEntryKey(payload.logs[Math.min(payload.logs.length - 1, 0)], 0) : "");
            }
        }
        catch (nextError) {
            setError(nextError instanceof Error ? nextError.message : String(nextError));
        }
    }
    (0, react_1.useEffect)(() => {
        if (tab !== "logs")
            return;
        reloadLogs().catch(() => undefined);
    }, [tab, level, source, activeSessionId]);
    (0, react_1.useEffect)(() => {
        if (tab !== "logs" || !follow)
            return;
        const timer = window.setInterval(() => reloadLogs().catch(() => undefined), 2500);
        return () => window.clearInterval(timer);
    }, [tab, follow, level, source, activeSessionId, search]);
    return ((0, jsx_runtime_1.jsxs)("section", { className: "panel-page timeline-page", children: [(0, jsx_runtime_1.jsxs)("header", { className: "panel-header", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("h2", { children: "Observability" }), (0, jsx_runtime_1.jsx)("p", { children: activeSessionId ? `Session ${shortId(activeSessionId)}` : "Recent workspace events and persistent logs" })] }), (0, jsx_runtime_1.jsxs)("div", { className: "segmented-actions", children: [(0, jsx_runtime_1.jsx)("button", { className: tab === "timeline" ? "active" : "", onClick: () => setTab("timeline"), children: "Timeline" }), (0, jsx_runtime_1.jsx)("button", { className: tab === "logs" ? "active" : "", onClick: () => setTab("logs"), children: "Logs" })] })] }), tab === "timeline" ? ((0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsxs)("div", { className: "observability-toolbar", children: [(0, jsx_runtime_1.jsxs)("span", { children: [items.length, " events"] }), (0, jsx_runtime_1.jsxs)("button", { onClick: onReload, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.RefreshCw, { size: 16 }), "Refresh"] })] }), (0, jsx_runtime_1.jsx)("textarea", { className: "timeline-textbox", readOnly: true, value: text || "No recent agent loop timeline events.", "aria-label": "Recent agent loop timeline" })] })) : ((0, jsx_runtime_1.jsx)(LogsPanel, { logs: logs, sources: sources, level: level, source: source, search: search, follow: follow, selectedLogKey: selectedLogKey, error: error, setLevel: setLevel, setSource: setSource, setSearch: setSearch, setFollow: setFollow, setSelectedLogKey: setSelectedLogKey, onReload: reloadLogs }))] }));
}
function LogsPanel({ logs, sources, level, source, search, follow, selectedLogKey, error, setLevel, setSource, setSearch, setFollow, setSelectedLogKey, onReload }) {
    const selectedIndex = Math.max(0, logs.findIndex((entry, index) => logEntryKey(entry, index) === selectedLogKey));
    const selected = logs[Math.min(selectedIndex, Math.max(0, logs.length - 1))];
    return ((0, jsx_runtime_1.jsxs)("div", { className: "logs-workbench", children: [(0, jsx_runtime_1.jsxs)("div", { className: "observability-toolbar logs-toolbar", children: [(0, jsx_runtime_1.jsx)("select", { value: level, onChange: (event) => setLevel(event.target.value), children: ["all", "debug", "info", "warning", "error", "critical"].map((item) => (0, jsx_runtime_1.jsx)("option", { value: item, children: item }, item)) }), (0, jsx_runtime_1.jsxs)("select", { value: source, onChange: (event) => setSource(event.target.value), children: [(0, jsx_runtime_1.jsx)("option", { value: "all", children: "all sources" }), sources.map((item) => (0, jsx_runtime_1.jsx)("option", { value: item, children: item }, item))] }), (0, jsx_runtime_1.jsx)("input", { value: search, onChange: (event) => setSearch(event.target.value), onKeyDown: (event) => event.key === "Enter" && onReload(), placeholder: "Search logs" }), (0, jsx_runtime_1.jsxs)("label", { className: "inline-check", children: [(0, jsx_runtime_1.jsx)("input", { type: "checkbox", checked: follow, onChange: (event) => setFollow(event.target.checked) }), "Follow"] }), (0, jsx_runtime_1.jsxs)("button", { onClick: onReload, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.RefreshCw, { size: 16 }), "Refresh"] })] }), error ? (0, jsx_runtime_1.jsx)("p", { className: "settings-error", children: error }) : null, (0, jsx_runtime_1.jsxs)("div", { className: "logs-grid", children: [(0, jsx_runtime_1.jsx)("div", { className: "log-list", children: logs.length ? logs.map((entry, index) => ((0, jsx_runtime_1.jsxs)("button", { className: logEntryKey(entry, index) === selectedLogKey ? "log-row active" : "log-row", onClick: () => {
                                setFollow(false);
                                setSelectedLogKey(logEntryKey(entry, index));
                            }, children: [(0, jsx_runtime_1.jsx)("span", { children: formatLogTime(entry.timestamp) }), (0, jsx_runtime_1.jsx)("em", { className: `log-level level-${String(entry.level || "info").toLowerCase()}`, children: entry.level || "info" }), (0, jsx_runtime_1.jsx)("strong", { children: entry.source || "log" }), (0, jsx_runtime_1.jsx)("p", { children: entry.message || entry.raw || "" })] }, logEntryKey(entry, index)))) : ((0, jsx_runtime_1.jsxs)("div", { className: "empty-state", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.FileText, { size: 24 }), (0, jsx_runtime_1.jsx)("strong", { children: "No logs match the current filters" }), (0, jsx_runtime_1.jsx)("span", { children: "pp-Echo checked timeline events, session JSONL files, and .pp-agent/logs/*.log and *.jsonl." })] })) }), (0, jsx_runtime_1.jsx)("aside", { className: "log-detail", children: selected ? ((0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsxs)("div", { className: "log-detail-head", children: [(0, jsx_runtime_1.jsx)("strong", { children: selected.source }), (0, jsx_runtime_1.jsx)("span", { className: `log-level level-${String(selected.level || "info").toLowerCase()}`, children: selected.level || "info" })] }), (0, jsx_runtime_1.jsx)("p", { children: selected.message }), (0, jsx_runtime_1.jsx)("pre", { children: JSON.stringify({ timestamp: selected.timestamp, session_id: selected.session_id, details: selected.details, raw: selected.raw }, null, 2) }), (0, jsx_runtime_1.jsx)("button", { onClick: () => navigator.clipboard?.writeText(selected.raw || selected.message || ""), children: "Copy" })] })) : ((0, jsx_runtime_1.jsx)("span", { children: "Select a log row to inspect details." })) })] })] }));
}
function logEntryKey(entry, index) {
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
    const [status, setStatus] = (0, react_1.useState)(null);
    const [corePending, setCorePending] = (0, react_1.useState)([]);
    const [coreActive, setCoreActive] = (0, react_1.useState)([]);
    const [coreSnapshot, setCoreSnapshot] = (0, react_1.useState)(null);
    const [coreAudit, setCoreAudit] = (0, react_1.useState)([]);
    const [selectedCoreId, setSelectedCoreId] = (0, react_1.useState)("");
    const [providerStatus, setProviderStatus] = (0, react_1.useState)(null);
    const [automationResult, setAutomationResult] = (0, react_1.useState)(null);
    const [selectedPath, setSelectedPath] = (0, react_1.useState)("");
    const [selectedFile, setSelectedFile] = (0, react_1.useState)(null);
    const [query, setQuery] = (0, react_1.useState)("");
    const [scope, setScope] = (0, react_1.useState)("auto");
    const [searchResult, setSearchResult] = (0, react_1.useState)(null);
    const [loading, setLoading] = (0, react_1.useState)(false);
    const [error, setError] = (0, react_1.useState)("");
    const files = status?.files || [];
    async function reload() {
        try {
            setError("");
            const [nextStatus, pendingPayload, activePayload, snapshotPayload, auditPayload, providerPayload] = await Promise.all([
                api_1.api.memoryStatus(),
                api_1.api.coreMemoryPending(),
                api_1.api.coreMemoryActive(),
                api_1.api.coreMemorySnapshot(),
                api_1.api.coreMemoryAudit(selectedCoreId || undefined, 80),
                api_1.api.coreMemoryProviderStatus()
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
                setSelectedFile(await api_1.api.memoryFile(nextPath, 1, 220));
            }
            else {
                setSelectedFile(null);
            }
        }
        catch (nextError) {
            setError(nextError instanceof Error ? nextError.message : String(nextError));
        }
    }
    async function refreshCore(memoryId = selectedCoreId) {
        const [pendingPayload, activePayload, snapshotPayload, auditPayload] = await Promise.all([
            api_1.api.coreMemoryPending(),
            api_1.api.coreMemoryActive(),
            api_1.api.coreMemorySnapshot(),
            api_1.api.coreMemoryAudit(memoryId || undefined, 80)
        ]);
        setCorePending(pendingPayload.pending);
        setCoreActive(activePayload.active);
        setCoreSnapshot(snapshotPayload);
        setCoreAudit(auditPayload.audit);
    }
    async function actOnCoreMemory(action, memoryId) {
        try {
            setError("");
            if (action === "approve")
                await api_1.api.approveCoreMemory(memoryId);
            if (action === "reject")
                await api_1.api.rejectCoreMemory(memoryId);
            if (action === "archive")
                await api_1.api.archiveCoreMemory(memoryId);
            setSelectedCoreId(memoryId);
            await refreshCore(memoryId);
        }
        catch (nextError) {
            setError(nextError instanceof Error ? nextError.message : String(nextError));
        }
    }
    async function runAutomation(action) {
        try {
            setError("");
            const result = action === "merge-preview" ? await api_1.api.coreMemoryMergePreview()
                : action === "merge-apply" ? await api_1.api.coreMemoryMergeApply()
                    : action === "compact-preview" ? await api_1.api.coreMemoryCompactPreview()
                        : await api_1.api.coreMemoryCompactApply();
            setAutomationResult(result);
            await refreshCore();
            setProviderStatus(await api_1.api.coreMemoryProviderStatus());
        }
        catch (nextError) {
            setError(nextError instanceof Error ? nextError.message : String(nextError));
        }
    }
    async function readFile(path, startLine = 1) {
        try {
            setError("");
            setSelectedPath(path);
            setSelectedFile(await api_1.api.memoryFile(path, startLine, 220));
        }
        catch (nextError) {
            setError(nextError instanceof Error ? nextError.message : String(nextError));
        }
    }
    async function searchMemory() {
        if (!query.trim())
            return;
        try {
            setLoading(true);
            setError("");
            setSearchResult(await api_1.api.memorySearch(query.trim(), scope, 8));
        }
        catch (nextError) {
            setError(nextError instanceof Error ? nextError.message : String(nextError));
        }
        finally {
            setLoading(false);
        }
    }
    (0, react_1.useEffect)(() => {
        reload().catch(() => undefined);
    }, []);
    return ((0, jsx_runtime_1.jsxs)("section", { className: "panel-page memory-page", children: [(0, jsx_runtime_1.jsxs)("header", { className: "panel-header memory-header", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("h2", { children: "Memory" }), (0, jsx_runtime_1.jsx)("p", { children: status?.memory_root || "Long-term Markdown memory" })] }), (0, jsx_runtime_1.jsxs)("button", { onClick: reload, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.RefreshCw, { size: 16 }), "Refresh"] })] }), error ? (0, jsx_runtime_1.jsx)("p", { className: "settings-error", children: error }) : null, (0, jsx_runtime_1.jsxs)("div", { className: "memory-stats", children: [(0, jsx_runtime_1.jsx)(MemoryStat, { label: "Episodic memory", value: (status?.episodic_memory_enabled ?? status?.enabled) ? "enabled" : "disabled" }), (0, jsx_runtime_1.jsx)(MemoryStat, { label: "Core memory", value: (status?.core_memory_enabled ?? true) ? "enabled" : "disabled" }), (0, jsx_runtime_1.jsx)(MemoryStat, { label: "Core pending", value: `${corePending.length}` }), (0, jsx_runtime_1.jsx)(MemoryStat, { label: "Core active", value: `${coreActive.length}` }), (0, jsx_runtime_1.jsx)(MemoryStat, { label: "Snapshot", value: `${coreSnapshot?.chars || 0} chars` }), (0, jsx_runtime_1.jsx)(MemoryStat, { label: "Provider", value: String(providerStatus?.provider || "unknown") }), (0, jsx_runtime_1.jsx)(MemoryStat, { label: "File memory", value: status?.file_memory_enabled ? "enabled" : "disabled" }), (0, jsx_runtime_1.jsx)(MemoryStat, { label: "Search", value: status?.search_enabled ? "enabled" : "disabled" }), (0, jsx_runtime_1.jsx)(MemoryStat, { label: "Files", value: `${status?.file_count || 0} files / ${status?.indexed_file_count || 0} indexed` })] }), (0, jsx_runtime_1.jsxs)("div", { className: "core-memory-layout", children: [(0, jsx_runtime_1.jsxs)("section", { className: "core-memory-column", children: [(0, jsx_runtime_1.jsxs)("div", { className: "capability-list-head", children: [(0, jsx_runtime_1.jsx)("span", { children: "Pending" }), (0, jsx_runtime_1.jsx)("button", { onClick: () => reload(), children: "Reload" })] }), (0, jsx_runtime_1.jsx)(CoreMemoryList, { memories: corePending, empty: "No pending candidates.", selectedId: selectedCoreId, onSelect: (id) => {
                                    setSelectedCoreId(id);
                                    api_1.api.coreMemoryAudit(id, 80).then((payload) => setCoreAudit(payload.audit)).catch(() => undefined);
                                }, actions: (memory) => ((0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsx)("button", { onClick: () => actOnCoreMemory("approve", memory.id), children: (0, jsx_runtime_1.jsx)(lucide_react_1.Check, { size: 14 }) }), (0, jsx_runtime_1.jsx)("button", { onClick: () => actOnCoreMemory("reject", memory.id), children: (0, jsx_runtime_1.jsx)(lucide_react_1.X, { size: 14 }) })] })) })] }), (0, jsx_runtime_1.jsxs)("section", { className: "core-memory-column", children: [(0, jsx_runtime_1.jsx)("div", { className: "capability-list-head", children: (0, jsx_runtime_1.jsx)("span", { children: "Active" }) }), (0, jsx_runtime_1.jsx)(CoreMemoryList, { memories: coreActive, empty: "No active core memory.", selectedId: selectedCoreId, onSelect: (id) => {
                                    setSelectedCoreId(id);
                                    api_1.api.coreMemoryAudit(id, 80).then((payload) => setCoreAudit(payload.audit)).catch(() => undefined);
                                }, actions: (memory) => ((0, jsx_runtime_1.jsx)("button", { onClick: () => actOnCoreMemory("archive", memory.id), children: (0, jsx_runtime_1.jsx)(lucide_react_1.Trash2, { size: 14 }) })) })] }), (0, jsx_runtime_1.jsxs)("section", { className: "core-memory-column core-memory-preview", children: [(0, jsx_runtime_1.jsxs)("div", { className: "capability-list-head", children: [(0, jsx_runtime_1.jsx)("span", { children: "Snapshot" }), (0, jsx_runtime_1.jsx)("small", { children: coreSnapshot?.snapshot_hash ? coreSnapshot.snapshot_hash.slice(0, 10) : "not frozen" })] }), (0, jsx_runtime_1.jsx)("pre", { children: coreSnapshot?.snapshot || "No active core memory will be injected." }), coreSnapshot?.skipped_ids?.length ? (0, jsx_runtime_1.jsxs)("p", { className: "muted", children: ["Skipped: ", coreSnapshot.skipped_ids.join(", ")] }) : null] }), (0, jsx_runtime_1.jsxs)("section", { className: "core-memory-column", children: [(0, jsx_runtime_1.jsxs)("div", { className: "capability-list-head", children: [(0, jsx_runtime_1.jsx)("span", { children: "Audit" }), (0, jsx_runtime_1.jsx)("small", { children: selectedCoreId ? shortId(selectedCoreId) : "all" })] }), (0, jsx_runtime_1.jsx)("div", { className: "core-audit-list", children: coreAudit.length ? coreAudit.map((record) => ((0, jsx_runtime_1.jsxs)("div", { className: "core-audit-row", children: [(0, jsx_runtime_1.jsx)("strong", { children: record.action }), (0, jsx_runtime_1.jsx)("span", { children: `${record.before_status || "-"} -> ${record.after_status || "-"}` }), (0, jsx_runtime_1.jsx)("p", { children: record.reason || record.actor })] }, record.audit_id))) : (0, jsx_runtime_1.jsx)("p", { className: "muted", children: "No audit records." }) })] })] }), (0, jsx_runtime_1.jsxs)("div", { className: "core-automation-bar", children: [(0, jsx_runtime_1.jsx)("button", { onClick: () => runAutomation("merge-preview"), children: "Merge preview" }), (0, jsx_runtime_1.jsx)("button", { onClick: () => runAutomation("merge-apply"), children: "Merge apply" }), (0, jsx_runtime_1.jsx)("button", { onClick: () => runAutomation("compact-preview"), children: "Compact preview" }), (0, jsx_runtime_1.jsx)("button", { onClick: () => runAutomation("compact-apply"), children: "Compact apply" }), (0, jsx_runtime_1.jsxs)("span", { children: ["Provider writes: ", String(providerStatus?.mirrored_write_count ?? 0), " / turns: ", String(providerStatus?.synced_turn_count ?? 0)] })] }), automationResult ? (0, jsx_runtime_1.jsx)("pre", { className: "core-automation-result", children: JSON.stringify(automationResult, null, 2) }) : null, (0, jsx_runtime_1.jsxs)("div", { className: "memory-layout", children: [(0, jsx_runtime_1.jsxs)("aside", { className: "memory-sidebar", children: [(0, jsx_runtime_1.jsxs)("div", { className: "memory-searchbar", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Search, { size: 15 }), (0, jsx_runtime_1.jsx)("input", { value: query, onChange: (event) => setQuery(event.target.value), onKeyDown: (event) => event.key === "Enter" && searchMemory(), placeholder: "Search memory" }), (0, jsx_runtime_1.jsxs)("select", { value: scope, onChange: (event) => setScope(event.target.value), children: [(0, jsx_runtime_1.jsx)("option", { value: "auto", children: "auto" }), (0, jsx_runtime_1.jsx)("option", { value: "workspace", children: "workspace" }), (0, jsx_runtime_1.jsx)("option", { value: "global", children: "global" }), (0, jsx_runtime_1.jsx)("option", { value: "all", children: "all" })] }), (0, jsx_runtime_1.jsx)("button", { onClick: searchMemory, disabled: !query.trim() || loading, children: loading ? "Searching" : "Search" })] }), (0, jsx_runtime_1.jsxs)("div", { className: "memory-results", children: [searchResult?.warnings?.map((warning) => (0, jsx_runtime_1.jsx)("p", { className: "settings-error", children: warning }, warning)), searchResult?.results?.map((hit) => ((0, jsx_runtime_1.jsxs)("button", { className: "memory-hit", onClick: () => readFile(hit.path, hit.line_start), children: [(0, jsx_runtime_1.jsx)("strong", { children: hit.path }), (0, jsx_runtime_1.jsxs)("span", { children: [hit.source_scope, " \u00B7 lines ", hit.line_start, "-", hit.line_end, " \u00B7 ", hit.score.toFixed(2)] }), (0, jsx_runtime_1.jsx)("p", { children: hit.snippet })] }, `${hit.path}-${hit.line_start}`)))] }), (0, jsx_runtime_1.jsxs)("div", { className: "memory-file-list", children: [(0, jsx_runtime_1.jsx)("div", { className: "capability-list-head", children: (0, jsx_runtime_1.jsxs)("span", { children: [files.length, " memory files"] }) }), files.map((file) => ((0, jsx_runtime_1.jsxs)("button", { className: selectedPath === file.path ? "memory-file-row active" : "memory-file-row", onClick: () => readFile(file.path), children: [(0, jsx_runtime_1.jsx)("strong", { children: file.path }), (0, jsx_runtime_1.jsxs)("span", { children: [file.scope, " \u00B7 ", formatBytes(file.size)] })] }, file.path)))] })] }), (0, jsx_runtime_1.jsx)("div", { className: "memory-reader", children: selectedFile ? ((0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsxs)("div", { className: "memory-reader-head", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsxs)("small", { children: [selectedFile.line_start, "-", selectedFile.line_end] }), (0, jsx_runtime_1.jsx)("h3", { children: selectedFile.path })] }), (0, jsx_runtime_1.jsx)("span", { children: status?.index_path || "" })] }), (0, jsx_runtime_1.jsx)("pre", { children: selectedFile.content || "This memory file is empty." })] })) : ((0, jsx_runtime_1.jsxs)("div", { className: "empty-state", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.BookOpen, { size: 24 }), (0, jsx_runtime_1.jsx)("strong", { children: "No memory files found" }), (0, jsx_runtime_1.jsx)("span", { children: "Create MEMORY.md or memory/**/*.md to populate this view." })] })) })] })] }));
}
function MemoryStat({ label, value }) {
    return ((0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("span", { children: label }), (0, jsx_runtime_1.jsx)("strong", { children: value })] }));
}
function CoreMemoryList({ memories, empty, selectedId, onSelect, actions }) {
    if (!memories.length)
        return (0, jsx_runtime_1.jsx)("div", { className: "core-memory-list", children: (0, jsx_runtime_1.jsx)("p", { className: "muted", children: empty }) });
    return ((0, jsx_runtime_1.jsx)("div", { className: "core-memory-list", children: memories.map((memory) => ((0, jsx_runtime_1.jsxs)("article", { className: selectedId === memory.id ? "core-memory-item active" : "core-memory-item", children: [(0, jsx_runtime_1.jsxs)("button", { className: "core-memory-main", onClick: () => onSelect(memory.id), children: [(0, jsx_runtime_1.jsxs)("span", { className: "core-memory-meta", children: [memory.scope, "/", memory.section, "/", memory.type] }), (0, jsx_runtime_1.jsx)("strong", { className: "core-memory-content", children: memory.content }), (0, jsx_runtime_1.jsxs)("small", { children: [shortId(memory.id), " \u00B7 confidence ", memory.confidence.toFixed(2)] })] }), (0, jsx_runtime_1.jsx)("div", { className: "core-memory-actions", children: actions(memory) })] }, memory.id))) }));
}
function CapabilityWorkbench({ initialTab, workspaceStatus, activeSessionId }) {
    const [tab, setTab] = (0, react_1.useState)(initialTab);
    const [inventory, setInventory] = (0, react_1.useState)(null);
    const [snapshot, setSnapshot] = (0, react_1.useState)(null);
    const [selectedName, setSelectedName] = (0, react_1.useState)("");
    const [draft, setDraft] = (0, react_1.useState)({});
    const [settingsDraft, setSettingsDraft] = (0, react_1.useState)({});
    const [drawerMode, setDrawerMode] = (0, react_1.useState)("none");
    const [notice, setNotice] = (0, react_1.useState)("");
    const [error, setError] = (0, react_1.useState)("");
    const [query, setQuery] = (0, react_1.useState)("");
    const items = capabilityItems(inventory, tab);
    const filteredItems = items.filter((item) => capabilityMatchesQuery(item, query));
    const selected = selectedName ? items.find((item) => String(item.name || "") === selectedName) : undefined;
    const governanceSummary = capabilityGovernanceSummary(inventory, tab);
    async function reload() {
        const [nextInventory, nextSnapshot] = await Promise.all([api_1.api.capabilityConfig(), api_1.api.config(activeSessionId || undefined)]);
        setInventory(nextInventory);
        setSnapshot(nextSnapshot);
        const nextItems = capabilityItems(nextInventory, tab);
        if (!selectedName && nextItems[0])
            setSelectedName(String(nextItems[0].name || ""));
        setSettingsDraft(capabilitySettingsToDraft(nextInventory, tab));
    }
    (0, react_1.useEffect)(() => {
        setTab(initialTab);
    }, [initialTab]);
    (0, react_1.useEffect)(() => {
        reload().catch((nextError) => setError(nextError instanceof Error ? nextError.message : String(nextError)));
    }, [tab, activeSessionId]);
    (0, react_1.useEffect)(() => {
        setDraft(capabilityItemToDraft(selected, tab));
    }, [selectedName, tab, inventory]);
    (0, react_1.useEffect)(() => {
        if (tab !== "skills" || !selectedName || !selected || selected.body_materialized)
            return;
        let cancelled = false;
        api_1.api.getSkill(selectedName)
            .then((detail) => {
            if (cancelled)
                return;
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
            const response = await api_1.api.capabilitySettingsPatch({ [tab]: patch });
            setInventory(response.inventory);
            setSnapshot(response.snapshot);
            setNotice("Settings applied.");
        }
        catch (nextError) {
            setError(nextError instanceof Error ? nextError.message : String(nextError));
        }
    }
    async function saveItem() {
        try {
            setError("");
            const payload = capabilityPayloadFromDraft(draft, tab);
            let nextInventory;
            if (tab === "mcp") {
                nextInventory = selected ? await api_1.api.updateMcpServer(String(selected.name), payload) : await api_1.api.createMcpServer(payload);
            }
            else if (tab === "skills") {
                nextInventory = selected ? await api_1.api.updateSkill(String(selected.name), payload) : await api_1.api.createSkill(payload);
            }
            else {
                nextInventory = selected ? await api_1.api.updatePlugin(String(selected.name), payload) : await api_1.api.createPlugin(payload);
            }
            setInventory(nextInventory);
            setSelectedName(String(payload.name || ""));
            setDrawerMode("edit");
            setNotice("Saved.");
        }
        catch (nextError) {
            setError(nextError instanceof Error ? nextError.message : String(nextError));
        }
    }
    async function deleteMcp() {
        if (tab !== "mcp" || !selected)
            return;
        if (!window.confirm(`Delete MCP server "${String(selected.name)}"? This removes the server from workspace capability configuration.`))
            return;
        try {
            const nextInventory = await api_1.api.deleteMcpServer(String(selected.name));
            setInventory(nextInventory);
            setSelectedName("");
            setDrawerMode("none");
            setNotice("Deleted.");
        }
        catch (nextError) {
            setError(nextError instanceof Error ? nextError.message : String(nextError));
        }
    }
    function newItem() {
        setSelectedName("");
        setDraft(capabilityItemToDraft(null, tab));
        setDrawerMode("edit");
    }
    return ((0, jsx_runtime_1.jsxs)("section", { className: "panel-page capability-page", children: [(0, jsx_runtime_1.jsxs)("header", { className: "panel-header", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("h2", { children: "Capability Workbench" }), (0, jsx_runtime_1.jsx)("p", { children: workspaceStatus?.path || inventory?.workspace || "Workspace capability configuration" })] }), (0, jsx_runtime_1.jsxs)("div", { className: "capability-meta", children: [(0, jsx_runtime_1.jsx)("span", { children: workspaceStatus?.git_branch || "no branch" }), (0, jsx_runtime_1.jsx)("span", { children: snapshot?.effective_hash ? snapshot.effective_hash.slice(0, 10) : "hash pending" }), (0, jsx_runtime_1.jsx)("span", { className: `reload-badge reload-${snapshot?.reload_policy || "hot"}`, children: snapshot?.reload_policy || "hot" }), (0, jsx_runtime_1.jsxs)("span", { children: [governanceSummary.total, " governed"] }), (0, jsx_runtime_1.jsxs)("span", { children: [governanceSummary.currentTab, " ", governanceSummary.label] }), (0, jsx_runtime_1.jsx)("span", { children: governanceSummary.risk })] })] }), (0, jsx_runtime_1.jsx)("div", { className: "segmented-actions capability-tabs", children: ["mcp", "skills", "plugins"].map((item) => ((0, jsx_runtime_1.jsx)("button", { className: tab === item ? "active" : "", onClick: () => { setTab(item); setSelectedName(""); }, children: item.toUpperCase() }, item))) }), error ? (0, jsx_runtime_1.jsx)("p", { className: "settings-error", children: error }) : null, notice ? (0, jsx_runtime_1.jsx)("p", { className: "settings-success", children: notice }) : null, (0, jsx_runtime_1.jsxs)("div", { className: "capability-toolbar", children: [(0, jsx_runtime_1.jsxs)("label", { className: "capability-search", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Search, { size: 14 }), (0, jsx_runtime_1.jsx)("input", { value: query, onChange: (event) => setQuery(event.target.value), placeholder: `Search ${tab}` })] }), (0, jsx_runtime_1.jsxs)("button", { onClick: () => reload(), children: [(0, jsx_runtime_1.jsx)(lucide_react_1.RefreshCw, { size: 14 }), " Reload"] }), (0, jsx_runtime_1.jsxs)("button", { onClick: () => setDrawerMode("settings"), children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Settings, { size: 14 }), " Settings"] }), (0, jsx_runtime_1.jsxs)("button", { onClick: newItem, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Plus, { size: 14 }), " New"] })] }), (0, jsx_runtime_1.jsxs)("div", { className: "capability-layout", children: [(0, jsx_runtime_1.jsxs)("div", { className: "capability-grid", children: [filteredItems.map((item) => ((0, jsx_runtime_1.jsxs)("button", { className: String(item.name) === String(selected?.name || "") ? "capability-card active" : "capability-card", title: String(item.description || item.path || item.resolved_transport || ""), onClick: () => { setSelectedName(String(item.name || "")); setDrawerMode("edit"); }, type: "button", children: [(0, jsx_runtime_1.jsx)("span", { className: `capability-card-initials capability-card-initials-${tab}`, children: capabilityInitials(item, tab) }), (0, jsx_runtime_1.jsxs)("span", { className: "capability-card-body", children: [(0, jsx_runtime_1.jsxs)("span", { className: "capability-card-top", children: [(0, jsx_runtime_1.jsx)("span", { children: tab.toUpperCase() }), (0, jsx_runtime_1.jsx)("em", { children: capabilityStatus(item, tab) })] }), (0, jsx_runtime_1.jsx)("strong", { children: String(item.name || "unnamed") }), (0, jsx_runtime_1.jsx)("p", { children: String(item.description || item.path || item.entrypoint || item.command || "No description yet.") }), (0, jsx_runtime_1.jsx)("span", { className: "capability-card-meta", children: capabilityMeta(item, tab).map((meta) => (0, jsx_runtime_1.jsx)("span", { children: meta }, meta)) })] }), (0, jsx_runtime_1.jsx)("span", { className: "capability-card-menu", "aria-hidden": "true", children: "\u22EE" })] }, String(item.name)))), items.length === 0 ? (0, jsx_runtime_1.jsxs)("div", { className: "capability-empty", children: ["No ", tab, " resources configured yet."] }) : null, items.length > 0 && filteredItems.length === 0 ? (0, jsx_runtime_1.jsxs)("div", { className: "capability-empty", children: ["No ", tab, " resources match this search."] }) : null] }), drawerMode !== "none" ? ((0, jsx_runtime_1.jsx)("div", { className: "capability-drawer-backdrop", onClick: () => setDrawerMode("none"), children: (0, jsx_runtime_1.jsx)("aside", { className: "capability-drawer", onClick: (event) => event.stopPropagation(), children: drawerMode === "settings" ? ((0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsxs)("div", { className: "capability-editor-head", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("small", { children: "SETTINGS" }), (0, jsx_runtime_1.jsxs)("h3", { children: [tab.toUpperCase(), " settings"] }), (0, jsx_runtime_1.jsx)("p", { children: snapshot?.pending_effects?.slice(0, 3).join(", ") || `${snapshot?.reload_policy || "hot"} reload policy` })] }), (0, jsx_runtime_1.jsxs)("div", { className: "capability-editor-actions", children: [(0, jsx_runtime_1.jsx)("button", { onClick: () => setSettingsDraft(capabilitySettingsToDraft(inventory, tab)), disabled: !inventory, children: "Revert" }), (0, jsx_runtime_1.jsx)("button", { className: "primary", onClick: applySettings, children: "Apply" }), (0, jsx_runtime_1.jsx)("button", { onClick: () => setDrawerMode("none"), children: (0, jsx_runtime_1.jsx)(lucide_react_1.X, { size: 14 }) })] })] }), (0, jsx_runtime_1.jsx)("div", { className: "capability-settings-card drawer", children: renderCapabilitySettings(settingsDraft, setSettingsDraft, tab) })] })) : ((0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsxs)("div", { className: "capability-editor-head", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("small", { children: selected ? "EDIT" : "CREATE" }), (0, jsx_runtime_1.jsx)("h3", { children: selected ? String(selected.name) : `New ${tab.slice(0, -1)}` })] }), (0, jsx_runtime_1.jsxs)("div", { className: "capability-editor-actions", children: [tab === "mcp" && selected ? (0, jsx_runtime_1.jsx)("button", { onClick: deleteMcp, children: "Delete" }) : null, (0, jsx_runtime_1.jsx)("button", { onClick: () => setDraft(capabilityItemToDraft(selected, tab)), children: "Revert" }), (0, jsx_runtime_1.jsx)("button", { className: "primary", onClick: saveItem, children: "Apply" }), (0, jsx_runtime_1.jsx)("button", { onClick: () => setDrawerMode("none"), children: (0, jsx_runtime_1.jsx)(lucide_react_1.X, { size: 14 }) })] })] }), renderCapabilityEditor(tab, draft, setDraft)] })) }) })) : null] })] }));
}
function capabilityItems(inventory, tab) {
    if (!inventory)
        return [];
    if (tab === "mcp")
        return inventory.mcp.servers;
    return inventory[tab].items;
}
function capabilityGovernanceSummary(inventory, tab) {
    const snapshot = inventory?.capabilities;
    const items = snapshot?.items || [];
    const total = Number(snapshot?.count || items.length || 0);
    const kinds = capabilityGovernanceKinds(tab);
    const discoveredCount = kinds.reduce((count, kind) => count + Number(snapshot?.by_kind?.[kind] || 0), 0);
    const staticMcpCount = tab === "mcp" ? Number(inventory?.mcp?.servers?.length || 0) : 0;
    const currentTab = discoveredCount || staticMcpCount;
    const riskCounts = items.reduce((counts, item) => {
        const kind = String(item.kind || "");
        if (!kinds.includes(kind))
            return counts;
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
function capabilityGovernanceKinds(tab) {
    if (tab === "mcp")
        return ["mcp_tool", "mcp_resource", "mcp_prompt"];
    if (tab === "skills")
        return ["skill"];
    return ["runtime_adapter", "extension"];
}
function capabilityGovernanceLabel(tab) {
    if (tab === "mcp")
        return "MCP capabilities";
    if (tab === "skills")
        return "skill capabilities";
    return "plugin capabilities";
}
function capabilityMatchesQuery(item, query) {
    const text = query.trim().toLowerCase();
    if (!text)
        return true;
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
function capabilityStatus(item, tab) {
    if (item.enabled === false)
        return "disabled";
    if (tab === "mcp")
        return String(item.resolved_transport || item.transport || "server");
    if (tab === "skills")
        return String(item.source || "skill");
    return String(item.entrypoint ? "configured" : "plugin");
}
function capabilityInitials(item, tab) {
    const fallback = tab === "mcp" ? "MC" : tab === "skills" ? "SK" : "PL";
    const name = String(item.name || "").trim();
    if (!name)
        return fallback;
    const parts = name.split(/[\s._/-]+/).filter(Boolean);
    if (parts.length >= 2)
        return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
    return name.slice(0, 2).toUpperCase();
}
function capabilityMeta(item, tab) {
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
function capabilitySettingsToDraft(inventory, tab) {
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
function capabilitySettingsFromDraft(draft, tab) {
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
function capabilityItemToDraft(item, tab) {
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
function capabilityPayloadFromDraft(draft, tab) {
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
    if (tab === "skills")
        return { name: draft.name, description: draft.description, body: draft.body };
    return { name: draft.name, description: draft.description, entrypoint: draft.entrypoint || null, provides: parseLines(draft.provides) };
}
function renderCapabilitySettings(draft, setDraft, tab) {
    const update = (key, value) => setDraft({ ...draft, [key]: value });
    if (tab === "mcp") {
        return ((0, jsx_runtime_1.jsxs)("div", { className: "capability-settings-fields", children: [(0, jsx_runtime_1.jsxs)("label", { className: "settings-toggle", children: [(0, jsx_runtime_1.jsx)("input", { type: "checkbox", checked: draft.enable === "true", onChange: (event) => update("enable", String(event.target.checked)) }), " Enabled"] }), (0, jsx_runtime_1.jsxs)("label", { children: [(0, jsx_runtime_1.jsx)("span", { children: "Config paths" }), (0, jsx_runtime_1.jsx)("textarea", { value: draft.config_paths || "", onChange: (event) => update("config_paths", event.target.value) })] }), (0, jsx_runtime_1.jsxs)("label", { children: [(0, jsx_runtime_1.jsx)("span", { children: "Server filters" }), (0, jsx_runtime_1.jsx)("textarea", { value: draft.server_filters || "", onChange: (event) => update("server_filters", event.target.value) })] })] }));
    }
    return ((0, jsx_runtime_1.jsxs)("div", { className: "capability-settings-fields", children: [["enable_project", "enable_user", "enable_builtin"].map((key) => ((0, jsx_runtime_1.jsxs)("label", { className: "settings-toggle", children: [(0, jsx_runtime_1.jsx)("input", { type: "checkbox", checked: draft[key] === "true", onChange: (event) => update(key, String(event.target.checked)) }), " ", key] }, key))), (0, jsx_runtime_1.jsxs)("label", { children: [(0, jsx_runtime_1.jsx)("span", { children: "Custom directories" }), (0, jsx_runtime_1.jsx)("textarea", { value: draft.custom_directories || "", onChange: (event) => update("custom_directories", event.target.value) })] }), (0, jsx_runtime_1.jsxs)("label", { children: [(0, jsx_runtime_1.jsx)("span", { children: "Include" }), (0, jsx_runtime_1.jsx)("textarea", { value: draft.include || "", onChange: (event) => update("include", event.target.value) })] }), (0, jsx_runtime_1.jsxs)("label", { children: [(0, jsx_runtime_1.jsx)("span", { children: "Ignored" }), (0, jsx_runtime_1.jsx)("textarea", { value: draft.ignored || "", onChange: (event) => update("ignored", event.target.value) })] })] }));
}
function renderCapabilityEditor(tab, draft, setDraft) {
    const update = (key, value) => setDraft({ ...draft, [key]: value });
    const field = (key, label, multiline = false) => ((0, jsx_runtime_1.jsxs)("label", { className: "capability-field", children: [(0, jsx_runtime_1.jsx)("span", { children: label }), multiline ? (0, jsx_runtime_1.jsx)("textarea", { value: draft[key] || "", onChange: (event) => update(key, event.target.value) }) : (0, jsx_runtime_1.jsx)("input", { value: draft[key] || "", onChange: (event) => update(key, event.target.value) })] }));
    if (tab === "mcp") {
        return ((0, jsx_runtime_1.jsxs)("div", { className: "capability-form", children: [field("name", "Name"), field("description", "Description"), (0, jsx_runtime_1.jsxs)("label", { className: "capability-field", children: [(0, jsx_runtime_1.jsx)("span", { children: "Transport" }), (0, jsx_runtime_1.jsxs)("select", { value: draft.transport || "stdio", onChange: (event) => update("transport", event.target.value), children: [(0, jsx_runtime_1.jsx)("option", { value: "stdio", children: "stdio" }), (0, jsx_runtime_1.jsx)("option", { value: "http", children: "http" }), (0, jsx_runtime_1.jsx)("option", { value: "auto", children: "auto" })] })] }), (0, jsx_runtime_1.jsxs)("label", { className: "capability-field", children: [(0, jsx_runtime_1.jsx)("span", { children: "Protocol" }), (0, jsx_runtime_1.jsxs)("select", { value: draft.protocol || "auto", onChange: (event) => update("protocol", event.target.value), children: [(0, jsx_runtime_1.jsx)("option", { value: "auto", children: "auto" }), (0, jsx_runtime_1.jsx)("option", { value: "standard", children: "standard" }), (0, jsx_runtime_1.jsx)("option", { value: "compat", children: "compat" })] })] }), field("command", "Command"), field("args", "Args", true), field("url", "URL"), field("cwd", "CWD"), field("env", "Env JSON", true), field("headers", "Headers JSON", true), field("bearer_token_env", "Bearer token env"), field("timeout_seconds", "Timeout seconds")] }));
    }
    if (tab === "skills") {
        return (0, jsx_runtime_1.jsxs)("div", { className: "capability-form", children: [field("name", "Name"), field("description", "Description"), field("body", "Skill body", true)] });
    }
    return (0, jsx_runtime_1.jsxs)("div", { className: "capability-form", children: [field("name", "Name"), field("description", "Description"), field("entrypoint", "Entrypoint"), field("provides", "Provides", true)] });
}
function stringifyList(value) {
    return Array.isArray(value) ? value.map(String).join("\n") : "";
}
function parseLines(value) {
    return String(value || "").split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean);
}
function stringifyJson(value) {
    return JSON.stringify(value || {}, null, 2);
}
function parseJsonObject(value) {
    const text = String(value || "").trim();
    if (!text)
        return {};
    const parsed = JSON.parse(text);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
        throw new Error("Expected a JSON object");
    return parsed;
}
function formatEventTime(value) {
    if (!value)
        return "--:--:--";
    return new Date(value * 1000).toLocaleTimeString();
}
function formatLogTime(value) {
    if (!value)
        return "--:--:--";
    const date = typeof value === "number" ? new Date(value > 10000000000 ? value : value * 1000) : new Date(value);
    if (Number.isNaN(date.getTime()))
        return String(value);
    return date.toLocaleTimeString();
}
function formatBytes(value) {
    const size = Number(value || 0);
    if (size < 1024)
        return `${size} B`;
    if (size < 1024 * 1024)
        return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / 1024 / 1024).toFixed(1)} MB`;
}
function latestAgentLoopItems(items) {
    const sorted = [...items]
        .filter((item) => item.created_at || item.event_type)
        .sort((left, right) => (left.created_at || 0) - (right.created_at || 0));
    const start = findLastIndex(sorted, (item) => item.event_type === "agent_start" || item.event_type === "local_user_prompt");
    return sorted.slice(Math.max(0, start)).slice(-160);
}
function runtimeEventToTimelineLike(event, index) {
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
function formatTimelineText(items) {
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
function WorkspaceDialog({ currentPath, value, pendingWorkspace, onChange, onClose, onOpen, onOpenPath, onConfirm }) {
    const canPickDirectory = typeof window.showDirectoryPicker === "function";
    const [pickerHint, setPickerHint] = (0, react_1.useState)("");
    const [pickingDirectory, setPickingDirectory] = (0, react_1.useState)(false);
    async function pickDirectory() {
        setPickingDirectory(true);
        try {
            const response = await api_1.api.pickWorkspaceDirectory();
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
        }
        catch (error) {
            setPickerHint(error instanceof Error ? error.message : String(error));
        }
        finally {
            setPickingDirectory(false);
        }
        const picker = window.showDirectoryPicker;
        if (!picker)
            return;
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
    return ((0, jsx_runtime_1.jsx)("div", { className: "workspace-dialog-backdrop", role: "presentation", onMouseDown: onClose, children: (0, jsx_runtime_1.jsxs)("section", { className: "workspace-dialog", role: "dialog", "aria-modal": "true", "aria-label": "\u9009\u62E9\u5DE5\u4F5C\u533A", onMouseDown: (event) => event.stopPropagation(), children: [(0, jsx_runtime_1.jsxs)("header", { children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("small", { children: "WORKSPACE" }), (0, jsx_runtime_1.jsx)("h2", { children: "\u9009\u62E9\u5DE5\u4F5C\u533A" })] }), (0, jsx_runtime_1.jsx)("button", { className: "icon-button", onClick: onClose, title: "\u5173\u95ED", children: (0, jsx_runtime_1.jsx)(lucide_react_1.X, { size: 16 }) })] }), (0, jsx_runtime_1.jsxs)("div", { className: "workspace-current", children: [(0, jsx_runtime_1.jsx)("span", { children: "\u5F53\u524D" }), (0, jsx_runtime_1.jsx)("strong", { children: currentPath || "本地工作区" })] }), (0, jsx_runtime_1.jsxs)("label", { className: "workspace-path-field", children: [(0, jsx_runtime_1.jsx)("span", { children: "\u672C\u5730\u8DEF\u5F84" }), (0, jsx_runtime_1.jsx)("input", { value: value, onChange: (event) => onChange(event.target.value), onKeyDown: (event) => {
                                if (event.key === "Enter")
                                    onOpen();
                            }, placeholder: "E:\\\\Projects\\\\my-app" })] }), (0, jsx_runtime_1.jsxs)("div", { className: "workspace-dialog-actions", children: [(0, jsx_runtime_1.jsxs)("button", { type: "button", onClick: pickDirectory, disabled: pickingDirectory, title: "\u6253\u5F00\u7CFB\u7EDF\u6587\u4EF6\u5939\u9009\u62E9\u5668", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.FolderOpen, { size: 16 }), pickingDirectory ? "选择中..." : "选择文件夹"] }), (0, jsx_runtime_1.jsxs)("button", { type: "button", onClick: onOpen, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Check, { size: 16 }), "\u6253\u5F00"] })] }), pendingWorkspace?.candidate ? ((0, jsx_runtime_1.jsxs)("div", { className: "workspace-confirm", children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("strong", { children: "\u786E\u8BA4\u6253\u5F00\u8FD9\u4E2A\u5DE5\u4F5C\u533A\uFF1F" }), (0, jsx_runtime_1.jsx)("span", { children: pendingWorkspace.candidate.path })] }), (0, jsx_runtime_1.jsx)("button", { type: "button", onClick: onConfirm, children: "\u786E\u8BA4" })] })) : ((0, jsx_runtime_1.jsx)("p", { className: "workspace-dialog-note", children: pickerHint || "请粘贴本地绝对路径。浏览器安全策略通常不会把“选择文件夹”的完整路径交给网页。" }))] }) }));
}
function InspectorCard({ title, icon: Icon, children }) {
    return ((0, jsx_runtime_1.jsxs)("div", { className: "panel-card", children: [(0, jsx_runtime_1.jsxs)("h3", { children: [(0, jsx_runtime_1.jsx)(Icon, { size: 16 }), " ", title] }), children] }));
}
function StatGrid({ items }) {
    return ((0, jsx_runtime_1.jsx)("dl", { className: "compact-meta", children: items.map(([label, value]) => ((0, jsx_runtime_1.jsxs)("div", { className: "compact-meta-row", children: [(0, jsx_runtime_1.jsx)("dt", { children: label }), (0, jsx_runtime_1.jsx)("dd", { children: value })] }, label))) }));
}
function pickedDirectoryPath(handle) {
    if (!handle)
        return "";
    for (const key of ["path", "fullPath", "nativePath", "__path"]) {
        const value = handle[key];
        if (typeof value === "string" && value.trim())
            return value.trim();
    }
    return "";
}
function workspaceErrorMessage(error, attemptedPath) {
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
function filterSessions(items, query) {
    const clean = query.trim().toLowerCase();
    if (!clean)
        return items;
    return items.filter((item) => {
        const fields = [item.id, item.model, item.summary_preview, item.last_user_preview, item.last_assistant_preview].filter(Boolean).join(" ").toLowerCase();
        return fields.includes(clean);
    });
}
function computeSessionStats(items) {
    return {
        total: items.length,
        active: items.filter((item) => Boolean(item.pending_plan_token)).length
    };
}
function scopeLabel(scope, profile, sessionId) {
    if (scope === "profile")
        return `Profile: ${profile || "new profile"}`;
    if (scope === "session")
        return sessionId ? `Session override: ${shortId(sessionId)}` : "Session override unavailable";
    return "Project defaults";
}
function readScopeConfig(snapshot, scope, profile) {
    if (scope === "session")
        return snapshot.session_config || {};
    if (scope === "profile") {
        const profiles = (snapshot.project_config.profiles || {});
        const name = profile || snapshot.active_profile || "";
        const value = profiles[name];
        return value && typeof value === "object" ? value : {};
    }
    return snapshot.project_config || {};
}
function isFieldDirty(snapshot, drafts, field, scope, profile) {
    const layer = readScopeConfig(snapshot, scope, profile);
    const layerValue = readConfigPath(layer, field.path);
    const baseline = layerValue === undefined ? readConfigPath(snapshot.settings, field.path) : layerValue;
    return (drafts[field.path] || "") !== stringifyConfigValue(baseline);
}
function renderConfigInput(field, value, onChange) {
    if (field.type === "boolean") {
        return ((0, jsx_runtime_1.jsx)("label", { className: "settings-toggle", children: (0, jsx_runtime_1.jsx)("input", { type: "checkbox", checked: value === "true", onChange: (event) => onChange(String(event.target.checked)) }) }));
    }
    if (field.options?.length) {
        return ((0, jsx_runtime_1.jsx)("select", { value: value, onChange: (event) => onChange(event.target.value), children: field.options.map((option) => (0, jsx_runtime_1.jsx)("option", { value: option, children: option }, option)) }));
    }
    if (field.type === "array") {
        const chips = value.trim().startsWith("[") ? parseArrayPreview(value) : value.split(",").map((item) => item.trim()).filter(Boolean);
        return ((0, jsx_runtime_1.jsxs)("div", { className: "settings-array-editor", children: [(0, jsx_runtime_1.jsx)("div", { children: chips.slice(0, 8).map((item) => (0, jsx_runtime_1.jsx)("span", { children: item }, item)) }), (0, jsx_runtime_1.jsx)("input", { value: value, onChange: (event) => onChange(event.target.value), placeholder: "comma list or JSON array" })] }));
    }
    if (field.type === "object") {
        return (0, jsx_runtime_1.jsx)("textarea", { className: "settings-inline-json", value: value, onChange: (event) => onChange(event.target.value) });
    }
    return ((0, jsx_runtime_1.jsx)("input", { type: field.type.startsWith("integer") || field.type === "number" ? "number" : "text", min: field.minimum ?? undefined, max: field.maximum ?? undefined, value: value, onChange: (event) => onChange(event.target.value) }));
}
function parseArrayPreview(value) {
    try {
        const parsed = JSON.parse(value);
        return Array.isArray(parsed) ? parsed.map(String) : [];
    }
    catch {
        return [];
    }
}
function applyConfigError(err, setError, setFieldErrors) {
    const message = err instanceof Error ? err.message : String(err);
    try {
        const payload = JSON.parse(message);
        const errors = Array.isArray(payload.errors) ? payload.errors : [];
        const next = {};
        errors.forEach((item) => {
            if (typeof item.path === "string")
                next[item.path] = String(item.message || item.code || "Invalid value");
        });
        setFieldErrors(next);
        setError(String(payload.message || "Config validation failed."));
        return;
    }
    catch {
        setError(message.includes("[object Object]") ? "Config conflict or validation error. Reload and reapply the change." : message);
    }
}
function buildConfigDrafts(snapshot) {
    const drafts = {};
    snapshot.schema.fields.forEach((field) => {
        drafts[field.path] = stringifyConfigValue(readConfigPath(snapshot.settings, field.path));
    });
    return drafts;
}
function readConfigPath(source, path) {
    return path.split(".").reduce((current, part) => {
        if (!current || typeof current !== "object")
            return undefined;
        return current[part];
    }, source);
}
function stringifyConfigValue(value) {
    if (value === undefined || value === null)
        return "";
    if (typeof value === "string")
        return value;
    if (typeof value === "number" || typeof value === "boolean")
        return String(value);
    return JSON.stringify(value);
}
function parseFieldDraft(value, type) {
    const text = (value || "").trim();
    if (type === "boolean")
        return text === "true";
    if (type.startsWith("integer"))
        return text ? Number.parseInt(text, 10) : null;
    if (type === "number")
        return text ? Number.parseFloat(text) : 0;
    if (type === "array") {
        if (!text)
            return [];
        if (!text.startsWith("["))
            return text.split(",").map((item) => item.trim()).filter(Boolean);
        return JSON.parse(text);
    }
    if (type === "object" || type.includes("null")) {
        if (!text)
            return type.includes("null") ? null : {};
        return JSON.parse(text);
    }
    return value || "";
}
function readTheme() {
    const stored = window.localStorage.getItem(STORAGE_THEME_KEY);
    if (stored === "light" || stored === "dark")
        return stored;
    return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}
function readStoredView() {
    const stored = window.localStorage.getItem(STORAGE_ACTIVE_VIEW_KEY);
    return stored === "history" || stored === "board" ? "chat" : stored || "chat";
}
function roleLabel(role) {
    if (role === "assistant")
        return "assistant";
    if (role === "user")
        return "user";
    return role;
}
function buildTranscript(snapshot, events = []) {
    const committedMessages = snapshot?.messages || [];
    const stored = committedMessages
        .filter((message) => message.role === "user" || message.role === "assistant")
        .map((message, index) => ({
        id: `stored:${index}`,
        role: message.role,
        body: (0, rich_text_1.extractMessageBody)(message),
        timestamp: typeof message.timestamp === "number" ? message.timestamp : index + 1
    }))
        .filter((item) => item.body.text.trim() || item.body.attachments.length > 0);
    const committedUsers = new Set(committedMessages
        .filter((message) => message.role === "user")
        .map((message) => normalizeText((0, rich_text_1.extractMessageBody)(message).text))
        .filter(Boolean));
    const committedAssistants = committedMessages
        .filter((message) => message.role === "assistant")
        .map((message) => normalizeText((0, rich_text_1.extractMessageBody)(message).text))
        .filter(Boolean);
    const runtime = [];
    const activityGroups = [];
    let activeActivityGroup = [];
    let streamBuffer = "";
    let streamIndex = 0;
    let streamTimestamp = 0;
    const flushActivityGroup = () => {
        const group = activeActivityGroup;
        activeActivityGroup = [];
        if (group.some(isActivityEvent))
            activityGroups.push(group);
    };
    const appendActivityEvent = (event) => {
        if (activeActivityGroup.length === 0)
            activeActivityGroup.push(event);
        else
            activeActivityGroup.push(event);
    };
    const flushStream = () => {
        const text = streamBuffer.trim();
        streamBuffer = "";
        if (!text)
            return;
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
            }
            else {
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
        const activity = combineActivityItemsForTranscript((0, activity_normalizer_1.buildActivityRuns)(group), group);
        if (!activity)
            return;
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
        if (leftTime !== rightTime)
            return leftTime - rightTime;
        return 0;
    });
    if (shouldShowProgressPlaceholder(items, events)) {
        items.push({ id: "progress-placeholder", role: "assistant", body: { text: "Analyzing the request", attachments: [] }, streaming: true });
    }
    return items;
}
function combineActivityItemsForTranscript(items, events) {
    if (items.length === 0)
        return null;
    if (items.length === 1)
        return items[0];
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
function buildTurnMarkers(transcript) {
    const markers = [];
    let current = null;
    const assistantParts = [];
    const finishCurrent = () => {
        if (!current)
            return;
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
        if (!current || item.id === "progress-placeholder")
            return;
        if (item.role === "assistant") {
            assistantParts.push(item.body.text);
        }
        else if (item.role === "activity" && item.activity) {
            assistantParts.push(item.activity.summary || item.body.text);
        }
        else if (item.role === "error") {
            assistantParts.push(item.body.text);
        }
    });
    finishCurrent();
    return markers;
}
function findActiveTurnId(target, markers) {
    if (markers.length === 0)
        return "";
    const anchorTop = target.scrollTop + 80;
    let active = markers[0].id;
    markers.forEach((marker) => {
        const element = findTranscriptElement(target, marker.id);
        if (element && element.offsetTop <= anchorTop)
            active = marker.id;
    });
    return active;
}
function findTranscriptElement(target, id) {
    const items = Array.from(target.querySelectorAll("[data-transcript-id]"));
    return items.find((item) => item.dataset.transcriptId === id) || null;
}
function summarizePreview(value) {
    const clean = normalizeText(value);
    return clean ? truncate(clean, 120) : "";
}
function normalizeText(value) {
    return value.replace(/\s+/g, " ").trim();
}
function formatErrorEvent(event) {
    const lines = [`ERROR: ${event.message || event.type}`];
    if (event.tool_name)
        lines.push(`tool: ${event.tool_name}`);
    if (event.type && event.type !== "error")
        lines.push(`event: ${event.type}`);
    const details = event.details || {};
    const errorType = details.error_type;
    const action = details.action;
    const source = details.source;
    if (typeof errorType === "string" && errorType)
        lines.push(`type: ${errorType}`);
    if (typeof action === "string" && action)
        lines.push(`action: ${action}`);
    if (typeof source === "string" && source)
        lines.push(`source: ${source}`);
    const error = details.error;
    if (typeof error === "string" && error && error !== event.message)
        lines.push(`detail: ${error}`);
    const attempts = details.attempts;
    if (Array.isArray(attempts) && attempts.length > 0) {
        lines.push("attempts:");
        attempts.slice(0, 6).forEach((attempt) => {
            if (!attempt || typeof attempt !== "object")
                return;
            const item = attempt;
            const provider = typeof item.provider === "string" ? item.provider : "provider";
            const status = typeof item.status === "string" ? item.status : "unknown";
            const message = typeof item.error === "string" ? ` - ${item.error}` : "";
            lines.push(`  - ${provider}: ${status}${message}`);
        });
    }
    const diagnostics = details.diagnostics;
    if (diagnostics && typeof diagnostics === "object") {
        const payload = diagnostics;
        const runtime = payload.runtime;
        const controller = payload.controller;
        appendDiagnosticLines(lines, "runtime", runtime);
        appendDiagnosticLines(lines, "controller", controller);
    }
    return lines.join("\n");
}
function isActivityEvent(event) {
    return (event.type.includes("tool") ||
        event.type.includes("planner") ||
        event.type.startsWith("reasoning_") ||
        event.type === "before_provider_request" ||
        event.type === "provider_response" ||
        event.type === "provider_error" ||
        event.type.includes("checkpoint") ||
        event.type.includes("subagent") ||
        event.type === "approval_result" ||
        event.type === "cancel_requested");
}
function formatActivityGroup(events, index) {
    const activityEvents = events.filter(isActivityEvent);
    if (activityEvents.length === 0)
        return null;
    const startedAt = firstTimestamp(events) ?? firstTimestamp(activityEvents);
    const endedAt = latestTerminalTimestamp(events) ?? lastTimestamp(activityEvents);
    const hasError = activityEvents.some((event) => event.type === "tool_error" || event.is_error);
    const entries = buildActivityEntries(activityEvents);
    if (entries.length === 0)
        return null;
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
function buildActivityEntries(events) {
    const entries = [];
    const toolStarts = new Map();
    const seenToolEnds = new Set();
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
        if (seenToolEnds.has(key))
            return;
        entries.push(formatRunningToolEntry(event, key));
    });
    return entries.sort((left, right) => (left.timestamp || 0) - (right.timestamp || 0));
}
function formatToolEntry(event, start, key) {
    const details = event.details || {};
    const startDetails = start?.details || {};
    const toolName = event.tool_name || start?.tool_name || "tool";
    const command = details.command ?? startDetails.command;
    const path = details.path ?? startDetails.path;
    const returncode = details.returncode;
    const isCommand = toolName === "run_shell" || typeof command === "string";
    const durationLabel = start?.timestamp && event.timestamp ? formatDuration(Math.max(0, (event.timestamp - start.timestamp) * 1000)) : "";
    const bits = [];
    if (typeof command === "string" && command.trim())
        bits.push(`Command: ${command.trim()}`);
    if (typeof path === "string" && path.trim())
        bits.push(`Path: ${path.trim()}`);
    if (typeof returncode === "number")
        bits.push(`Exit: ${returncode}`);
    if (event.message && event.message.trim())
        bits.push(truncateMultiline(event.message.trim(), 1200));
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
function formatRunningToolEntry(event, key) {
    const details = event.details || {};
    const toolName = event.tool_name || "tool";
    const command = details.command;
    const path = details.path;
    const bits = ["运行中"];
    if (typeof command === "string" && command.trim())
        bits.push(`Command: ${command.trim()}`);
    if (typeof path === "string" && path.trim())
        bits.push(`Path: ${path.trim()}`);
    return {
        id: `tool:${key}:running`,
        kind: toolName === "run_shell" || typeof command === "string" ? "command" : "tool",
        label: toolName,
        detail: bits.join("\n"),
        timestamp: event.timestamp,
        tone: "running"
    };
}
function groupPlannerDetailLines(events) {
    const plannerEnd = [...events].reverse().find((event) => event.type === "planner_end");
    const plannerSteps = events.filter((event) => event.type === "planner_step" && event.plan_step);
    const details = plannerEnd?.details || {};
    const lines = [];
    const planSteps = Array.isArray(details.plan_steps) ? details.plan_steps : plannerSteps.map((event) => event.plan_step);
    const summary = stringList(details.summary);
    const files = stringList(details.files_touched_guess);
    const shell = stringList(details.shell_commands_guess);
    const tools = stringList(details.tools);
    const highRisk = stringList(details.high_risk_tools);
    const stepCount = typeof details.step_count === "number" ? details.step_count : typeof details.count === "number" ? details.count : planSteps.length || summary.length;
    if (stepCount)
        lines.push(`计划包含 ${stepCount} 个步骤。`);
    summary.slice(0, 4).forEach((item) => lines.push(`- ${item}`));
    if (files.length > 0)
        lines.push(`预计处理文件：${files.slice(0, 5).join(", ")}`);
    if (shell.length > 0)
        lines.push(`准备运行命令：${shell.slice(0, 3).join(" | ")}`);
    if (tools.length > 0)
        lines.push(`准备调用工具：${tools.slice(0, 5).join(", ")}`);
    if (highRisk.length > 0)
        lines.push(`需要确认：${highRisk.slice(0, 5).join(", ")}`);
    return lines;
}
function plannerStatusLabel(status) {
    if (status === "in_progress")
        return "进行中";
    if (status === "completed")
        return "已完成";
    if (status === "failed")
        return "失败";
    if (status === "pending")
        return "等待中";
    return status;
}
function formatPlannerEntry(event, index, plannerSummary) {
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
        if (event.plan_step.tool_name)
            lines.push(`工具：${event.plan_step.tool_name}`);
        if (event.plan_step.status)
            lines.push(`状态：${plannerStatusLabel(event.plan_step.status)}`);
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
function formatRuntimeEntry(event, kind, index) {
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
function activityEntryDetail(entry) {
    const meta = [entry.durationLabel, entry.tone === "running" ? "运行中" : ""].filter(Boolean).join(" · ");
    return `${entry.label}${meta ? ` (${meta})` : ""}\n${entry.detail}`.trim();
}
function firstTimestamp(events) {
    return events.find((event) => typeof event.timestamp === "number")?.timestamp;
}
function lastTimestamp(events) {
    for (let index = events.length - 1; index >= 0; index -= 1) {
        if (typeof events[index].timestamp === "number")
            return events[index].timestamp;
    }
    return undefined;
}
function latestTerminalTimestamp(events) {
    for (let index = events.length - 1; index >= 0; index -= 1) {
        const event = events[index];
        if ((event.type === "turn_end" || event.type === "agent_end") && typeof event.timestamp === "number")
            return event.timestamp;
    }
    return undefined;
}
function formatToolEvent(event) {
    const details = event.details || {};
    const toolName = event.tool_name || "工具";
    const status = toolEventStatus(details, event.is_error);
    const lines = [status, `${toolName}`];
    const path = details.path;
    const command = details.command;
    const token = details.token;
    const output = typeof event.message === "string" ? event.message.trim() : "";
    if (typeof path === "string" && path.trim())
        lines.push(`文件：${path}`);
    if (typeof command === "string" && command.trim())
        lines.push(`命令：${command}`);
    if (typeof token === "string" && token.trim())
        lines.push(`token：${token}`);
    const returncode = details.returncode;
    if (typeof returncode === "number")
        lines.push(`退出码：${returncode}`);
    if (details.approval_token && typeof details.approval_token === "string")
        lines.push(`审批 token：${details.approval_token}`);
    if (output) {
        lines.push("");
        lines.push(output);
    }
    return lines.join("\n").trim();
}
function toolResultAttachments(details) {
    const attachments = [];
    const seen = new Set();
    const pushAttachment = (item, rawUrl) => {
        if (!rawUrl)
            return;
        const url = (0, rich_text_1.sanitizeMediaUrl)(rawUrl, { allowRelative: false });
        if (!url || seen.has(url))
            return;
        if (looksLikeDecorativeImage(url, firstStringValue(item.title, item.alt) || ""))
            return;
        seen.add(url);
        attachments.push({
            url,
            alt: firstStringValue(item.title, item.alt),
            title: firstStringValue(item.title),
            name: firstStringValue(item.url),
        });
    };
    for (const result of Array.isArray(details.results) ? details.results : []) {
        if (!result || typeof result !== "object")
            continue;
        const item = result;
        const rawUrl = firstStringValue(item.image_url, item.image, item.thumbnail, item.thumbnail_url);
        pushAttachment(item, rawUrl);
        if (attachments.length >= 3)
            break;
    }
    for (const image of Array.isArray(details.images) ? details.images : []) {
        if (!image || typeof image !== "object")
            continue;
        const item = image;
        pushAttachment(item, firstStringValue(item.url, item.src, item.image_url));
        if (attachments.length >= 3)
            break;
    }
    return attachments;
}
function looksLikeDecorativeImage(url, label) {
    const value = `${url} ${label}`.toLowerCase();
    if (["logo", "favicon", "icon", "sprite", "placeholder", "blank", "loading", "avatar", "qrcode", "qr-code", "wechat", "weixin", "广告", "二维码", "图标"].some((word) => value.includes(word))) {
        return true;
    }
    return /(^|[/_.-])(ad|ads|advert|banner|sponsor|promo)([/_.-]|$)/.test(value);
}
function firstStringValue(...values) {
    for (const value of values) {
        if (typeof value === "string" && value.trim())
            return value.trim();
    }
    return undefined;
}
function formatApprovalEvent(event) {
    const details = event.details || {};
    const approvalDetails = details.approval_details || {};
    const lines = [];
    const actionType = typeof details.action_type === "string" ? details.action_type : "";
    if (actionType === "run_shell") {
        lines.push("Command completed.");
    }
    else if (actionType === "write_file" || actionType === "edit_file") {
        const path = approvalDetails.path || approvalDetails.absolute_path || details.path;
        lines.push(typeof path === "string" && path.trim() ? `Applied successfully: ${path}` : "Applied successfully.");
    }
    else if (actionType === "apply_patch_artifact") {
        const changedPaths = Array.isArray(approvalDetails.changed_paths)
            ? approvalDetails.changed_paths.filter((value) => typeof value === "string" && value.trim().length > 0)
            : [];
        lines.push(changedPaths.length > 0 ? `Patch applied successfully: ${changedPaths.join(", ")}` : "Patch artifact applied successfully.");
    }
    else if (event.message) {
        lines.push(event.message);
    }
    else {
        lines.push("Approval completed.");
    }
    const result = details.result;
    if (typeof result === "string" && result.trim()) {
        lines.push("");
        lines.push(result.trim());
    }
    return lines.join("\n").trim();
}
function toolEventStatus(details, isError) {
    if (details.persisted === true)
        return "已完成";
    if (details.staged === true)
        return "已进入审批";
    if (details.approval_unavailable === true)
        return "无法安全执行";
    if (isError)
        return "执行失败";
    return "执行完成";
}
function appendDiagnosticLines(lines, label, value) {
    if (!value || typeof value !== "object")
        return;
    const payload = value;
    const status = payload.status && typeof payload.status === "object" ? payload.status : payload;
    const interesting = ["controller", "running", "controller_ready", "cdp_port", "tabs_count", "last_error", "doctor_error"];
    const parts = interesting
        .map((key) => {
        const item = status[key];
        if (item === undefined || item === null || item === "")
            return "";
        return `${key}=${String(item)}`;
    })
        .filter(Boolean);
    if (parts.length > 0)
        lines.push(`${label}: ${parts.join(", ")}`);
    const recent = status.recent_actions;
    if (Array.isArray(recent) && recent.length > 0) {
        const tail = recent.slice(-3).map((item) => {
            if (!item || typeof item !== "object")
                return "";
            const action = item.action || "action";
            const ok = item.ok === true ? "ok" : "failed";
            const duration = item.duration_ms;
            const error = item.error;
            return `${String(action)}:${ok}${typeof duration === "number" ? ` ${duration}ms` : ""}${typeof error === "string" ? ` ${error}` : ""}`;
        }).filter(Boolean);
        if (tail.length > 0)
            lines.push(`${label} recent: ${tail.join(" | ")}`);
    }
}
function runtimeEventDedupeKey(event) {
    const details = event.details || {};
    const trace = details.trace && typeof details.trace === "object" ? details.trace : {};
    const activity = details.activity && typeof details.activity === "object" ? details.activity : {};
    const explicit = event.event_id || trace.event_id || activity.event_id || details.event_id;
    if (typeof explicit === "string" && explicit.trim())
        return explicit;
    if (typeof explicit === "number")
        return String(explicit);
    return runtimeEventKey(event);
}
function runtimeEventKey(event) {
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
function shouldShowProgressPlaceholder(items, events) {
    if (!isTurnInFlight(events))
        return false;
    const latestUserIndex = findLastIndex(items, (item) => item.role === "user");
    if (latestUserIndex < 0)
        return true;
    return !items.slice(latestUserIndex + 1).some((item) => item.role === "assistant" && item.body.text.trim() && item.id !== "progress-placeholder");
}
function runtimeIsBusy(snapshot, events) {
    if (snapshot)
        return Boolean(snapshot.busy);
    return isTurnInFlight(events);
}
function runtimeDisplayStatus(currentStatus, snapshot, events) {
    if (snapshot?.cancel_requested)
        return "Canceling";
    if (snapshot?.busy)
        return currentStatus;
    const terminal = latestTerminalEvent(events);
    if (hasErrorSinceLatestStart(events))
        return "Failed";
    const phase = snapshot?.turn?.phase;
    if (phase === "idle")
        return terminal ? "Completed" : "Idle";
    if (terminal)
        return "Completed";
    return currentStatus === "tool_start" ? "Idle" : currentStatus;
}
function isTurnInFlight(events) {
    let inFlight = false;
    for (const event of events) {
        if (event.type === "local_user_prompt" || event.type === "agent_start" || event.type === "turn_start")
            inFlight = true;
        if (event.type === "turn_end" || event.type === "agent_end" || event.type === "error")
            inFlight = false;
    }
    return inFlight;
}
function latestTerminalEvent(events) {
    for (let index = events.length - 1; index >= 0; index -= 1) {
        const event = events[index];
        if (event.type === "turn_end" || event.type === "agent_end" || event.type === "error" || event.is_error)
            return event;
    }
    return undefined;
}
function hasErrorSinceLatestStart(events) {
    const latestStart = findLastIndex(events, (event) => event.type === "local_user_prompt" || event.type === "agent_start" || event.type === "turn_start");
    return events.slice(Math.max(0, latestStart)).some((event) => event.type === "error" || event.is_error);
}
function buildActivityItems(events, snapshot, approvals) {
    return (0, activity_normalizer_1.buildActivityRuns)(events, snapshot, approvals);
}
function eventLabel(event) {
    const specName = event.details?.spec_name;
    if (typeof specName === "string" && specName.trim())
        return specName;
    return event.type.replace(/_/g, " ");
}
function summarizeEvent(event, toolStart) {
    const duration = toolDuration(event, toolStart);
    const durationSuffix = duration ? ` (${duration})` : "";
    if (event.plan_step?.title)
        return event.plan_step.title;
    if (event.message)
        return `${truncate(event.message, 92)}${durationSuffix}`;
    const preview = event.details?.preview;
    if (typeof preview === "string" && preview.trim())
        return `${truncate(preview, 92)}${durationSuffix}`;
    const summary = event.details?.summary;
    if (typeof summary === "string" && summary.trim())
        return `${truncate(summary, 92)}${durationSuffix}`;
    const childSession = event.details?.child_session_id || event.details?.session_id;
    const status = event.details?.status;
    if (typeof childSession === "string" && childSession.trim()) {
        const prefix = typeof status === "string" && status.trim() ? `${status}: ` : "";
        return `${prefix}child ${childSession.slice(0, 8)}${durationSuffix}`;
    }
    const completed = event.details?.completed;
    const total = event.details?.total;
    if (typeof completed === "number" && typeof total === "number")
        return `${completed}/${total}${durationSuffix}`;
    if (event.type === "tool_start")
        return "Started";
    if (event.type === "subagent_start")
        return "Started";
    if (event.type === "subagent_progress")
        return "Running";
    if (event.type === "subagent_end")
        return "Completed";
    if (event.type === "cancel_requested")
        return "Cancel requested";
    return event.is_error ? "Failed" : "Updated";
}
function toolEventKey(event) {
    const callId = event.details?.tool_call_id;
    if (typeof callId === "string" && callId.trim())
        return callId;
    return event.tool_name || "";
}
function toolDuration(event, toolStart) {
    if (event.type !== "tool_end" && event.type !== "tool_result" && event.type !== "tool_error")
        return "";
    if (!toolStart?.timestamp || !event.timestamp)
        return "";
    const elapsedMs = Math.max(0, (event.timestamp - toolStart.timestamp) * 1000);
    if (elapsedMs < 1000)
        return "";
    return formatDuration(elapsedMs);
}
function formatDuration(elapsedMs) {
    const totalSeconds = Math.max(1, Math.round(elapsedMs / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return minutes ? `${minutes}m ${seconds}s` : `${seconds}s`;
}
function truncate(value, limit) {
    const clean = normalizeText(value);
    return clean.length <= limit ? clean : `${clean.slice(0, limit - 1)}...`;
}
function truncateMultiline(value, limit) {
    const clean = value.trim();
    return clean.length <= limit ? clean : `${clean.slice(0, limit - 1)}...`;
}
function findLastIndex(items, predicate) {
    for (let index = items.length - 1; index >= 0; index -= 1) {
        if (predicate(items[index]))
            return index;
    }
    return -1;
}
function buildActiveApproval(snapshot, events, summary) {
    const plannerToken = snapshot?.pending_plan_token;
    const sessionId = snapshot?.session_id || "";
    const eventTokens = eventPendingTokens(events);
    if (plannerToken) {
        const sourceItems = summary.active_items || summary.items;
        const plannerAction = sourceItems.find((item) => item.action_type === "planner_approval" && item.token === plannerToken && isActionableApproval(item) && approvalBelongsToSession(item, sessionId, eventTokens));
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
    const pending = sourceItems.find((item) => item.action_type !== "planner_approval" && isActionableApproval(item) && approvalBelongsToSession(item, sessionId, eventTokens));
    if (!pending)
        return null;
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
function eventPendingTokens(events) {
    const tokens = new Set();
    events.forEach((event) => {
        const token = event.details?.token;
        if (typeof token === "string" && token.trim())
            tokens.add(token);
    });
    return tokens;
}
function approvalBelongsToSession(item, sessionId, eventTokens) {
    const itemSession = item.details?.session_id;
    if (typeof itemSession === "string" && itemSession)
        return itemSession === sessionId;
    return eventTokens.has(item.token);
}
function isActionableApproval(item) {
    const state = item.lifecycle?.state || "";
    return ACTIONABLE_APPROVAL_STATES.has(state);
}
function latestPlannerApprovalDetails(events, token) {
    for (let index = events.length - 1; index >= 0; index -= 1) {
        const event = events[index];
        if (event.type !== "planner_gate_pending" && event.type !== "planner_start" && event.type !== "planner_end")
            continue;
        const details = event.details || {};
        const eventToken = details.token;
        if (typeof eventToken === "string" && eventToken && eventToken !== token)
            continue;
        if (Array.isArray(details.summary) || Array.isArray(details.plan_steps) || Array.isArray(details.tools))
            return details;
    }
    return undefined;
}
function plannerApprovalDescription(item, eventDetails) {
    const details = item?.details || eventDetails || {};
    const steps = plannerStepSummaries(details);
    if (steps.length > 0) {
        const visible = steps.slice(0, 3).map((step, index) => `${index + 1}. ${step}`).join("  ");
        const suffix = steps.length > 3 ? `  另有 ${steps.length - 3} 步。` : "";
        return `即将执行 ${steps.length} 步：${visible}${suffix}`;
    }
    const tools = stringList(details.tools);
    if (tools.length > 0)
        return `即将调用工具：${tools.slice(0, 5).join(", ")}。批准后才会进入具体执行。`;
    return "确认模型提出的工具执行计划。批准计划本身不会直接改文件，下一步仍会对具体动作单独确认。";
}
function plannerApprovalMeta(item, eventDetails) {
    const details = item?.details || eventDetails || {};
    const tools = stringList(details.tools);
    const files = stringList(details.files_touched_guess);
    const bits = [];
    if (tools.length > 0)
        bits.push(`tools: ${tools.slice(0, 4).join(", ")}${tools.length > 4 ? ", ..." : ""}`);
    if (files.length > 0)
        bits.push(`files: ${files.slice(0, 3).join(", ")}${files.length > 3 ? ", ..." : ""}`);
    return bits.join(" · ");
}
function plannerStepSummaries(details) {
    const summary = stringList(details.summary);
    if (summary.length > 0)
        return summary;
    const planSteps = Array.isArray(details.plan_steps) ? details.plan_steps : [];
    return planSteps
        .map((step) => {
        if (!step || typeof step !== "object")
            return "";
        const record = step;
        const title = typeof record.title === "string" ? record.title.trim() : "";
        const tool = typeof record.tool_name === "string" ? record.tool_name.trim() : "";
        if (title && tool)
            return `${title} [${tool}]`;
        return title || tool;
    })
        .filter((value) => value.length > 0);
}
function stringList(value) {
    if (!Array.isArray(value))
        return [];
    return value.map((item) => String(item || "").trim()).filter((item) => item.length > 0);
}
function approvalEmptyText(busy, workspaceApprovalCount) {
    if (busy)
        return "Plan accepted. Waiting for model output or an exact action confirmation.";
    if (workspaceApprovalCount > 0)
        return `${workspaceApprovalCount} pending approval(s) exist in this workspace.`;
    return "No pending approval for this session.";
}
function approvalTitle(actionType) {
    if (actionType === "apply_patch_artifact")
        return "apply isolated patch artifact";
    if (actionType === "write_file")
        return "apply staged write";
    if (actionType === "edit_file")
        return "apply staged edit";
    if (actionType === "run_shell")
        return "run staged command";
    return actionType.replace(/_/g, " ");
}
function approvalButtonLabel(actionType) {
    if (actionType === "apply_patch_artifact")
        return "Apply patch";
    if (actionType === "write_file")
        return "Apply write";
    if (actionType === "edit_file")
        return "Apply edit";
    if (actionType === "run_shell")
        return "Run command";
    return "Approve action";
}
function approvalSuccessMessage(actionType, result) {
    if (actionType === "apply_patch_artifact") {
        const changedPaths = Array.isArray(result.details?.changed_paths)
            ? result.details.changed_paths.filter((value) => typeof value === "string" && value.trim().length > 0)
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
function approvalDescription(item) {
    if (item.action_type === "apply_patch_artifact") {
        const details = item.details || {};
        const changedPaths = Array.isArray(details.changed_paths)
            ? details.changed_paths.filter((value) => typeof value === "string" && value.trim().length > 0)
            : [];
        if (changedPaths.length > 0) {
            return `Changed paths: ${changedPaths.join(", ")}. Staged only; the main workspace updates after approval.`;
        }
        return "Isolated patch artifact is staged only; the main workspace updates after approval.";
    }
    if (item.target_path)
        return `Target: ${item.target_path}`;
    if (item.command)
        return `Command: ${item.command}`;
    const details = item.details || {};
    const target = details.target_path || details.path || details.file_path;
    if (typeof target === "string" && target.trim())
        return `Target: ${target}`;
    const command = details.command;
    if (typeof command === "string" && command.trim())
        return `Command: ${command}`;
    const summary = details.summary;
    if (Array.isArray(summary) && summary.length > 0)
        return String(summary[0]);
    if (typeof summary === "string" && summary.trim())
        return summary;
    return "A concrete staged action is waiting for your second confirmation.";
}
function approvalMeta(item) {
    const state = item.lifecycle?.state || "pending";
    return `${item.action_type} · ${state}`;
}
function shortId(value) {
    return value ? value.slice(0, 8) : "session";
}
function sortSessionsByUpdatedAt(items) {
    return [...items].sort((left, right) => (right.updated_at || 0) - (left.updated_at || 0));
}
