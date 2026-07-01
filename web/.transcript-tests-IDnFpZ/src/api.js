"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.api = void 0;
async function request(path, init) {
    const headers = init?.body instanceof FormData ? init?.headers || {} : { "Content-Type": "application/json", ...(init?.headers || {}) };
    const response = await fetch(path, {
        ...init,
        headers
    });
    if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        const detail = payload.detail;
        if (detail && typeof detail === "object") {
            const message = typeof detail.message === "string" ? detail.message : JSON.stringify(detail);
            const errorId = typeof detail.error_id === "string" ? ` (${detail.error_id})` : "";
            throw new Error(`${message}${errorId}`);
        }
        throw new Error(detail || response.statusText);
    }
    return response.json();
}
exports.api = {
    health: () => request("/api/health"),
    workspace: () => request("/api/workspace"),
    workspaceStatus: () => request("/api/workspace/status"),
    workspaceGit: () => request("/api/workspace/git"),
    switchGitBranch: (branch) => request("/api/workspace/git/switch", {
        method: "POST",
        body: JSON.stringify({ branch })
    }),
    createGitBranch: (branch) => request("/api/workspace/git/branches", {
        method: "POST",
        body: JSON.stringify({ branch })
    }),
    onboardingStatus: () => request("/api/onboarding/status"),
    onboardingCheckModel: () => request("/api/onboarding/check-model", { method: "POST" }),
    modelProviders: () => request("/api/models/providers"),
    modelUsage: () => request("/api/models/usage"),
    modelTest: (provider, model) => request("/api/models/test", {
        method: "POST",
        body: JSON.stringify({ provider, model })
    }),
    applyModelPreset: (providerId, model, baseHash) => request("/api/models/apply-preset", {
        method: "POST",
        body: JSON.stringify({ provider_id: providerId, model, base_hash: baseHash })
    }),
    workspaces: () => request("/api/workspaces"),
    bots: () => request("/api/bots"),
    botDetail: (botId) => request(`/api/bots/${encodeURIComponent(botId)}`),
    botHealth: (botId) => request(`/api/bots/${encodeURIComponent(botId)}/health`),
    botEvents: (botId, afterId, limit = 100) => {
        const query = new URLSearchParams({ limit: String(limit) });
        if (afterId)
            query.set("after_id", afterId);
        return request(`/api/bots/${encodeURIComponent(botId)}/events?${query.toString()}`);
    },
    startBot: (botId) => request(`/api/bots/${encodeURIComponent(botId)}/start`, { method: "POST" }),
    stopBot: (botId, force = false) => request(`/api/bots/${encodeURIComponent(botId)}/stop${force ? "?force=true" : ""}`, { method: "POST" }),
    setBotPublicUrl: (botId, publicUrl) => request(`/api/bots/${encodeURIComponent(botId)}/public-url`, {
        method: "POST",
        body: JSON.stringify({ public_url: publicUrl })
    }),
    testBotWebhookVerify: (botId) => request(`/api/bots/${encodeURIComponent(botId)}/test-webhook-verify`, { method: "POST" }),
    openWorkspace: (path, confirmed = false) => request("/api/workspaces/open", {
        method: "POST",
        body: JSON.stringify({ path, confirmed })
    }),
    pickWorkspaceDirectory: () => request("/api/workspaces/pick-directory", {
        method: "POST"
    }),
    sessions: () => request("/api/sessions"),
    createSession: () => request("/api/sessions", { method: "POST" }),
    snapshot: (sessionId) => request(`/api/sessions/${sessionId}`),
    events: (sessionId) => request(`/api/sessions/${sessionId}/events`),
    timeline: (sessionId, limit = 80) => request(sessionId
        ? `/api/sessions/${encodeURIComponent(sessionId)}/timeline?limit=${limit}`
        : `/api/timeline?limit=${limit}`),
    traces: (params = {}) => {
        const query = new URLSearchParams();
        query.set("limit", String(params.limit || 50));
        if (params.sessionId)
            query.set("session_id", params.sessionId);
        return request(`/api/traces?${query.toString()}`);
    },
    latestTrace: (sessionId) => request(sessionId ? `/api/traces/latest?session_id=${encodeURIComponent(sessionId)}` : "/api/traces/latest"),
    traceDetail: (runId) => request(`/api/traces/${encodeURIComponent(runId)}`),
    sessionTraces: (sessionId, limit = 20) => request(`/api/sessions/${encodeURIComponent(sessionId)}/traces?limit=${limit}`),
    logs: (params = {}) => {
        const query = new URLSearchParams();
        if (params.level)
            query.set("level", params.level);
        if (params.source)
            query.set("source", params.source);
        if (params.sessionId)
            query.set("session_id", params.sessionId);
        if (params.search)
            query.set("search", params.search);
        query.set("limit", String(params.limit || 200));
        return request(`/api/logs?${query.toString()}`);
    },
    memoryStatus: () => request("/api/memory/status"),
    memorySearch: (query, scope = "auto", limit = 8) => request(`/api/memory/search?query=${encodeURIComponent(query)}&scope=${encodeURIComponent(scope)}&limit=${limit}`),
    memoryFiles: () => request("/api/memory/files"),
    memoryFile: (path, startLine, lineCount) => {
        const query = new URLSearchParams({ path });
        if (startLine)
            query.set("start_line", String(startLine));
        if (lineCount)
            query.set("line_count", String(lineCount));
        return request(`/api/memory/file?${query.toString()}`);
    },
    coreMemoryPending: () => request("/api/memory/core/pending"),
    coreMemoryActive: () => request("/api/memory/core/active"),
    coreMemorySnapshot: () => request("/api/memory/core/snapshot"),
    coreMemoryAudit: (memoryId, limit = 100) => {
        const query = new URLSearchParams({ limit: String(limit) });
        if (memoryId)
            query.set("memory_id", memoryId);
        return request(`/api/memory/core/audit?${query.toString()}`);
    },
    coreMemoryCompactPreview: () => request("/api/memory/core/compact-preview"),
    coreMemoryCompactApply: (reason = "web compaction") => request("/api/memory/core/compact-apply", {
        method: "POST",
        body: JSON.stringify({ actor: "web", reason })
    }),
    coreMemoryMergePreview: () => request("/api/memory/core/merge-preview"),
    coreMemoryMergeApply: (reason = "web merge") => request("/api/memory/core/merge-apply", {
        method: "POST",
        body: JSON.stringify({ actor: "web", reason })
    }),
    coreMemoryProviderStatus: () => request("/api/memory/core/provider/status"),
    approveCoreMemory: (memoryId, reason = "web approval") => request(`/api/memory/core/${encodeURIComponent(memoryId)}/approve`, {
        method: "POST",
        body: JSON.stringify({ actor: "web", reason })
    }),
    rejectCoreMemory: (memoryId, reason = "web rejection") => request(`/api/memory/core/${encodeURIComponent(memoryId)}/reject`, {
        method: "POST",
        body: JSON.stringify({ actor: "web", reason })
    }),
    archiveCoreMemory: (memoryId, reason = "web archive") => request(`/api/memory/core/${encodeURIComponent(memoryId)}/archive`, {
        method: "POST",
        body: JSON.stringify({ actor: "web", reason })
    }),
    tree: (sessionId) => request(`/api/sessions/${sessionId}/tree`),
    prompt: (sessionId, prompt) => request(`/api/sessions/${sessionId}/prompt`, {
        method: "POST",
        body: JSON.stringify({ prompt })
    }),
    continueSession: (sessionId) => request(`/api/sessions/${sessionId}/continue`, { method: "POST" }),
    approve: (sessionId) => request(`/api/sessions/${sessionId}/approve`, { method: "POST" }),
    reject: (sessionId) => request(`/api/sessions/${sessionId}/reject`, { method: "POST" }),
    cancel: (sessionId) => request(`/api/sessions/${sessionId}/cancel`, { method: "POST" }),
    approvals: () => request("/api/approvals"),
    runtimeReport: (sessionId) => request(sessionId ? `/api/runtime/report?session_id=${encodeURIComponent(sessionId)}` : "/api/runtime/report"),
    uploadAttachment: (sessionId, file) => {
        const body = new FormData();
        body.append("file", file);
        return request(`/api/sessions/${encodeURIComponent(sessionId)}/attachments`, { method: "POST", body });
    },
    listAttachments: (sessionId) => request(`/api/sessions/${encodeURIComponent(sessionId)}/attachments`),
    inspectAttachment: (sessionId, attachmentId) => request(`/api/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}`),
    searchAttachment: (sessionId, query, attachmentId, topK = 5, mode = "auto") => request(`/api/sessions/${encodeURIComponent(sessionId)}/attachments/search`, {
        method: "POST",
        body: JSON.stringify({ query, attachment_id: attachmentId, top_k: topK, mode })
    }),
    readAttachmentChunk: (sessionId, attachmentId, chunkId) => request(`/api/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}/chunks/${encodeURIComponent(chunkId)}`),
    readAttachmentText: (sessionId, attachmentId, offset = 0, maxChars = 30000) => request(`/api/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}/text`, {
        method: "POST",
        body: JSON.stringify({ offset, max_chars: maxChars })
    }),
    readAttachmentRange: (sessionId, attachmentId, startLine, endLine) => request(`/api/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}/range`, {
        method: "POST",
        body: JSON.stringify({ start_line: startLine, end_line: endLine })
    }),
    deleteAttachment: (sessionId, attachmentId) => request(`/api/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}`, { method: "DELETE" }),
    previewAttachmentImport: (sessionId, attachmentId, targetPath, overwrite = false) => request(`/api/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}/import/preview`, {
        method: "POST",
        body: JSON.stringify({ target_path: targetPath, overwrite })
    }),
    requestAttachmentImport: (sessionId, attachmentId, targetPath, overwrite = false) => request(`/api/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}/import`, {
        method: "POST",
        body: JSON.stringify({ target_path: targetPath, overwrite })
    }),
    previewAttachmentMemoryIngest: (sessionId, attachmentId) => request(`/api/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}/ingest-memory/preview`, { method: "POST" }),
    ingestAttachmentMemory: (sessionId, attachmentId, chunkIds, tags, scope = "workspace") => request(`/api/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}/ingest-memory`, {
        method: "POST",
        body: JSON.stringify({ mode: chunkIds.length ? "selected_chunks" : "all_chunks", chunk_ids: chunkIds, max_chunks: 100, tags, scope })
    }),
    readAttachmentSymbol: (sessionId, attachmentId, symbolId) => request(`/api/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}/symbols/${encodeURIComponent(symbolId)}`),
    approvePending: (token) => request(`/api/approvals/${encodeURIComponent(token)}/approve`, { method: "POST" }),
    rejectPending: (token) => request(`/api/approvals/${encodeURIComponent(token)}/reject`, { method: "POST" }),
    capabilities: () => request("/api/capabilities"),
    capabilityConfig: () => request("/api/capability-config"),
    capabilitySettingsPatch: (capabilities) => request("/api/capability-config/settings", {
        method: "PATCH",
        body: JSON.stringify({ capabilities })
    }),
    createMcpServer: (payload) => request("/api/mcp/servers", { method: "POST", body: JSON.stringify(payload) }),
    updateMcpServer: (name, payload) => request(`/api/mcp/servers/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify(payload) }),
    deleteMcpServer: (name) => request(`/api/mcp/servers/${encodeURIComponent(name)}`, { method: "DELETE" }),
    createSkill: (payload) => request("/api/skills", { method: "POST", body: JSON.stringify(payload) }),
    getSkill: (name) => request(`/api/skills/${encodeURIComponent(name)}`),
    updateSkill: (name, payload) => request(`/api/skills/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify(payload) }),
    createPlugin: (payload) => request("/api/plugins", { method: "POST", body: JSON.stringify(payload) }),
    updatePlugin: (name, payload) => request(`/api/plugins/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify(payload) }),
    mcp: () => request("/api/mcp"),
    settings: () => request("/api/settings"),
    sandboxStatus: (sessionId) => request(sessionId ? `/api/sandbox/status?session_id=${encodeURIComponent(sessionId)}` : "/api/sandbox/status"),
    config: (sessionId) => request(sessionId ? `/api/config?session_id=${encodeURIComponent(sessionId)}` : "/api/config"),
    configSet: (path, value, baseHash) => request("/api/config/set", {
        method: "POST",
        body: JSON.stringify({ path, value, base_hash: baseHash })
    }),
    configPatch: (patch, baseHash) => request("/api/config", {
        method: "PATCH",
        body: JSON.stringify({ patch, base_hash: baseHash })
    }),
    setProjectProfile: (profile, baseHash, sessionId) => request("/api/config/profile", {
        method: "POST",
        body: JSON.stringify({ profile, base_hash: baseHash, session_id: sessionId })
    }),
    configProfileSet: (profile, path, value, baseHash, sessionId) => request("/api/config/profile/set", {
        method: "POST",
        body: JSON.stringify({ profile, path, value, base_hash: baseHash, session_id: sessionId })
    }),
    sessionConfigSet: (sessionId, path, value) => request(`/api/sessions/${encodeURIComponent(sessionId)}/config/set`, {
        method: "POST",
        body: JSON.stringify({ path, value })
    }),
    setSessionProfile: (sessionId, profile) => request(`/api/sessions/${encodeURIComponent(sessionId)}/profile`, {
        method: "POST",
        body: JSON.stringify({ profile })
    }),
    setSessionModel: (sessionId, model, providerId) => request(`/api/sessions/${encodeURIComponent(sessionId)}/model`, {
        method: "POST",
        body: JSON.stringify({ model, provider_id: providerId })
    }),
    debugSet: (path, value, sessionId) => request("/api/debug/set", {
        method: "POST",
        body: JSON.stringify({ path, value, session_id: sessionId })
    }),
    sessionTools: (sessionId) => request(`/api/sessions/${encodeURIComponent(sessionId)}/tools`)
};
