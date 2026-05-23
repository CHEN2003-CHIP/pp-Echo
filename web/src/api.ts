export type MessageAttachment = {
  url: string;
  alt?: string;
  title?: string;
  mime_type?: string;
  kind?: "image" | "file";
  name?: string;
};

export type MessageContentPart =
  | { type: "text"; text: string }
  | { type: "tool_call"; id: string; name: string; arguments?: Record<string, unknown> }
  | { type: "image"; url: string; alt?: string; title?: string; mime_type?: string }
  | { type: string; [key: string]: unknown };

export type SnapshotMessage = {
  role: string;
  content: MessageContentPart[];
  timestamp?: number;
  tool_call_id?: string | null;
  tool_name?: string | null;
  metadata?: {
    attachments?: Array<string | MessageAttachment | Record<string, unknown>>;
    images?: Array<string | MessageAttachment | Record<string, unknown>>;
    [key: string]: unknown;
  };
};

export type SessionEntry = {
  id: string;
  parent_id?: string | null;
  updated_at: number;
  model: string;
  message_count: number;
  turn_count: number;
  pending_plan_token?: string | null;
  active_head_id?: string | null;
  summary_preview?: string;
  last_user_preview?: string;
  last_assistant_preview?: string;
};

export type RuntimeEvent = {
  type: string;
  session_id: string;
  turn_id?: number | null;
  phase?: string | null;
  timestamp?: number;
  message?: string | null;
  delta?: string | null;
  tool_name?: string | null;
  tool_args?: Record<string, unknown> | null;
  plan_step?: { title: string; tool_name?: string | null; status?: string } | null;
  details?: Record<string, unknown>;
  is_error?: boolean;
};

export type SessionSnapshot = {
  session_id: string;
  busy: boolean;
  cancel_requested?: boolean;
  pending_plan_token?: string | null;
  pending_tool_call_count: number;
  queued_message_count: number;
  turn?: { phase?: string | null; reason?: string | null };
  pending_artifacts?: Array<{
    token: string;
    session_id?: string;
    workflow?: string;
    artifact_id?: string;
    changed_paths?: string[];
    lifecycle_state?: string;
  }>;
  history?: {
    source?: "active" | "stored";
    message_count?: number;
    visible_message_count?: number;
    returned_message_count?: number;
    truncated?: boolean;
    max_messages?: number;
    max_total_text_chars?: number;
  };
  runtime_control?: {
    status?: string;
    pending_artifact_count?: number;
    pending_artifacts?: Array<{ token: string; changed_paths?: string[] }>;
  };
  messages: SnapshotMessage[];
};

export type PendingAction = {
  token: string;
  action_type: string;
  target_path?: string | null;
  command?: string | null;
  created_at?: number;
  details?: Record<string, unknown>;
  lifecycle?: { state?: string } | null;
};

export type ApprovalsSummary = {
  count: number;
  by_type?: Record<string, number>;
  tokens?: string[];
  items: PendingAction[];
};

export type ApprovalActionResponse = {
  token: string;
  action_type: string;
  result: string;
  success?: boolean;
  lifecycle?: { state?: string } | null;
  details?: Record<string, unknown>;
};

export type WorkspaceEntry = {
  path: string;
  name: string;
  exists: boolean;
  is_dir: boolean;
  has_agents?: boolean;
  has_pp_agent?: boolean;
  last_opened_at?: number;
};

export type WorkspacesState = {
  active: WorkspaceEntry;
  recent: WorkspaceEntry[];
};

export type WorkspaceStatus = {
  path: string;
  name: string;
  git_branch?: string;
};

export type RuntimeDoctorReport = {
  workspace: string;
  status: string;
  session_id?: string | null;
  summary: {
    session_count: number;
    pending_action_count: number;
    pending_artifact_count: number;
    finding_count: number;
  };
  sessions: Array<{
    session_id: string;
    pending_plan_token?: string | null;
    pending_artifact_count: number;
    status: string;
  }>;
  pending_artifacts: Array<{
    token: string;
    session_id?: string;
    workflow?: string;
    artifact_id?: string;
    changed_paths?: string[];
    lifecycle_state?: string;
  }>;
  findings: Array<Record<string, unknown>>;
};

export type TimelineEntry = {
  id: string;
  session_id: string;
  created_at: number;
  event_type: string;
  turn_id?: number;
  phase?: string | null;
  tool_name?: string | null;
  message?: string | null;
  is_error?: boolean;
  details?: Record<string, unknown>;
};

export type OpenWorkspaceResponse = WorkspacesState & {
  requires_confirmation: boolean;
  candidate?: WorkspaceEntry | null;
};

export type ConfigField = {
  path: string;
  type: string;
  category: string;
  reload_policy: "hot" | "next_turn" | "rebuild_runtime" | "restart_required";
  description?: string;
  session_override?: boolean;
  runtime_override?: boolean;
  editor?: string;
  options?: string[];
  minimum?: number | null;
  maximum?: number | null;
  item_type?: string;
};

export type ConfigSnapshot = {
  settings: Record<string, unknown>;
  project_config: Record<string, unknown>;
  profile_config: Record<string, unknown>;
  session_config: Record<string, unknown>;
  runtime_config: Record<string, unknown>;
  effective_config: Record<string, unknown>;
  config_hash: string;
  effective_hash: string;
  config_version: string;
  reload_policy: string;
  pending_effects: string[];
  source_map: Record<string, string>;
  active_profile?: string | null;
  profiles: string[];
  schema: { fields: ConfigField[]; categories: string[] };
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload.detail;
    if (detail && typeof detail === "object") {
      throw new Error(JSON.stringify(detail));
    }
    throw new Error(detail || response.statusText);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<{ ok: boolean; workspace: string }>("/api/health"),
  workspace: () => request<{ path: string; name: string }>("/api/workspace"),
  workspaceStatus: () => request<WorkspaceStatus>("/api/workspace/status"),
  workspaces: () => request<WorkspacesState>("/api/workspaces"),
  openWorkspace: (path: string, confirmed = false) =>
    request<OpenWorkspaceResponse>("/api/workspaces/open", {
      method: "POST",
      body: JSON.stringify({ path, confirmed })
    }),
  sessions: () => request<{ sessions: SessionEntry[] }>("/api/sessions"),
  createSession: () => request<SessionSnapshot>("/api/sessions", { method: "POST" }),
  snapshot: (sessionId: string) => request<SessionSnapshot>(`/api/sessions/${sessionId}`),
  events: (sessionId: string) => request<{ events: RuntimeEvent[] }>(`/api/sessions/${sessionId}/events`),
  timeline: (sessionId?: string, limit = 80) =>
    request<{ timeline: TimelineEntry[] }>(
      sessionId
        ? `/api/sessions/${encodeURIComponent(sessionId)}/timeline?limit=${limit}`
        : `/api/timeline?limit=${limit}`
    ),
  tree: (sessionId: string) => request<Record<string, unknown>>(`/api/sessions/${sessionId}/tree`),
  prompt: (sessionId: string, prompt: string) =>
    request<{ session_id: string; queued: boolean }>(`/api/sessions/${sessionId}/prompt`, {
      method: "POST",
      body: JSON.stringify({ prompt })
    }),
  approve: (sessionId: string) => request(`/api/sessions/${sessionId}/approve`, { method: "POST" }),
  reject: (sessionId: string) => request(`/api/sessions/${sessionId}/reject`, { method: "POST" }),
  cancel: (sessionId: string) => request(`/api/sessions/${sessionId}/cancel`, { method: "POST" }),
  approvals: () => request<ApprovalsSummary>("/api/approvals"),
  runtimeReport: (sessionId?: string) =>
    request<RuntimeDoctorReport>(sessionId ? `/api/runtime/report?session_id=${encodeURIComponent(sessionId)}` : "/api/runtime/report"),
  approvePending: (token: string) => request<ApprovalActionResponse>(`/api/approvals/${encodeURIComponent(token)}/approve`, { method: "POST" }),
  rejectPending: (token: string) => request(`/api/approvals/${encodeURIComponent(token)}/reject`, { method: "POST" }),
  capabilities: () => request<{ capabilities: unknown[] }>("/api/capabilities"),
  mcp: () => request<Record<string, unknown>>("/api/mcp"),
  settings: () => request<Record<string, unknown>>("/api/settings"),
  config: (sessionId?: string) => request<ConfigSnapshot>(sessionId ? `/api/config?session_id=${encodeURIComponent(sessionId)}` : "/api/config"),
  configSet: (path: string, value: unknown, baseHash?: string) =>
    request<ConfigSnapshot>("/api/config/set", {
      method: "POST",
      body: JSON.stringify({ path, value, base_hash: baseHash })
    }),
  configPatch: (patch: Record<string, unknown>, baseHash?: string) =>
    request<ConfigSnapshot>("/api/config", {
      method: "PATCH",
      body: JSON.stringify({ patch, base_hash: baseHash })
    }),
  setProjectProfile: (profile: string | null, baseHash?: string, sessionId?: string) =>
    request<ConfigSnapshot>("/api/config/profile", {
      method: "POST",
      body: JSON.stringify({ profile, base_hash: baseHash, session_id: sessionId })
    }),
  configProfileSet: (profile: string, path: string, value: unknown, baseHash?: string, sessionId?: string) =>
    request<ConfigSnapshot>("/api/config/profile/set", {
      method: "POST",
      body: JSON.stringify({ profile, path, value, base_hash: baseHash, session_id: sessionId })
    }),
  sessionConfigSet: (sessionId: string, path: string, value: unknown) =>
    request<ConfigSnapshot>(`/api/sessions/${encodeURIComponent(sessionId)}/config/set`, {
      method: "POST",
      body: JSON.stringify({ path, value })
    }),
  setSessionProfile: (sessionId: string, profile: string | null) =>
    request<ConfigSnapshot>(`/api/sessions/${encodeURIComponent(sessionId)}/profile`, {
      method: "POST",
      body: JSON.stringify({ profile })
    }),
  setSessionModel: (sessionId: string, model: string) =>
    request<ConfigSnapshot & { pending_next_turn?: boolean }>(`/api/sessions/${encodeURIComponent(sessionId)}/model`, {
      method: "POST",
      body: JSON.stringify({ model })
    }),
  debugSet: (path: string, value: unknown, sessionId?: string) =>
    request<ConfigSnapshot>("/api/debug/set", {
      method: "POST",
      body: JSON.stringify({ path, value, session_id: sessionId })
    }),
  sessionTools: (sessionId: string) => request<Record<string, unknown>>(`/api/sessions/${encodeURIComponent(sessionId)}/tools`)
};
