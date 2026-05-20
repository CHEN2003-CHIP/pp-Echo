"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.App = App;
exports.buildTranscript = buildTranscript;
exports.runtimeIsBusy = runtimeIsBusy;
exports.runtimeDisplayStatus = runtimeDisplayStatus;
exports.isTurnInFlight = isTurnInFlight;
exports.buildActivityItems = buildActivityItems;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
const lucide_react_1 = require("lucide-react");
const api_1 = require("./api");
const rich_text_1 = require("./rich-text");
const navItems = [
    { type: "projects", label: "Projects", icon: lucide_react_1.FolderOpen },
    { type: "agents", label: "Agents / Subagents", icon: lucide_react_1.Bot },
    { type: "mcp", label: "MCP Manager", icon: lucide_react_1.Boxes },
    { type: "usage", label: "Usage", icon: lucide_react_1.LayoutDashboard },
    { type: "timeline", label: "Timeline", icon: lucide_react_1.GitBranch },
    { type: "settings", label: "Settings", icon: lucide_react_1.Settings }
];
function App() {
    const [workspace, setWorkspace] = (0, react_1.useState)({ name: "pp-Echo", path: "" });
    const [workspaces, setWorkspaces] = (0, react_1.useState)({ active: { name: "pp-Echo", path: "", exists: true, is_dir: true }, recent: [] });
    const [sessions, setSessions] = (0, react_1.useState)([]);
    const [tabs, setTabs] = (0, react_1.useState)([]);
    const [activeTabId, setActiveTabId] = (0, react_1.useState)("");
    const [snapshots, setSnapshots] = (0, react_1.useState)({});
    const [events, setEvents] = (0, react_1.useState)({});
    const [prompt, setPrompt] = (0, react_1.useState)("");
    const [status, setStatus] = (0, react_1.useState)("Ready");
    const [sideData, setSideData] = (0, react_1.useState)({});
    const [approvalSummary, setApprovalSummary] = (0, react_1.useState)({ count: 0, items: [] });
    const [approvalAction, setApprovalAction] = (0, react_1.useState)(null);
    const [approvalFeedback, setApprovalFeedback] = (0, react_1.useState)("");
    const [workspaceDraft, setWorkspaceDraft] = (0, react_1.useState)("");
    const [pendingWorkspace, setPendingWorkspace] = (0, react_1.useState)(null);
    const pollers = (0, react_1.useRef)({});
    const transcriptRef = (0, react_1.useRef)(null);
    (0, react_1.useEffect)(() => {
        refreshAll();
        return () => {
            Object.values(pollers.current).forEach((poller) => window.clearInterval(poller));
        };
    }, []);
    const activeTab = tabs.find((tab) => tab.id === activeTabId);
    const activeSessionId = activeTab?.type === "chat" ? activeTab.sessionId : "";
    const activeSnapshot = activeSessionId ? snapshots[activeSessionId] : undefined;
    const activeEvents = activeSessionId ? events[activeSessionId] || [] : [];
    const transcript = (0, react_1.useMemo)(() => buildTranscript(activeSnapshot, activeEvents), [activeSnapshot, activeEvents]);
    const activityItems = (0, react_1.useMemo)(() => buildActivityItems(activeEvents), [activeEvents]);
    const activeApproval = (0, react_1.useMemo)(() => buildActiveApproval(activeSnapshot, activeEvents, approvalSummary), [activeSnapshot, activeEvents, approvalSummary]);
    const busy = runtimeIsBusy(activeSnapshot, activeEvents);
    const displayStatus = runtimeDisplayStatus(status, activeSnapshot, activeEvents);
    (0, react_1.useEffect)(() => {
        const target = transcriptRef.current;
        if (target) {
            target.scrollTop = target.scrollHeight;
        }
    }, [transcript.length, transcript[transcript.length - 1]?.body.text, transcript[transcript.length - 1]?.body.attachments.length]);
    async function refreshAll() {
        const [workspaceState, sessionList, approvals] = await Promise.all([api_1.api.workspaces(), api_1.api.sessions(), api_1.api.approvals()]);
        setWorkspaces(workspaceState);
        setWorkspace(workspaceState.active);
        setSessions(sortSessionsByUpdatedAt(sessionList.sessions));
        setApprovalSummary(approvals);
        setStatus("Connected");
        if (sessionList.sessions[0] && tabs.length === 0) {
            openSession(sessionList.sessions[0].id);
        }
    }
    async function openSession(sessionId) {
        const snapshot = await api_1.api.snapshot(sessionId).catch(async () => {
            const created = await api_1.api.createSession();
            return created;
        });
        setSnapshots((current) => ({ ...current, [snapshot.session_id]: snapshot }));
        ensureEventPolling(snapshot.session_id);
        const tab = { id: `chat:${snapshot.session_id}`, type: "chat", title: shortId(snapshot.session_id), sessionId: snapshot.session_id };
        setTabs((current) => (current.some((item) => item.id === tab.id) ? current : [...current, tab]));
        setActiveTabId(tab.id);
    }
    async function createSession() {
        const created = await api_1.api.createSession();
        await refreshAll();
        openSession(created.session_id);
    }
    function ensureEventPolling(sessionId) {
        if (pollers.current[sessionId])
            return;
        setStatus("Live events connected");
        const poll = async () => {
            const payload = await api_1.api.events(sessionId).catch(() => ({ events: [] }));
            payload.events.forEach((event) => appendEvent(sessionId, event));
            refreshSessionState(sessionId);
        };
        poll();
        pollers.current[sessionId] = window.setInterval(poll, 700);
    }
    function appendEvent(sessionId, event) {
        setEvents((current) => ({ ...current, [sessionId]: [...(current[sessionId] || []), event] }));
        setStatus(event.message || event.type);
    }
    function refreshSessionState(sessionId) {
        api_1.api.snapshot(sessionId).then((snapshot) => setSnapshots((current) => ({ ...current, [sessionId]: snapshot }))).catch(() => undefined);
        api_1.api.sessions().then((payload) => setSessions(sortSessionsByUpdatedAt(payload.sessions))).catch(() => undefined);
        refreshApprovals();
    }
    function refreshApprovals() {
        return api_1.api.approvals().then(setApprovalSummary).catch(() => undefined);
    }
    function openPanel(type) {
        const title = navItems.find((item) => item.type === type)?.label || type;
        const tab = { id: `panel:${type}`, type, title };
        setTabs((current) => (current.some((item) => item.id === tab.id) ? current : [...current, tab]));
        setActiveTabId(tab.id);
        loadPanel(type);
    }
    async function loadPanel(type) {
        const loader = type === "projects" ? api_1.api.workspaces :
            type === "agents" ? api_1.api.capabilities :
                type === "mcp" ? api_1.api.mcp :
                    type === "settings" ? api_1.api.settings :
                        type === "usage" ? () => api_1.api.runtimeReport(activeSessionId || undefined) :
                            type === "timeline" && activeSessionId ? () => api_1.api.tree(activeSessionId) :
                                async () => ({});
        const data = await loader().catch((error) => ({ error: String(error) }));
        setSideData((current) => ({ ...current, [type]: data }));
    }
    function stopPolling() {
        Object.values(pollers.current).forEach((poller) => window.clearInterval(poller));
        pollers.current = {};
    }
    function resetWorkspaceUi() {
        stopPolling();
        setTabs([]);
        setActiveTabId("");
        setSnapshots({});
        setEvents({});
        setPrompt("");
        setSideData({});
        setApprovalSummary({ count: 0, items: [] });
    }
    async function reloadWorkspaceAfterSwitch(workspaceState) {
        resetWorkspaceUi();
        setWorkspaces(workspaceState);
        setWorkspace(workspaceState.active);
        setStatus(`Workspace: ${workspaceState.active.name}`);
        const [sessionList, approvals] = await Promise.all([api_1.api.sessions(), api_1.api.approvals()]);
        const sorted = sortSessionsByUpdatedAt(sessionList.sessions);
        setSessions(sorted);
        setApprovalSummary(approvals);
        if (sorted[0]) {
            openSession(sorted[0].id);
        }
    }
    async function openWorkspace(path, confirmed = false) {
        const target = path.trim();
        if (!target)
            return;
        try {
            const response = await api_1.api.openWorkspace(target, confirmed);
            if (response.requires_confirmation) {
                setPendingWorkspace(response);
                setStatus("Workspace confirmation required");
                return;
            }
            setPendingWorkspace(null);
            setWorkspaceDraft("");
            await reloadWorkspaceAfterSwitch(response);
        }
        catch (error) {
            setStatus(error instanceof Error ? error.message : String(error));
        }
    }
    async function sendPrompt() {
        if (!activeSessionId || !prompt.trim())
            return;
        const text = prompt;
        setPrompt("");
        appendEvent(activeSessionId, { type: "local_user_prompt", session_id: activeSessionId, message: text });
        await api_1.api.prompt(activeSessionId, text);
        refreshSessionState(activeSessionId);
    }
    async function cancelActiveSession() {
        if (!activeSessionId || !busy)
            return;
        appendEvent(activeSessionId, {
            type: "cancel_requested",
            session_id: activeSessionId,
            message: "Cancel requested for the running turn.",
            details: { cancel_requested: true }
        });
        await api_1.api.cancel(activeSessionId);
        refreshSessionState(activeSessionId);
    }
    async function approve() {
        if (!activeApproval)
            return;
        const approval = activeApproval;
        setApprovalAction({ token: approval.token, action: "approve" });
        setApprovalFeedback("");
        try {
            if (approval.kind === "planner" && activeSessionId) {
                await api_1.api.approve(activeSessionId);
                clearPlannerToken(activeSessionId);
                setStatus("Plan approved");
                setApprovalFeedback("Plan approved. Waiting for the concrete action.");
            }
            else {
                const result = await api_1.api.approvePending(approval.token);
                removeApproval(approval.token);
                const message = approvalSuccessMessage(approval.actionType || "", result);
                setStatus(message);
                setApprovalFeedback(message);
            }
            if (activeSessionId)
                refreshSessionState(activeSessionId);
            await refreshApprovals();
        }
        catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            setStatus(message);
            setApprovalFeedback(message);
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
            }
            else {
                await api_1.api.rejectPending(approval.token);
                removeApproval(approval.token);
            }
            setStatus("Approval rejected");
            setApprovalFeedback("Approval rejected.");
            if (activeSessionId)
                refreshSessionState(activeSessionId);
            await refreshApprovals();
        }
        catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            setStatus(message);
            setApprovalFeedback(message);
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
            tokens: current.tokens?.filter((item) => item !== token),
            items: current.items.filter((item) => item.token !== token)
        }));
    }
    function closeTab(tabId) {
        setTabs((current) => current.filter((tab) => tab.id !== tabId));
        if (activeTabId === tabId) {
            const remaining = tabs.filter((tab) => tab.id !== tabId);
            setActiveTabId(remaining[remaining.length - 1]?.id || "");
        }
    }
    return ((0, jsx_runtime_1.jsxs)("div", { className: "shell", children: [(0, jsx_runtime_1.jsxs)("header", { className: "titlebar", children: [(0, jsx_runtime_1.jsxs)("div", { className: "brand", children: [(0, jsx_runtime_1.jsx)("div", { className: "brand-mark", children: (0, jsx_runtime_1.jsx)(lucide_react_1.Sparkles, { size: 17 }) }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("strong", { children: "pp-Echo" }), (0, jsx_runtime_1.jsx)("span", { children: workspace.path })] })] }), (0, jsx_runtime_1.jsxs)("div", { className: "title-actions", children: [(0, jsx_runtime_1.jsx)("button", { title: "Refresh", onClick: refreshAll, children: (0, jsx_runtime_1.jsx)(lucide_react_1.RefreshCw, { size: 16 }) }), (0, jsx_runtime_1.jsx)("button", { title: "New session", onClick: createSession, children: (0, jsx_runtime_1.jsx)(lucide_react_1.Plus, { size: 16 }) }), (0, jsx_runtime_1.jsx)("button", { title: "Stop", disabled: !activeSessionId || !busy, onClick: cancelActiveSession, children: (0, jsx_runtime_1.jsx)(lucide_react_1.Square, { size: 15 }) })] })] }), (0, jsx_runtime_1.jsxs)("aside", { className: "sidebar", children: [(0, jsx_runtime_1.jsxs)("button", { className: "workspace-card", onClick: () => openPanel("projects"), children: [(0, jsx_runtime_1.jsx)("div", { className: "workspace-icon", children: (0, jsx_runtime_1.jsx)(lucide_react_1.Code2, { size: 20 }) }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("h1", { children: workspace.name }), (0, jsx_runtime_1.jsx)("p", { children: "Local workspace" })] }), (0, jsx_runtime_1.jsx)(lucide_react_1.ChevronRight, { size: 14 })] }), (0, jsx_runtime_1.jsx)("nav", { className: "nav-list", children: navItems.map((item) => ((0, jsx_runtime_1.jsxs)("button", { onClick: () => openPanel(item.type), children: [(0, jsx_runtime_1.jsx)(item.icon, { size: 16 }), (0, jsx_runtime_1.jsx)("span", { children: item.label }), (0, jsx_runtime_1.jsx)(lucide_react_1.ChevronRight, { size: 14 })] }, item.type))) }), (0, jsx_runtime_1.jsxs)("section", { className: "session-list", children: [(0, jsx_runtime_1.jsxs)("div", { className: "section-title", children: [(0, jsx_runtime_1.jsx)("span", { children: "Sessions" }), (0, jsx_runtime_1.jsx)("button", { onClick: createSession, title: "New session", children: (0, jsx_runtime_1.jsx)(lucide_react_1.Plus, { size: 14 }) })] }), sessions.map((session) => ((0, jsx_runtime_1.jsxs)("button", { className: "session-row", onClick: () => openSession(session.id), children: [(0, jsx_runtime_1.jsx)(lucide_react_1.MessageSquare, { size: 15 }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("strong", { children: session.last_user_preview || session.summary_preview || shortId(session.id) }), (0, jsx_runtime_1.jsxs)("span", { children: [session.turn_count, " turns \u00B7 ", session.model] })] })] }, session.id)))] })] }), (0, jsx_runtime_1.jsxs)("main", { className: "main", children: [(0, jsx_runtime_1.jsx)("div", { className: "tabs", children: tabs.map((tab) => ((0, jsx_runtime_1.jsxs)("button", { className: tab.id === activeTabId ? "tab active" : "tab", onClick: () => setActiveTabId(tab.id), children: [(0, jsx_runtime_1.jsx)("span", { children: tab.title }), (0, jsx_runtime_1.jsx)(lucide_react_1.X, { size: 13, onClick: (event) => { event.stopPropagation(); closeTab(tab.id); } })] }, tab.id))) }), (0, jsx_runtime_1.jsx)("div", { className: "content", children: activeTab?.type === "chat" ? ((0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsxs)("section", { className: "transcript", ref: transcriptRef, children: [transcript.length === 0 && ((0, jsx_runtime_1.jsxs)("div", { className: "empty", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Sparkles, { size: 26 }), (0, jsx_runtime_1.jsx)("h2", { children: "Start a pp-Echo session" }), (0, jsx_runtime_1.jsx)("p", { children: "Ask for repo inspection, implementation planning, or a safe change." })] })), transcript.map((item) => ((0, jsx_runtime_1.jsxs)("article", { className: `message ${item.role}${item.streaming ? " streaming" : ""}`, children: [(0, jsx_runtime_1.jsx)("div", { className: "avatar", children: item.role === "assistant" ? (0, jsx_runtime_1.jsx)(lucide_react_1.Bot, { size: 16 }) : (0, jsx_runtime_1.jsx)(lucide_react_1.MessageSquare, { size: 15 }) }), (0, jsx_runtime_1.jsxs)("div", { className: "bubble", children: [(0, jsx_runtime_1.jsx)("span", { children: item.role }), (0, jsx_runtime_1.jsx)(rich_text_1.RichMessageContent, { text: item.body.text, attachments: item.body.attachments, streaming: item.streaming })] })] }, item.id)))] }), (0, jsx_runtime_1.jsxs)("aside", { className: "detail-panel", children: [(0, jsx_runtime_1.jsxs)("div", { className: "panel-card", children: [(0, jsx_runtime_1.jsxs)("h3", { children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Activity, { size: 16 }), " Runtime"] }), (0, jsx_runtime_1.jsxs)("dl", { children: [(0, jsx_runtime_1.jsx)("dt", { children: "Status" }), (0, jsx_runtime_1.jsx)("dd", { children: displayStatus }), (0, jsx_runtime_1.jsx)("dt", { children: "Session" }), (0, jsx_runtime_1.jsx)("dd", { children: shortId(activeSessionId) }), (0, jsx_runtime_1.jsx)("dt", { children: "Phase" }), (0, jsx_runtime_1.jsx)("dd", { children: activeSnapshot?.runtime_control?.status || activeSnapshot?.turn?.phase || "idle" }), (0, jsx_runtime_1.jsx)("dt", { children: "Queue" }), (0, jsx_runtime_1.jsx)("dd", { children: activeSnapshot?.queued_message_count || 0 }), (0, jsx_runtime_1.jsx)("dt", { children: "Artifacts" }), (0, jsx_runtime_1.jsx)("dd", { children: activeSnapshot?.runtime_control?.pending_artifact_count || 0 }), (0, jsx_runtime_1.jsx)("dt", { children: "Mode" }), (0, jsx_runtime_1.jsx)("dd", { children: activeSnapshot?.cancel_requested ? "Canceling" : busy ? "Working" : "Idle" })] })] }), (0, jsx_runtime_1.jsxs)("div", { className: "panel-card", children: [(0, jsx_runtime_1.jsxs)("h3", { children: [(0, jsx_runtime_1.jsx)(lucide_react_1.ShieldCheck, { size: 16 }), " Approval"] }), activeApproval ? ((0, jsx_runtime_1.jsxs)(jsx_runtime_1.Fragment, { children: [(0, jsx_runtime_1.jsx)("p", { className: "approval-kind", children: activeApproval.title }), (0, jsx_runtime_1.jsx)("p", { className: "muted", children: activeApproval.description }), activeApproval.meta && (0, jsx_runtime_1.jsx)("small", { className: "approval-meta", children: activeApproval.meta }), (0, jsx_runtime_1.jsx)("code", { children: String(activeApproval.token).slice(0, 18) }), (0, jsx_runtime_1.jsxs)("div", { className: "split-actions", children: [(0, jsx_runtime_1.jsxs)("button", { disabled: Boolean(approvalAction), onClick: approve, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Check, { size: 15 }), " ", approvalAction?.token === activeApproval.token && approvalAction.action === "approve" ? "Applying..." : activeApproval.approveLabel] }), (0, jsx_runtime_1.jsxs)("button", { disabled: Boolean(approvalAction), onClick: reject, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.X, { size: 15 }), " ", approvalAction?.token === activeApproval.token && approvalAction.action === "reject" ? "Rejecting..." : "Reject"] })] })] })) : (0, jsx_runtime_1.jsx)("p", { className: "muted", children: approvalFeedback || approvalEmptyText(busy, approvalSummary.count) })] }), (0, jsx_runtime_1.jsxs)("div", { className: "panel-card", children: [(0, jsx_runtime_1.jsxs)("h3", { children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Clock3, { size: 16 }), " Recent Events"] }), (0, jsx_runtime_1.jsxs)("ul", { className: "event-list", children: [activityItems.length === 0 && (0, jsx_runtime_1.jsx)("li", { className: "muted-event", children: "No tool activity yet" }), activityItems.slice(-8).reverse().map((item, index) => ((0, jsx_runtime_1.jsxs)("li", { children: [(0, jsx_runtime_1.jsx)("strong", { children: item.label }), (0, jsx_runtime_1.jsx)("span", { children: item.detail })] }, `${item.label}-${index}`)))] })] })] }), (0, jsx_runtime_1.jsxs)("div", { className: "composer", children: [(0, jsx_runtime_1.jsx)("textarea", { value: prompt, onChange: (event) => setPrompt(event.target.value), placeholder: "Ask pp-Echo what to do next" }), (0, jsx_runtime_1.jsx)("button", { disabled: !activeSessionId || !prompt.trim() || Boolean(activeApproval), onClick: sendPrompt, children: (0, jsx_runtime_1.jsx)(lucide_react_1.Play, { size: 17 }) })] })] })) : activeTab?.type === "projects" ? ((0, jsx_runtime_1.jsx)(ProjectsView, { workspaceDraft: workspaceDraft, workspaces: workspaces, pendingWorkspace: pendingWorkspace, onChangeDraft: setWorkspaceDraft, onOpenWorkspace: (path) => openWorkspace(path), onConfirmWorkspace: () => pendingWorkspace?.candidate && openWorkspace(pendingWorkspace.candidate.path, true), onCancelConfirmation: () => setPendingWorkspace(null), onReload: () => api_1.api.workspaces().then((data) => { setWorkspaces(data); setSideData((current) => ({ ...current, projects: data })); }) })) : activeTab ? ((0, jsx_runtime_1.jsx)(PanelView, { type: activeTab.type, data: sideData[activeTab.type], onReload: () => loadPanel(activeTab.type) })) : ((0, jsx_runtime_1.jsxs)("div", { className: "empty full", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Sparkles, { size: 30 }), (0, jsx_runtime_1.jsx)("h2", { children: "Select or create a session" })] })) })] })] }));
}
function ProjectsView({ workspaceDraft, workspaces, pendingWorkspace, onChangeDraft, onOpenWorkspace, onConfirmWorkspace, onCancelConfirmation, onReload }) {
    return ((0, jsx_runtime_1.jsxs)("section", { className: "projects-page", children: [(0, jsx_runtime_1.jsxs)("header", { children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("h2", { children: "Projects" }), (0, jsx_runtime_1.jsx)("p", { children: workspaces.active.path })] }), (0, jsx_runtime_1.jsxs)("button", { onClick: onReload, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.RefreshCw, { size: 16 }), " Reload"] })] }), (0, jsx_runtime_1.jsxs)("div", { className: "workspace-open", children: [(0, jsx_runtime_1.jsx)("input", { value: workspaceDraft, onChange: (event) => onChangeDraft(event.target.value), onKeyDown: (event) => {
                            if (event.key === "Enter")
                                onOpenWorkspace(workspaceDraft);
                        }, placeholder: "E:\\\\Projects\\\\my-app" }), (0, jsx_runtime_1.jsxs)("button", { onClick: () => onOpenWorkspace(workspaceDraft), children: [(0, jsx_runtime_1.jsx)(lucide_react_1.FolderOpen, { size: 16 }), " Open"] })] }), pendingWorkspace?.candidate && ((0, jsx_runtime_1.jsxs)("div", { className: "confirm-workspace", children: [(0, jsx_runtime_1.jsx)(lucide_react_1.AlertTriangle, { size: 18 }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("strong", { children: "Open this workspace?" }), (0, jsx_runtime_1.jsx)("span", { children: pendingWorkspace.candidate.path })] }), (0, jsx_runtime_1.jsxs)("button", { onClick: onConfirmWorkspace, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Check, { size: 15 }), " Confirm"] }), (0, jsx_runtime_1.jsxs)("button", { onClick: onCancelConfirmation, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.X, { size: 15 }), " Cancel"] })] })), (0, jsx_runtime_1.jsxs)("div", { className: "project-grid", children: [(0, jsx_runtime_1.jsx)(WorkspaceTile, { label: "Current", workspace: workspaces.active, active: true, onOpen: onOpenWorkspace }), workspaces.recent
                        .filter((item) => item.path !== workspaces.active.path)
                        .map((item) => (0, jsx_runtime_1.jsx)(WorkspaceTile, { label: "Recent", workspace: item, onOpen: onOpenWorkspace }, item.path))] })] }));
}
function WorkspaceTile({ label, workspace, active = false, onOpen }) {
    return ((0, jsx_runtime_1.jsxs)("button", { className: active ? "project-tile active" : "project-tile", onClick: () => onOpen(workspace.path), children: [(0, jsx_runtime_1.jsx)("div", { className: "project-icon", children: (0, jsx_runtime_1.jsx)(lucide_react_1.FolderOpen, { size: 18 }) }), (0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("small", { children: label }), (0, jsx_runtime_1.jsx)("strong", { children: workspace.name }), (0, jsx_runtime_1.jsx)("span", { children: workspace.path })] }), (0, jsx_runtime_1.jsx)("em", { children: workspace.has_agents ? "AGENTS.md" : workspace.has_pp_agent ? ".pp-agent" : "folder" })] }));
}
function PanelView({ type, data, onReload }) {
    if (type === "usage" && data && typeof data === "object") {
        const report = data;
        return ((0, jsx_runtime_1.jsxs)("section", { className: "panel-page", children: [(0, jsx_runtime_1.jsxs)("header", { children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("h2", { children: panelTitle(type) }), (0, jsx_runtime_1.jsx)("p", { children: panelSubtitle(type) })] }), (0, jsx_runtime_1.jsxs)("button", { onClick: onReload, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.RefreshCw, { size: 16 }), " Reload"] })] }), (0, jsx_runtime_1.jsxs)("div", { className: "panel-card", children: [(0, jsx_runtime_1.jsxs)("h3", { children: [(0, jsx_runtime_1.jsx)(lucide_react_1.Activity, { size: 16 }), " Runtime Doctor"] }), (0, jsx_runtime_1.jsxs)("dl", { children: [(0, jsx_runtime_1.jsx)("dt", { children: "Status" }), (0, jsx_runtime_1.jsx)("dd", { children: report.status }), (0, jsx_runtime_1.jsx)("dt", { children: "Sessions" }), (0, jsx_runtime_1.jsx)("dd", { children: report.summary?.session_count ?? 0 }), (0, jsx_runtime_1.jsx)("dt", { children: "Pending" }), (0, jsx_runtime_1.jsx)("dd", { children: report.summary?.pending_action_count ?? 0 }), (0, jsx_runtime_1.jsx)("dt", { children: "Artifacts" }), (0, jsx_runtime_1.jsx)("dd", { children: report.summary?.pending_artifact_count ?? 0 }), (0, jsx_runtime_1.jsx)("dt", { children: "Findings" }), (0, jsx_runtime_1.jsx)("dd", { children: report.summary?.finding_count ?? 0 })] }), Array.isArray(report.sessions) && report.sessions.length > 0 && ((0, jsx_runtime_1.jsx)("ul", { className: "event-list", children: report.sessions.slice(0, 6).map((session) => ((0, jsx_runtime_1.jsxs)("li", { children: [(0, jsx_runtime_1.jsx)("strong", { children: shortId(session.session_id) }), (0, jsx_runtime_1.jsxs)("span", { children: [session.status, " \u8DEF artifacts ", session.pending_artifact_count] })] }, session.session_id))) })), Array.isArray(report.findings) && report.findings.length > 0 && ((0, jsx_runtime_1.jsx)("pre", { children: JSON.stringify(report.findings, null, 2) }))] })] }));
    }
    return ((0, jsx_runtime_1.jsxs)("section", { className: "panel-page", children: [(0, jsx_runtime_1.jsxs)("header", { children: [(0, jsx_runtime_1.jsxs)("div", { children: [(0, jsx_runtime_1.jsx)("h2", { children: panelTitle(type) }), (0, jsx_runtime_1.jsx)("p", { children: panelSubtitle(type) })] }), (0, jsx_runtime_1.jsxs)("button", { onClick: onReload, children: [(0, jsx_runtime_1.jsx)(lucide_react_1.RefreshCw, { size: 16 }), " Reload"] })] }), (0, jsx_runtime_1.jsx)("pre", { children: JSON.stringify(data || {}, null, 2) })] }));
}
function buildTranscript(snapshot, events = []) {
    const committedMessages = snapshot?.messages || [];
    const stored = committedMessages
        .filter((message) => message.role === "user" || message.role === "assistant")
        .map((message, index) => ({
        id: `stored:${index}`,
        role: message.role,
        body: (0, rich_text_1.extractMessageBody)(message)
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
    let streamBuffer = "";
    let streamIndex = 0;
    const flushStream = () => {
        const text = streamBuffer.trim();
        streamBuffer = "";
        if (!text)
            return;
        const normalized = normalizeText(text);
        const alreadyCommitted = committedAssistants.some((committed) => committed.includes(normalized) || normalized.includes(committed));
        if (!alreadyCommitted) {
            runtime.push({ id: `stream:${streamIndex++}`, role: "assistant", body: { text, attachments: [] }, streaming: true });
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
                runtime.push({ id: `local-user:${runtime.length}`, role: "user", body: { text, attachments: [] } });
            }
            continue;
        }
        if (event.type === "turn_end" || event.type === "agent_end" || event.type === "agent_start") {
            flushStream();
            continue;
        }
        if (event.is_error && event.message) {
            flushStream();
            runtime.push({ id: `error:${runtime.length}`, role: "error", body: { text: event.message, attachments: [] } });
            continue;
        }
        if (event.type.includes("tool")) {
            flushStream();
        }
    }
    flushStream();
    const items = [...stored, ...runtime];
    if (shouldShowThinking(items, events)) {
        items.push({ id: "thinking", role: "assistant", body: { text: "Thinking", attachments: [] }, streaming: true });
    }
    return items;
}
function normalizeText(value) {
    return value.replace(/\s+/g, " ").trim();
}
function shouldShowThinking(items, events) {
    if (!isTurnInFlight(events))
        return false;
    const latestUserIndex = findLastIndex(items, (item) => item.role === "user");
    if (latestUserIndex < 0)
        return true;
    return !items.slice(latestUserIndex + 1).some((item) => item.role === "assistant" && item.body.text.trim() && item.id !== "thinking");
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
        if (event.type === "local_user_prompt" || event.type === "agent_start" || event.type === "turn_start") {
            inFlight = true;
        }
        if (event.type === "turn_end" || event.type === "agent_end" || event.type === "error") {
            inFlight = false;
        }
    }
    return inFlight;
}
function latestTerminalEvent(events) {
    for (let index = events.length - 1; index >= 0; index -= 1) {
        const event = events[index];
        if (event.type === "turn_end" || event.type === "agent_end" || event.type === "error" || event.is_error) {
            return event;
        }
    }
    return undefined;
}
function hasErrorSinceLatestStart(events) {
    const latestStart = findLastIndex(events, (event) => event.type === "local_user_prompt" || event.type === "agent_start" || event.type === "turn_start");
    return events.slice(Math.max(0, latestStart)).some((event) => event.type === "error" || event.is_error);
}
function buildActivityItems(events) {
    const toolStarts = new Map();
    return events
        .filter((event) => event.type.includes("tool") ||
        event.type.includes("planner") ||
        event.type.includes("checkpoint") ||
        event.type.includes("subagent") ||
        event.type === "cancel_requested")
        .map((event) => {
        const key = toolEventKey(event);
        if (event.type === "tool_start" && key)
            toolStarts.set(key, event);
        return {
            label: event.tool_name || eventLabel(event),
            detail: summarizeEvent(event, key ? toolStarts.get(key) : undefined)
        };
    });
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
function findLastIndex(items, predicate) {
    for (let index = items.length - 1; index >= 0; index -= 1) {
        if (predicate(items[index]))
            return index;
    }
    return -1;
}
function buildActiveApproval(snapshot, events, summary) {
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
function approvalEmptyText(busy, workspaceApprovalCount) {
    if (busy)
        return "Plan accepted. Waiting for model output or an exact action confirmation.";
    if (workspaceApprovalCount > 0)
        return `${workspaceApprovalCount} pending approval(s) exist in this workspace. Open Usage to review old items.`;
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
        return changedPaths.length > 0
            ? `Patch applied successfully: ${changedPaths.join(", ")}`
            : "Patch artifact applied successfully.";
    }
    const path = result.details?.absolute_path || result.details?.path;
    if (actionType === "write_file" || actionType === "edit_file") {
        return typeof path === "string" && path.trim() ? `Applied successfully: ${path}` : "Applied successfully.";
    }
    if (actionType === "run_shell")
        return "Command completed.";
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
function panelTitle(type) {
    if (type === "agents")
        return "Agents / Subagents";
    if (type === "mcp")
        return "MCP Manager";
    if (type === "usage")
        return "Usage Dashboard";
    if (type === "timeline")
        return "Timeline & Checkpoints";
    return "Settings";
}
function panelSubtitle(type) {
    if (type === "agents")
        return "Discover built-in tools, skills, extensions, and subagent-facing capabilities.";
    if (type === "mcp")
        return "Inspect Model Context Protocol configuration for this workspace.";
    if (type === "usage")
        return "Runtime status and approval workload for the current workspace.";
    if (type === "timeline")
        return "Session tree, rewind targets, and checkpoint-oriented state.";
    return "Active pp-Echo configuration resolved from environment and project files.";
}
