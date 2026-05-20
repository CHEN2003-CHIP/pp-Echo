"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.api = void 0;
async function request(path, init) {
    const response = await fetch(path, {
        headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
        ...init
    });
    if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || response.statusText);
    }
    return response.json();
}
exports.api = {
    health: () => request("/api/health"),
    workspace: () => request("/api/workspace"),
    workspaces: () => request("/api/workspaces"),
    openWorkspace: (path, confirmed = false) => request("/api/workspaces/open", {
        method: "POST",
        body: JSON.stringify({ path, confirmed })
    }),
    sessions: () => request("/api/sessions"),
    createSession: () => request("/api/sessions", { method: "POST" }),
    snapshot: (sessionId) => request(`/api/sessions/${sessionId}`),
    events: (sessionId) => request(`/api/sessions/${sessionId}/events`),
    tree: (sessionId) => request(`/api/sessions/${sessionId}/tree`),
    prompt: (sessionId, prompt) => request(`/api/sessions/${sessionId}/prompt`, {
        method: "POST",
        body: JSON.stringify({ prompt })
    }),
    approve: (sessionId) => request(`/api/sessions/${sessionId}/approve`, { method: "POST" }),
    reject: (sessionId) => request(`/api/sessions/${sessionId}/reject`, { method: "POST" }),
    cancel: (sessionId) => request(`/api/sessions/${sessionId}/cancel`, { method: "POST" }),
    approvals: () => request("/api/approvals"),
    runtimeReport: (sessionId) => request(sessionId ? `/api/runtime/report?session_id=${encodeURIComponent(sessionId)}` : "/api/runtime/report"),
    approvePending: (token) => request(`/api/approvals/${encodeURIComponent(token)}/approve`, { method: "POST" }),
    rejectPending: (token) => request(`/api/approvals/${encodeURIComponent(token)}/reject`, { method: "POST" }),
    capabilities: () => request("/api/capabilities"),
    mcp: () => request("/api/mcp"),
    settings: () => request("/api/settings")
};
