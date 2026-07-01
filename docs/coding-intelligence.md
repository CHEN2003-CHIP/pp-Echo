# Coding Intelligence Layer

pp-Echo can surface a lightweight repository analysis before the normal coding workflow begins.

This layer is for workspace orientation, not for deep static analysis or code execution. It reuses the project context summary and adds a shallow structural map of the repository so the default coding workspace agent can quickly see:

- source roots
- test roots
- docs roots
- frontend and backend roots
- config files
- CI files
- entry points
- likely validation commands

The analysis is intentionally fixed-path and shallow. It should not scan the whole repository recursively or inspect protected paths.

The runtime context bridge adds the analysis to the `project_context` section for default coding workspaces.

The timeline layer can render this as a `repository_analysis` block for frontend consumers.

## Task Planner

`TaskPlan` is the structured planning layer between a user task and later execution phases. It is built from the user task plus available `ProjectContext`, `ProjectManifest` excerpts, and `RepositoryAnalysis`.

The MVP planner is rule-based and does not call an LLM. It uses conservative keyword routing and repository structure to propose:

- files to inspect
- likely files to change
- validation commands
- risk level
- assumptions and warnings
- ordered `PlanStep` records

The planner is an input surface for future `TaskScope`, `ImpactAnalyzer`, `TestPlanner`, and `ExecutionOrchestrator` work. It does not execute the plan, enforce scope, change sandbox behavior, or alter approval semantics.

Future versions can upgrade this into an LLM-assisted planner while keeping the current `TaskPlan` contract stable for Web/TUI timeline rendering.

## Task Scope

`TaskScope` is the authorization boundary between a `TaskPlan` and later execution phases.

It constrains:

- `allowed_paths`
- `disallowed_paths`
- edit permission
- delete permission
- shell permission
- network permission
- maximum changed files

TaskScope is not sandbox enforcement and it is not approval policy. It is a task-level scope contract that future ToolPolicy and structured changes enforcement can consume before shell commands, file edits, deletes, or `apply_patch_candidate` actions run.

The MVP scope builder is rule-based, inherits risk from `TaskPlan`, always denies network and delete by default, and always blocks protected paths such as `.env`, `.git/**`, `.pp-agent/**`, key files, caches, and build outputs.

## Impact Analyzer

`ChangeImpact` summarizes changed paths into impacted modules, related test paths, docs, warnings, and risk level.

The analyzer is rule-based and path-prefix only. It does not read file contents, run tools, call an LLM, or enforce sandbox policy. It maps known pp-Echo areas such as runtime, tools, sandbox, observability, context, coding, config, storage, CLI, web, docs, tests, and CI workflows into stable module names.

Risk is conservative:

- docs-only and tests-only changes are low risk
- coding, context, observability, runtime, tools, config, storage, CLI, web, and CI are medium risk
- sandbox, approval, policy, network, security, or `apply_patch` related paths/tasks are high risk
- unmatched paths remain unknown

`change_impact_to_context_item` and timeline helpers expose the same payload to context and Web/TUI consumers.

## Validation Planner

`ValidationPlan` is a recommendation layer that turns `ChangeImpact` into command candidates for a future orchestrator.

It only creates command records. It does not execute tests and does not request approvals.

Focused recommendations include module-specific pytest commands such as `python -m pytest tests/coding -q`, `python -m pytest tests/context -q`, and `python -m pytest tests/observability -q`. Sandbox-sensitive changes include the shell sandbox executor test. Web changes add `cd web && npm test` and `cd web && npm run build` when `web/package.json` is known from repository analysis.

High-risk changes also receive a full validation recommendation from repository likely commands, falling back to `python -m pytest -q`.

## Execution Orchestrator MVP

`prepare_coding_workflow` is the preparation-stage coding workflow orchestrator.

It strings together:

- `ProjectContext`
- `RepositoryAnalysis`
- `TaskPlan`
- `TaskScope`
- predicted `ChangeImpact`
- `ValidationPlan`

The current MVP prepares contracts only. It does not execute shell commands, edit files, call `apply_patch_candidate`, call an LLM, or change sandbox, approval, ToolPolicy, runtime, Web, or backend behavior.

`predicted_impact` is inferred from the task plan and task scope before any real file changes exist. It is not actual impact. A later execution loop can consume structured changes after edits and generate a separate actual impact record.

The prepared `CodingWorkflow` includes:

- stable `summary_text`
- ordered timeline blocks
- context items
- warnings collected from each preparation layer

Timeline blocks are generated in this order when repository analysis is available:

1. `repository_analysis`
2. `plan`
3. `task_scope`
4. `change_impact`
5. `validation_plan`

`coding_workflow_to_context_item` can package the complete workflow for future runtime or ExecutionOrchestrator context injection without forcing runtime integration in this PR.

## Scope Enforcement

`TaskScope` describes the task-level boundary. `ScopeEnforcementResult` records an actual check against that boundary.

This layer does not replace sandbox, approval, ToolPolicy, workspace locks, rollback, or patch digest checks. It adds a task-level boundary that can be consulted before structured changes, `apply_patch_candidate`, or future ToolPolicy hooks proceed.

`allowed` has three meanings:

- `true`: a TaskScope was provided and the checked path or structured changes passed
- `false`: a TaskScope was provided and the action should be blocked
- `null`: no TaskScope was provided, so enforcement was skipped and legacy behavior can continue

`enforce_structured_changes_scope` checks structured change paths without reading file contents and without mutating the changes. `enforce_path_scope` checks a single path/action for future file operation or ToolPolicy integration.

The current implementation exposes helpers and timeline/context details. It does not force every legacy pending action to include a TaskScope, and it does not change existing approval semantics.

## Runtime WriteScope Bridge

`TaskScope` belongs to the coding intelligence layer. `WriteScope` is the runtime/apply-path contract that tools can consume without importing `pp_agent.coding`.

The adapter `task_scope_to_write_scope` maps:

- `allowed_paths`
- `disallowed_paths`
- `allow_delete`
- `max_files_changed`
- `risk_level`
- `source="task_scope"`

`WriteScope` is intentionally smaller than `TaskScope`. It is not approval, sandbox, ToolPolicy, rollback, or digest validation. It is a task-level write boundary checked immediately before applying structured `apply_patch_candidate` changes.

Legacy pending actions without `write_scope` keep their existing behavior. Pending actions with `write_scope` run `check_structured_changes_against_write_scope` before acquiring the workspace lock, before snapshotting targets, and before writing files. A blocked check returns `scope_blocked=true` and `scope_check` details.

## Controlled Execution Session

`start_coding_execution_session` turns a prepared `CodingWorkflow` into a controlled execution session contract.

The session carries:

- the original workflow
- default or caller-provided `ExecutionGuardrails`
- a runtime `WriteScope` derived from `workflow.task_scope`
- timeline blocks
- context items
- pending approval placeholders
- warnings and stable summary text

The MVP does not run a model loop, execute shell commands, edit files, create pending actions, or call `apply_patch_candidate`. It only prepares the session that a later runtime loop, CLI/TUI, or Web surface can consume.

`attach_write_scope_to_patch_candidate_args` is the bridge helper for future patch candidate creation paths. It attaches `write_scope` to outgoing args without mutating the original dict, and rejects conflicting scopes so approval and digest semantics stay explicit.

## Runtime Execution Context Bridge

`CodingExecutionSession` remains the coding-layer session contract. `RuntimeExecutionContext` is the smaller neutral context that runtime and tools can consume without importing `pp_agent.coding`.

The adapter `coding_session_to_runtime_execution_context` maps:

- `session.id` to `session_id`
- `status` and `phase`
- the derived runtime `WriteScope`
- `ExecutionGuardrails` to `RuntimeExecutionGuardrails`
- zeroed `RuntimeExecutionCounters`
- `predicted_impact_not_actual=true`
- copied warnings

`RuntimeExecutionContext` is not a complete coding intelligence model. It carries guardrails, counters, session metadata, and optional `WriteScope` for future execution integration. It does not call an LLM, execute shell commands, edit files, create pending actions, invoke `apply_patch_candidate`, or change sandbox and approval behavior.

Runtime guardrails are currently helper-only. `check_runtime_guardrails` returns:

- `allowed=true` when the context exists and the requested action is below its limit
- `allowed=false` when the limit is reached or the action is unknown
- `allowed=null` when no runtime execution context is present and legacy flow skips the check

`increment_runtime_counter` returns an updated frozen context for `tool_call`, `shell_command`, or `patch_candidate`. Future ToolRegistry or runtime loop integration can use these helpers, but this bridge does not force them into the current execution path.

`attach_runtime_context_to_patch_candidate_args` lets patch candidate creation paths attach `write_scope` and minimal `execution_context` metadata from runtime context. It preserves legacy args when no context is present, avoids mutating the input dict, and rejects conflicting existing `write_scope` or execution metadata.

## Runtime Integration

`RuntimeExecutionContext` is now optionally wired into `ToolRegistry` through `ToolExecutionContext`. Runtime can attach the context to the registry; when no context is attached, guardrail checks return the skipped legacy path and existing tool behavior is unchanged.

The current integration points are:

- `ToolRegistry.execute` checks the `tool_call` guardrail after the existing ToolPolicy decision and before invoking the tool.
- `approve_pending_action` checks the `shell_command` guardrail before a staged `run_shell` action calls the sandbox executor.
- sandbox shell results check the `patch_candidate` guardrail before creating an `apply_patch_candidate` pending action.

Counters are updated only after the relevant action actually happens:

- `tool_calls` increments after a tool invocation returns or raises.
- `shell_commands` increments after the sandbox executor has run.
- `patch_candidates` increments after an `apply_patch_candidate` pending action is created.

Blocked guardrails return error details and do not execute the blocked step. A blocked tool call does not invoke the tool. A blocked shell command does not call the sandbox executor. A blocked patch candidate does not create a pending action.

Patch candidate args are enriched before the pending action and effect payload are built. This means an attached `write_scope` is part of the patch candidate effect's normalized arguments and payload digest, not a late approval-time mutation. The helper also adds minimal `execution_context` metadata with session id, phase, and `predicted_impact_not_actual`.

## Controlled Tool Loop MVP

`run_controlled_coding_loop` is the first finite runtime driver for coding tasks. It takes a user task plus an `AgentRuntime`, and may also reuse a prepared `CodingWorkflow` or `CodingExecutionSession`.

The flow is:

1. prepare or reuse `CodingWorkflow`
2. prepare or reuse `CodingExecutionSession`
3. adapt the session to `RuntimeExecutionContext`
4. attach that context to `AgentRuntime` / `ToolRegistry`
5. run at most `ControlledLoopOptions.max_model_turns`
6. stop on approval, guardrail block, scope block, max turns, runtime error, or completion

This is a controlled loop, not an autonomous loop. It does not auto-approve pending actions, does not auto-apply patch candidates, does not bypass ToolPolicy, and does not change sandbox, approval, payload digest, or write-scope enforcement semantics.

Stop conditions are explicit:

- pending approvals plus `stop_on_approval=true` -> `awaiting_approval`
- runtime guardrail block plus `stop_on_guardrail_block=true` -> `guardrail_blocked`
- write-scope or task-scope block plus `stop_on_scope_block=true` -> `scope_blocked`
- max turns reached -> `completed` with `stop_reason=max_turns`
- runtime exception -> `failed`

Patch candidate creation still receives `write_scope` before the pending action effect and payload digest are built. Patch apply still checks `write_scope` before workspace locks and writes. The loop only observes and stops; it does not grant approval or apply changes.

`ControlledToolLoopResult` packages the session, runtime execution context, timeline blocks, pending approval summaries, validation plan, warnings, and a stable summary for CLI/TUI/Web consumers.

## CLI Product Entrypoint

`pp-echo code "<task>"` is the first product-facing controlled coding workspace command.

It has two modes:

- `pp-echo code "<task>" --prepare-only`
- `pp-echo code "<task>" --max-turns 3`

Prepare-only mode calls `prepare_coding_workflow` and `start_coding_execution_session`, then prints the task, status, phase, task plan summary, task scope summary, predicted impact summary, validation summary, execution guardrails, warnings, and optional compact timeline blocks. It does not build an `AgentRuntime`, call a model, execute shell commands, edit files, request approval, or apply patches.

Controlled-loop mode builds an `AgentRuntime`, attaches the prepared runtime execution context, and calls `run_controlled_coding_loop` with conservative options:

- stop on pending approval
- stop on guardrail block
- stop on scope block
- no auto approval
- no auto patch apply

Useful examples:

```powershell
pp-echo code "add tests for the coding cli" --prepare-only
pp-echo code "add tests for the coding cli" --prepare-only --json
pp-echo code "add tests for the coding cli" --max-turns 3 --show-timeline
pp-echo code "add tests for the coding cli" --dry-run --json
```

The text output is intentionally compact. Pending approvals only show token, action type, tool name, title/summary, changed files, command, and scope-check summary. Timeline output only shows type, title, status, and compact details such as risk, counters, guardrails, validation commands, and counts. The CLI must not print full pending payloads, file contents, full diffs, secrets, or prompt bodies.

`--json` uses the same filtered payloads as text mode so future TUI/Web surfaces can reuse the CLI serialization helpers without depending on raw runtime internals.

## Web/API Coding Workflow Service

`pp_agent.web.coding_service` wraps the controlled coding workflow for Web/API consumers without
binding to a frontend framework or mounting routes by itself.

The service layer exposes:

- `CodingWorkflowService.start_task(task, workspace=None, max_turns=3, prepare_only=False)`
- `CodingWorkflowService.get_task(task_id)`
- `CodingWorkflowService.get_timeline(task_id)`
- `CodingWorkflowService.get_pending_approvals(task_id)`
- `CodingWorkflowService.get_validation_plan(task_id)`

`CodingTaskState` is the Web-facing state shape:

- `task_id`
- `task`
- `status`
- `stop_reason`
- `workflow_summary`
- `timeline_blocks`
- `pending_approvals`
- `validation_commands`
- `runtime_counters`
- `warnings`

Prepare-only flow:

1. call `prepare_coding_workflow`
2. call `start_coding_execution_session`
3. store and return a prepared `CodingTaskState`
4. do not call `run_controlled_coding_loop`

Controlled-loop flow:

1. build or receive an `AgentRuntime`
2. call `run_controlled_coding_loop`
3. store and return a controlled-loop `CodingTaskState`
4. stop on approval, guardrail block, scope block, max turns, or runtime error

The service is not a tool runtime. It does not auto-approve pending actions, does not apply patch
candidates, does not change payload digest semantics, and does not change write-scope enforcement.

### Web Coding API Endpoints

`pp_agent.web.coding_api` mounts real FastAPI endpoints for the Web adapter while keeping the
service injectable for tests:

- `POST /api/coding/tasks`
- `GET /api/coding/tasks/{task_id}`
- `GET /api/coding/tasks/{task_id}/timeline`
- `GET /api/coding/tasks/{task_id}/pending-approvals`
- `GET /api/coding/tasks/{task_id}/validation-plan`
- `POST /api/coding/tasks/{task_id}/approvals/{token}/approve`
- `POST /api/coding/tasks/{task_id}/approvals/{token}/reject`

Start-task request:

```json
{
  "task": "fix failing test",
  "workspace": ".",
  "max_turns": 3,
  "prepare_only": false
}
```

Task response:

```json
{
  "task_id": "coding-task-abc123",
  "task": "fix failing test",
  "status": "awaiting_approval",
  "stop_reason": "approval_required",
  "workflow_summary": "Controlled workflow summary",
  "timeline_blocks": [],
  "pending_approvals": [],
  "validation_commands": [],
  "runtime_counters": {},
  "warnings": []
}
```

Sub-resource responses:

```json
{ "task_id": "coding-task-abc123", "timeline_blocks": [] }
```

```json
{ "task_id": "coding-task-abc123", "pending_approvals": [] }
```

```json
{ "task_id": "coding-task-abc123", "validation_commands": [] }
```

Errors use a stable JSON shape and do not include Python tracebacks:

```json
{ "error": "bad_request", "message": "task is required" }
```

```json
{ "error": "not_found", "message": "coding task not found" }
```

The API applies service-level and route-level sanitization. Responses exclude full pending payloads,
file contents, raw diffs, manifests, prompts, secrets, and payload digest inputs. The endpoints do
not auto-approve, batch approve, or apply actions from the API layer.

Approval requests:

```json
{ "confirm": true }
```

Reject requests:

```json
{ "reason": "Not needed" }
```

Approve delegates to the existing backend approval path. It does not write files, apply patches, or
run commands directly from the Web/API layer, and it does not bypass payload digest, write-scope,
workspace lock, sandbox, or rollback checks. If the approval backend is unavailable, the API returns
`not_supported` instead of fabricating success.

Reject delegates to the existing reject backend when available. If that backend is unavailable, the
service can mark the approval as rejected in the Web/API task state and remove it from the summary;
that service-level rejection does not execute the staged action.

For frontend development against the real backend:

```bash
VITE_CODING_TASK_API=real
VITE_API_BASE_URL=http://localhost:<port>
```

## Unified Agent Workspace UI

The Web product should stay a unified Agent Workspace rather than adding a separate coding-task
page. Users submit general requests and coding requests through the same composer, and the default
frontend path always sends prompts to the normal `AgentRuntime` session. Coding is an agent
capability, not a separate frontend route and not a mock checklist.

Default Web behavior:

- `inspect this repo...` goes through the regular chat prompt path.
- repository analysis, file reads, edits, shell commands, and approvals appear through runtime
  messages, activity events, and the existing approval rail.
- the main chat UI does not render mock `CodingTaskState` timeline/checklist cards.
- the frontend does not apply patches, render full diffs, or call runtime/tools directly.

`web/src/lib/codingTaskApi.ts` and `web/src/lib/mockCodingTask.ts` remain available as a debug/API
contract harness for the Web Coding API. They are not the default product entrypoint.

Debug adapter selection:

- `CodingTaskClient` is defined in `web/src/lib/codingTaskApi.ts`.
- `MockCodingTaskClient` is backed by `web/src/lib/mockCodingTask.ts`.
- `VITE_CODING_TASK_API=real` selects `HttpCodingTaskClient` for debug surfaces that explicitly
  instantiate the adapter.
- `VITE_API_BASE_URL` targets another backend origin; it defaults to the current origin.

The real HTTP client sends:

```http
POST /api/coding/tasks
Content-Type: application/json
```

```json
{
  "task": "inspect this repo and run focused tests",
  "workspace": "E:/Pycharm Project/pp-Echo",
  "max_turns": 3,
  "prepare_only": false
}
```

The response must be a JSON-friendly `CodingTaskState`. Non-2xx responses become readable errors,
and incomplete response shapes are rejected by the debug adapter before a debug surface consumes
them.

UI direction:

- Prefer shadcn/ui components when the project adds shadcn configuration.
- Do not introduce another heavy UI kit.
- Current repository state has no `components.json`, Tailwind config, or shadcn package, so this
  pass reuses the existing Web styles instead of hand-adding a parallel component system.
- Suggested shadcn MCP config for local development:

```toml
[mcp_servers.shadcn]
command = "npx"
args = ["shadcn@latest", "mcp"]
```

Pending approval summaries only include:

- `token`
- `action_type`
- `tool_name`
- `summary`
- `changed_files`
- `command`
- compact `scope_check`

Timeline summaries only include:

- `type`
- `title`
- `status`
- compact `summary`
- a small `details` subset such as risk, stop reason, counts, guardrails, runtime counters,
  validation commands, and write-scope counts

Full pending payloads, file contents, full diffs, manifests, prompts, secrets, and digest inputs are
not part of the service output.

Example state payload:

```json
{
  "task_id": "coding-task-123",
  "task": "add web coding service",
  "status": "awaiting_approval",
  "stop_reason": "approval_required",
  "workflow_summary": "Controlled Tool Loop...",
  "timeline_blocks": [
    {
      "type": "controlled_tool_loop",
      "title": "Controlled execution paused for approval",
      "status": "waiting_approval",
      "summary": "Controlled Tool Loop...",
      "details": {
        "stop_reason": "approval_required",
        "pending_approvals_count": 1
      }
    }
  ],
  "pending_approvals": [
    {
      "token": "tok-1",
      "action_type": "run_shell",
      "tool_name": "run_shell",
      "summary": "Run validation",
      "changed_files": [],
      "command": "python -m pytest tests/web -q",
      "scope_check": null
    }
  ],
  "validation_commands": [
    {
      "command": "python -m pytest tests/web -q",
      "priority": "focused",
      "reason": "Focused validation for impacted test path tests/web.",
      "related_paths": ["tests/web"]
    }
  ],
  "runtime_counters": {
    "tool_calls": 0,
    "shell_commands": 0,
    "patch_candidates": 0
  },
  "warnings": []
}
```
