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
  event_id?: string | null;
  run_id?: string | null;
  activity_id?: string | null;
  parent_activity_id?: string | null;
  status?: "pending" | "running" | "success" | "warning" | "error" | "cancelled" | string | null;
  started_at?: number | null;
  ended_at?: number | null;
  duration_ms?: number | null;
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
  active_count?: number;
  archived_count?: number;
  by_type?: Record<string, number>;
  tokens?: string[];
  items: PendingAction[];
  active_items?: PendingAction[];
  archived_items?: PendingAction[];
  state_counts?: Record<string, number>;
};

export type ApprovalActionResponse = {
  token: string;
  action_type: string;
  session_id?: string | null;
  turn_id?: string | number | null;
  tool_call_id?: string | null;
  source_tool_name?: string | null;
  result: string;
  success?: boolean;
  resumed?: boolean;
  event_count?: number;
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
  git_dirty_count?: number;
};

export type WorkspaceGitBranch = {
  name: string;
  current?: boolean;
  upstream?: string;
};

export type WorkspaceGitStatus = {
  is_repo: boolean;
  current_branch: string;
  branches: WorkspaceGitBranch[];
  dirty_count: number;
  untracked_count: number;
  ahead?: number;
  behind?: number;
  error?: string;
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

export type AttachmentRecord = {
  attachment_id: string;
  session_id: string;
  original_filename: string;
  stored_filename: string;
  relative_dir: string;
  content_type?: string | null;
  kind: string;
  size_bytes: number;
  sha256: string;
  created_at: number;
  status: string;
  text_preview?: string;
  extracted_text_path?: string | null;
  chunks_path?: string | null;
  index_path?: string | null;
  metadata?: Record<string, unknown>;
  error?: string | null;
};

export type AttachmentSearchResult = {
  chunk_id: string;
  attachment_id: string;
  filename: string;
  score: number;
  match_type: string;
  snippet: string;
  page_start?: number | null;
  page_end?: number | null;
  line_start?: number | null;
  line_end?: number | null;
  source_ref?: string | null;
  section_title?: string | null;
};

export type AttachmentChunkRead = {
  chunk: Record<string, unknown>;
  text: string;
  truncated: boolean;
};

export type AttachmentRangeRead = {
  attachment_id: string;
  filename: string;
  line_start: number;
  line_end: number;
  text: string;
  truncated: boolean;
};

export type AttachmentTextRead = {
  attachment_id: string;
  filename: string;
  offset: number;
  max_chars: number;
  text_length: number;
  returned_chars: number;
  next_offset?: number | null;
  truncated: boolean;
  text: string;
};

export type AttachmentImportPreview = {
  attachment_id: string;
  filename: string;
  target_path: string;
  would_overwrite: boolean;
  overwrite: boolean;
  size_bytes: number;
  sha256: string;
  requires_approval: boolean;
  effect_preview: { kind: string; path: string; digest: string };
  token?: string;
  approval_id?: string;
  staged?: boolean;
};

export type AttachmentMemoryPreview = {
  attachment_id: string;
  filename: string;
  chunk_count: number;
  estimated_memory_items: number;
  source_refs: string[];
  requires_confirmation: boolean;
};

export type AttachmentSymbolRead = {
  symbol: Record<string, unknown>;
  attachment_id: string;
  filename: string;
  source_ref: string;
  text: string;
  truncated: boolean;
};

export type OnboardingCheckStatus = "ok" | "warning" | "error" | "skipped";

export type OnboardingCheck = {
  id: string;
  title: string;
  status: OnboardingCheckStatus;
  summary: string;
  detail?: string;
  action_label?: string | null;
  action_command?: string | null;
  docs_hint?: string | null;
};

export type OnboardingStatus = {
  workspace: string;
  overall_status: "ready" | "partial" | "blocked";
  checks: OnboardingCheck[];
  command_hints: Array<{
    title: string;
    command: string;
    description?: string;
  }>;
  next_steps: Array<{
    title: string;
    description: string;
    action_label?: string | null;
    target_view?: string | null;
  }>;
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

export type TraceStatus = "running" | "ok" | "error" | "blocked" | "pending" | "cancelled";

export type TraceRunSummary = {
  schema_version: string;
  run_id: string;
  session_id?: string | null;
  turn_id?: string | number | null;
  workspace: string;
  user_goal_preview: string;
  status: TraceStatus;
  started_at: number;
  ended_at?: number | null;
  duration_ms?: number | null;
  provider?: string | null;
  model?: string | null;
  llm_calls: number;
  tool_calls: number;
  approval_count: number;
  memory_recall_count: number;
  checkpoint_count: number;
  subagent_count: number;
  error_count: number;
  blocked_count: number;
  pending_count: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_tokens: number;
  total_cost_usd?: number | null;
  llm_latency_ms_total?: number;
  llm_latency_ms_avg?: number | null;
  llm_retry_count?: number;
  tool_error_count?: number;
  tools_used?: string[];
  mcp_tool_calls?: number;
  subagent_tool_calls?: number;
  shell_tool_calls?: number;
  risk_level: "low" | "medium" | "high";
  changed_path_count: number;
  attributes?: Record<string, unknown>;
};

export type TraceSpan = {
  schema_version: string;
  run_id: string;
  span_id: string;
  parent_span_id?: string | null;
  session_id?: string | null;
  turn_id?: string | number | null;
  name: string;
  span_type: string;
  status: TraceStatus;
  started_at: number;
  ended_at?: number | null;
  duration_ms?: number | null;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  attributes: Record<string, unknown>;
  error_kind?: string | null;
  error_message?: string | null;
  redaction_applied?: boolean;
};

export type TraceEvent = {
  schema_version: string;
  run_id: string;
  event_id: string;
  name: string;
  timestamp: number;
  session_id?: string | null;
  turn_id?: string | number | null;
  span_id?: string | null;
  attributes: Record<string, unknown>;
  payload: Record<string, unknown>;
  redaction_applied?: boolean;
};

export type TraceDiagnosis = {
  code: string;
  severity: "info" | "warning" | "error";
  title: string;
  message: string;
  span_id?: string | null;
  attributes?: Record<string, unknown>;
};

export type TraceArtifact = {
  schema_version: string;
  run_id: string;
  artifact_id: string;
  artifact_type: string;
  path?: string | null;
  token?: string | null;
  preview: string;
  attributes: Record<string, unknown>;
};

export type TraceDetail = {
  run: Record<string, unknown> | null;
  summary: TraceRunSummary | null;
  spans: TraceSpan[];
  events: TraceEvent[];
  artifacts: TraceArtifact[];
  diagnosis: TraceDiagnosis[];
  warnings: string[];
};

export type LogEntry = {
  timestamp?: string | number | null;
  level: string;
  source: string;
  session_id?: string | null;
  message: string;
  details?: unknown;
  raw?: string;
};

export type CapabilityInventory = {
  workspace: string;
  capabilities?: {
    items: Array<Record<string, unknown>>;
    by_kind: Record<string, number>;
    count: number;
  };
  settings: {
    mcp: Record<string, unknown>;
    skills: Record<string, unknown>;
    plugins: Record<string, unknown>;
  };
  mcp: {
    enabled: boolean;
    config_paths: string[];
    settings: Record<string, unknown>;
    servers: Array<Record<string, unknown>>;
    errors: Array<{ path: string; code: string; message: string }>;
  };
  skills: {
    roots: Array<Record<string, unknown>>;
    items: Array<Record<string, unknown>>;
  };
  plugins: {
    roots: Array<Record<string, unknown>>;
    items: Array<Record<string, unknown>>;
  };
};

export type MemoryFileEntry = {
  path: string;
  mtime: number;
  size: number;
  content_hash: string;
  scope: string;
};

export type MemoryStatus = {
  workspace: string;
  enabled: boolean;
  episodic_memory_enabled?: boolean;
  episodic_history_enabled?: boolean;
  core_memory_enabled?: boolean;
  file_memory_enabled: boolean;
  search_enabled: boolean;
  memory_root: string;
  index_path: string;
  global_root: string;
  file_count: number;
  indexed_file_count: number;
  files: MemoryFileEntry[];
};

export type MemorySearchHit = {
  path: string;
  source_scope: string;
  line_start: number;
  line_end: number;
  score: number;
  vector_score: number;
  bm25_score: number;
  sources: string[];
  heading_path: string[];
  snippet: string;
};

export type MemorySearchResponse = {
  query: string;
  mode: string;
  semantic_available: boolean;
  bm25_available: boolean;
  results: MemorySearchHit[];
  warnings: string[];
};

export type MemoryFileRead = {
  path: string;
  line_start: number;
  line_end: number;
  content: string;
};

export type CoreMemoryRecord = {
  id: string;
  scope: "global" | "workspace" | string;
  workspace_id?: string | null;
  section: "user_profile" | "project_profile" | "agent_notes" | string;
  type: string;
  content: string;
  confidence: number;
  status: "pending" | "active" | "rejected" | "archived" | string;
  metadata?: Record<string, unknown>;
  created_at?: number;
  updated_at?: number;
};

export type CoreMemorySnapshot = {
  snapshot: string;
  workspace_id: string;
  session_id?: string | null;
  included_ids: string[];
  skipped_ids: string[];
  skipped_reasons: Record<string, string>;
  chars: number;
  snapshot_hash: string;
  budget: Record<string, unknown>;
};

export type CoreMemoryAuditRecord = {
  audit_id: string;
  memory_id: string;
  action: string;
  actor: string;
  before_status?: string | null;
  after_status?: string | null;
  reason: string;
  created_at: number;
  metadata?: Record<string, unknown>;
};

export type OpenWorkspaceResponse = WorkspacesState & {
  requires_confirmation: boolean;
  candidate?: WorkspaceEntry | null;
};

export type PickDirectoryResponse = {
  path?: string | null;
  cancelled: boolean;
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

export type ModelProviderPreset = {
  id: string;
  label: string;
  protocol: "openai-compatible" | "anthropic";
  default_base_url: string;
  default_api_key_env: string;
  recommended_models: string[];
  supports_thinking: boolean;
  supports_streaming: boolean;
  supports_tools: boolean;
  notes?: string;
};

export type ModelConnectivityResult = {
  provider: string;
  model: string;
  base_url: string;
  api_key_env: string;
  status: "ok" | "warning" | "error";
  latency_ms?: number | null;
  message: string;
  retryable: boolean;
  safe_detail: string;
};

export type ModelUsageRow = {
  provider_id: string;
  provider_label: string;
  model: string;
  base_url: string;
  api_key_env: string;
  api_key_configured: boolean;
  current: boolean;
  runs: number;
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  total_cost_usd?: number | null;
};

export type BotSummary = {
  id: string;
  type: string;
  platform: string;
  name: string;
  enabled: boolean;
  description?: string | null;
  desired_state?: string;
  process_state: string;
  agent_state?: string;
  bot_state: string;
  ingress_state: string;
  qq_state?: string;
  configured: boolean;
  last_event_at?: string | null;
  last_message_at?: string | null;
  last_error?: string | null;
  status_text: string;
  still_running_count?: number;
  queued_count?: number;
};

export type BotStatusDetail = {
  bot_id: string;
  type: string;
  platform: string;
  name: string;
  enabled: boolean;
  configured: boolean;
  desired_state?: string;
  process_state: string;
  agent_state?: string;
  ingress_state: string;
  qq_state?: string;
  bot_state: string;
  local_url?: string | null;
  public_url?: string | null;
  webhook_url?: string | null;
  bot_path: string;
  pid?: number | null;
  started_at?: string | null;
  last_heartbeat_at?: string | null;
  last_event_at?: string | null;
  last_message_at?: string | null;
  last_reply_at?: string | null;
  last_error?: string | null;
  last_run_at?: string | null;
  warnings?: string[];
  still_running_count?: number;
  queued_count?: number;
  effective_policy?: Record<string, unknown>;
};

export type BotDetail = {
  config: {
    id: string;
    type: string;
    platform: string;
    name: string;
    enabled: boolean;
    description?: string | null;
    adapter?: Record<string, unknown>;
    ingress?: Record<string, unknown>;
    routing?: Record<string, unknown>;
    security?: Record<string, unknown>;
  };
  status: BotStatusDetail;
  effective_status?: BotStatusDetail;
  webhook_url: string;
  paths: Record<string, string>;
  events: Array<Record<string, unknown>>;
  messages: Array<Record<string, unknown>>;
  runs: Array<Record<string, unknown>>;
  traces: Array<Record<string, unknown>>;
  logs: { bot: string[]; error: string[] };
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
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
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<{ ok: boolean; workspace: string }>("/api/health"),
  workspace: () => request<{ path: string; name: string }>("/api/workspace"),
  workspaceStatus: () => request<WorkspaceStatus>("/api/workspace/status"),
  workspaceGit: () => request<WorkspaceGitStatus>("/api/workspace/git"),
  switchGitBranch: (branch: string) =>
    request<WorkspaceGitStatus>("/api/workspace/git/switch", {
      method: "POST",
      body: JSON.stringify({ branch })
    }),
  createGitBranch: (branch: string) =>
    request<WorkspaceGitStatus>("/api/workspace/git/branches", {
      method: "POST",
      body: JSON.stringify({ branch })
    }),
  onboardingStatus: () => request<OnboardingStatus>("/api/onboarding/status"),
  onboardingCheckModel: () => request<OnboardingCheck>("/api/onboarding/check-model", { method: "POST" }),
  modelProviders: () => request<{ providers: ModelProviderPreset[] }>("/api/models/providers"),
  modelUsage: () => request<{ models: ModelUsageRow[] }>("/api/models/usage"),
  modelTest: (provider?: Record<string, unknown>, model?: Record<string, unknown>) =>
    request<ModelConnectivityResult>("/api/models/test", {
      method: "POST",
      body: JSON.stringify({ provider, model })
    }),
  applyModelPreset: (providerId: string, model?: string, baseHash?: string) =>
    request<ConfigSnapshot>("/api/models/apply-preset", {
      method: "POST",
      body: JSON.stringify({ provider_id: providerId, model, base_hash: baseHash })
    }),
  workspaces: () => request<WorkspacesState>("/api/workspaces"),
  bots: () => request<{ bots: BotSummary[] }>("/api/bots"),
  botDetail: (botId: string) => request<BotDetail>(`/api/bots/${encodeURIComponent(botId)}`),
  botHealth: (botId: string) => request<{ effective_status: BotStatusDetail }>(`/api/bots/${encodeURIComponent(botId)}/health`),
  botEvents: (botId: string, afterId?: string, limit = 100) => {
    const query = new URLSearchParams({ limit: String(limit) });
    if (afterId) query.set("after_id", afterId);
    return request<{ events: Array<Record<string, unknown>> }>(`/api/bots/${encodeURIComponent(botId)}/events?${query.toString()}`);
  },
  startBot: (botId: string) => request<BotDetail>(`/api/bots/${encodeURIComponent(botId)}/start`, { method: "POST" }),
  stopBot: (botId: string, force = false) => request<BotDetail>(`/api/bots/${encodeURIComponent(botId)}/stop${force ? "?force=true" : ""}`, { method: "POST" }),
  setBotPublicUrl: (botId: string, publicUrl: string) =>
    request<BotDetail>(`/api/bots/${encodeURIComponent(botId)}/public-url`, {
      method: "POST",
      body: JSON.stringify({ public_url: publicUrl })
    }),
  testBotWebhookVerify: (botId: string) => request<Record<string, string>>(`/api/bots/${encodeURIComponent(botId)}/test-webhook-verify`, { method: "POST" }),
  openWorkspace: (path: string, confirmed = false) =>
    request<OpenWorkspaceResponse>("/api/workspaces/open", {
      method: "POST",
      body: JSON.stringify({ path, confirmed })
    }),
  pickWorkspaceDirectory: () =>
    request<PickDirectoryResponse>("/api/workspaces/pick-directory", {
      method: "POST"
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
  traces: (params: { limit?: number; sessionId?: string } = {}) => {
    const query = new URLSearchParams();
    query.set("limit", String(params.limit || 50));
    if (params.sessionId) query.set("session_id", params.sessionId);
    return request<{ runs: TraceRunSummary[] }>(`/api/traces?${query.toString()}`);
  },
  latestTrace: (sessionId?: string) =>
    request<TraceRunSummary>(sessionId ? `/api/traces/latest?session_id=${encodeURIComponent(sessionId)}` : "/api/traces/latest"),
  traceDetail: (runId: string) => request<TraceDetail>(`/api/traces/${encodeURIComponent(runId)}`),
  sessionTraces: (sessionId: string, limit = 20) =>
    request<{ runs: TraceRunSummary[] }>(`/api/sessions/${encodeURIComponent(sessionId)}/traces?limit=${limit}`),
  logs: (params: { level?: string; source?: string; sessionId?: string; search?: string; limit?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.level) query.set("level", params.level);
    if (params.source) query.set("source", params.source);
    if (params.sessionId) query.set("session_id", params.sessionId);
    if (params.search) query.set("search", params.search);
    query.set("limit", String(params.limit || 200));
    return request<{ logs: LogEntry[]; sources: string[] }>(`/api/logs?${query.toString()}`);
  },
  memoryStatus: () => request<MemoryStatus>("/api/memory/status"),
  memorySearch: (query: string, scope = "auto", limit = 8) =>
    request<MemorySearchResponse>(`/api/memory/search?query=${encodeURIComponent(query)}&scope=${encodeURIComponent(scope)}&limit=${limit}`),
  memoryFiles: () => request<{ files: MemoryFileEntry[] }>("/api/memory/files"),
  memoryFile: (path: string, startLine?: number, lineCount?: number) => {
    const query = new URLSearchParams({ path });
    if (startLine) query.set("start_line", String(startLine));
    if (lineCount) query.set("line_count", String(lineCount));
    return request<MemoryFileRead>(`/api/memory/file?${query.toString()}`);
  },
  coreMemoryPending: () => request<{ pending: CoreMemoryRecord[] }>("/api/memory/core/pending"),
  coreMemoryActive: () => request<{ active: CoreMemoryRecord[] }>("/api/memory/core/active"),
  coreMemorySnapshot: () => request<CoreMemorySnapshot>("/api/memory/core/snapshot"),
  coreMemoryAudit: (memoryId?: string, limit = 100) => {
    const query = new URLSearchParams({ limit: String(limit) });
    if (memoryId) query.set("memory_id", memoryId);
    return request<{ audit: CoreMemoryAuditRecord[] }>(`/api/memory/core/audit?${query.toString()}`);
  },
  coreMemoryCompactPreview: () => request<Record<string, unknown>>("/api/memory/core/compact-preview"),
  coreMemoryCompactApply: (reason = "web compaction") =>
    request<Record<string, unknown>>("/api/memory/core/compact-apply", {
      method: "POST",
      body: JSON.stringify({ actor: "web", reason })
    }),
  coreMemoryMergePreview: () => request<Record<string, unknown>>("/api/memory/core/merge-preview"),
  coreMemoryMergeApply: (reason = "web merge") =>
    request<Record<string, unknown>>("/api/memory/core/merge-apply", {
      method: "POST",
      body: JSON.stringify({ actor: "web", reason })
    }),
  coreMemoryProviderStatus: () => request<Record<string, unknown>>("/api/memory/core/provider/status"),
  approveCoreMemory: (memoryId: string, reason = "web approval") =>
    request<{ memory: CoreMemoryRecord }>(`/api/memory/core/${encodeURIComponent(memoryId)}/approve`, {
      method: "POST",
      body: JSON.stringify({ actor: "web", reason })
    }),
  rejectCoreMemory: (memoryId: string, reason = "web rejection") =>
    request<{ memory: CoreMemoryRecord }>(`/api/memory/core/${encodeURIComponent(memoryId)}/reject`, {
      method: "POST",
      body: JSON.stringify({ actor: "web", reason })
    }),
  archiveCoreMemory: (memoryId: string, reason = "web archive") =>
    request<{ memory: CoreMemoryRecord }>(`/api/memory/core/${encodeURIComponent(memoryId)}/archive`, {
      method: "POST",
      body: JSON.stringify({ actor: "web", reason })
    }),
  tree: (sessionId: string) => request<Record<string, unknown>>(`/api/sessions/${sessionId}/tree`),
  prompt: (sessionId: string, prompt: string) =>
    request<{ session_id: string; queued: boolean }>(`/api/sessions/${sessionId}/prompt`, {
      method: "POST",
      body: JSON.stringify({ prompt })
    }),
  continueSession: (sessionId: string) => request<{ session_id: string }>(`/api/sessions/${sessionId}/continue`, { method: "POST" }),
  approve: (sessionId: string) => request(`/api/sessions/${sessionId}/approve`, { method: "POST" }),
  reject: (sessionId: string) => request(`/api/sessions/${sessionId}/reject`, { method: "POST" }),
  cancel: (sessionId: string) => request(`/api/sessions/${sessionId}/cancel`, { method: "POST" }),
  approvals: () => request<ApprovalsSummary>("/api/approvals"),
  runtimeReport: (sessionId?: string) =>
    request<RuntimeDoctorReport>(sessionId ? `/api/runtime/report?session_id=${encodeURIComponent(sessionId)}` : "/api/runtime/report"),
  uploadAttachment: (sessionId: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<{ attachment: AttachmentRecord }>(`/api/sessions/${encodeURIComponent(sessionId)}/attachments`, { method: "POST", body });
  },
  listAttachments: (sessionId: string) =>
    request<{ attachments: AttachmentRecord[] }>(`/api/sessions/${encodeURIComponent(sessionId)}/attachments`),
  inspectAttachment: (sessionId: string, attachmentId: string) =>
    request<{ attachment: AttachmentRecord; metadata: Record<string, unknown> }>(`/api/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}`),
  searchAttachment: (sessionId: string, query: string, attachmentId?: string, topK = 5, mode = "auto") =>
    request<{ results: AttachmentSearchResult[] }>(`/api/sessions/${encodeURIComponent(sessionId)}/attachments/search`, {
      method: "POST",
      body: JSON.stringify({ query, attachment_id: attachmentId, top_k: topK, mode })
    }),
  readAttachmentChunk: (sessionId: string, attachmentId: string, chunkId: string) =>
    request<AttachmentChunkRead>(`/api/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}/chunks/${encodeURIComponent(chunkId)}`),
  readAttachmentText: (sessionId: string, attachmentId: string, offset = 0, maxChars = 30000) =>
    request<AttachmentTextRead>(`/api/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}/text`, {
      method: "POST",
      body: JSON.stringify({ offset, max_chars: maxChars })
    }),
  readAttachmentRange: (sessionId: string, attachmentId: string, startLine: number, endLine: number) =>
    request<AttachmentRangeRead>(`/api/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}/range`, {
      method: "POST",
      body: JSON.stringify({ start_line: startLine, end_line: endLine })
    }),
  deleteAttachment: (sessionId: string, attachmentId: string) =>
    request<{ deleted: boolean; attachment_id: string }>(`/api/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}`, { method: "DELETE" }),
  previewAttachmentImport: (sessionId: string, attachmentId: string, targetPath: string, overwrite = false) =>
    request<AttachmentImportPreview>(`/api/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}/import/preview`, {
      method: "POST",
      body: JSON.stringify({ target_path: targetPath, overwrite })
    }),
  requestAttachmentImport: (sessionId: string, attachmentId: string, targetPath: string, overwrite = false) =>
    request<AttachmentImportPreview>(`/api/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}/import`, {
      method: "POST",
      body: JSON.stringify({ target_path: targetPath, overwrite })
    }),
  previewAttachmentMemoryIngest: (sessionId: string, attachmentId: string) =>
    request<AttachmentMemoryPreview>(`/api/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}/ingest-memory/preview`, { method: "POST" }),
  ingestAttachmentMemory: (sessionId: string, attachmentId: string, chunkIds: string[], tags: string[], scope = "workspace") =>
    request<{ memory_items_created: number; source_refs: string[] }>(`/api/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}/ingest-memory`, {
      method: "POST",
      body: JSON.stringify({ mode: chunkIds.length ? "selected_chunks" : "all_chunks", chunk_ids: chunkIds, max_chunks: 100, tags, scope })
    }),
  readAttachmentSymbol: (sessionId: string, attachmentId: string, symbolId: string) =>
    request<AttachmentSymbolRead>(`/api/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}/symbols/${encodeURIComponent(symbolId)}`),
  approvePending: (token: string) => request<ApprovalActionResponse>(`/api/approvals/${encodeURIComponent(token)}/approve`, { method: "POST" }),
  rejectPending: (token: string) => request(`/api/approvals/${encodeURIComponent(token)}/reject`, { method: "POST" }),
  capabilities: () => request<{ capabilities: unknown[] }>("/api/capabilities"),
  capabilityConfig: () => request<CapabilityInventory>("/api/capability-config"),
  capabilitySettingsPatch: (capabilities: Record<string, unknown>) =>
    request<{ snapshot: ConfigSnapshot; inventory: CapabilityInventory }>("/api/capability-config/settings", {
      method: "PATCH",
      body: JSON.stringify({ capabilities })
    }),
  createMcpServer: (payload: Record<string, unknown>) =>
    request<CapabilityInventory>("/api/mcp/servers", { method: "POST", body: JSON.stringify(payload) }),
  updateMcpServer: (name: string, payload: Record<string, unknown>) =>
    request<CapabilityInventory>(`/api/mcp/servers/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteMcpServer: (name: string) => request<CapabilityInventory>(`/api/mcp/servers/${encodeURIComponent(name)}`, { method: "DELETE" }),
  createSkill: (payload: Record<string, unknown>) =>
    request<CapabilityInventory>("/api/skills", { method: "POST", body: JSON.stringify(payload) }),
  getSkill: (name: string) => request<Record<string, unknown>>(`/api/skills/${encodeURIComponent(name)}`),
  updateSkill: (name: string, payload: Record<string, unknown>) =>
    request<CapabilityInventory>(`/api/skills/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify(payload) }),
  createPlugin: (payload: Record<string, unknown>) =>
    request<CapabilityInventory>("/api/plugins", { method: "POST", body: JSON.stringify(payload) }),
  updatePlugin: (name: string, payload: Record<string, unknown>) =>
    request<CapabilityInventory>(`/api/plugins/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify(payload) }),
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
  setSessionModel: (sessionId: string, model: string, providerId?: string) =>
    request<ConfigSnapshot & { pending_next_turn?: boolean }>(`/api/sessions/${encodeURIComponent(sessionId)}/model`, {
      method: "POST",
      body: JSON.stringify({ model, provider_id: providerId })
    }),
  debugSet: (path: string, value: unknown, sessionId?: string) =>
    request<ConfigSnapshot>("/api/debug/set", {
      method: "POST",
      body: JSON.stringify({ path, value, session_id: sessionId })
    }),
  sessionTools: (sessionId: string) => request<Record<string, unknown>>(`/api/sessions/${encodeURIComponent(sessionId)}/tools`)
};
