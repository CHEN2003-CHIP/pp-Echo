# Timeline Contract

The timeline layer is the JSON-friendly contract used by Web and TUI clients to render agent work without parsing model text.

It is intentionally separate from trace storage:

- `AgentStep` captures the visible unit of work.
- `FileOperation` captures read/write/delete/rename activity.
- `DiffArtifact` captures structured file-change content.
- `ApprovalCard` captures staged actions waiting for review.
- `TestRunResult` and `RunSummary` capture verification and end-of-run status.

Frontend consumers should treat these objects as stable data shapes and should not depend on internal runtime classes.

The contract is built from runtime events, structured file changes, and pending action payloads.

## Project Context Blocks

The default workspace bootstrap can add lightweight project context blocks before the normal conversation flow:

- `project_context` summarizes the detected language stack, likely test commands, important paths, and loaded manifest hints.
- `manifest_loaded` records each discovered instruction file preview.

These blocks are generated from workspace inspection and manifest loading, not from model text.

- `repository_analysis` summarizes the repository shape for the default coding workspace agent, including source roots, test roots, docs, CI files, entry points, and likely validation commands.
- `change_impact` summarizes changed paths, impacted modules, recommended test paths, docs impact, warnings, and risk.
- `validation_plan` lists recommended validation commands without executing them.
- `coding_workflow` summarizes the preparation-stage workflow that strings repository analysis, plan, scope, predicted impact, and validation recommendations together.
- `scope_enforcement` records whether task-level scope enforcement passed, blocked an action, or was skipped for a legacy flow with no TaskScope.
- `execution_session` records a prepared controlled coding execution session.
- `execution_guardrails` records the guardrails attached to that future execution session.
- `controlled_tool_loop` records a finite controlled runtime loop, including status, stop reason, counters, and pending approval summaries.

Workflow preparation blocks should appear in stable order:

`repository_analysis` -> `plan` -> `task_scope` -> `change_impact` -> `validation_plan`

## Conversational Timeline Blocks

The frontend can combine text and runtime facts into `TimelineBlock` records:

- `AssistantMessageBlock` carries model-authored explanatory text.
- `AgentActionGroup` groups factual runtime activity such as shell commands, file reads, edits, approvals, and tests.
- `TimelineBlock` is the renderable unit the Web/TUI layer should consume.

The model message is not the source of tool facts. Tool facts come from runtime events, structured changes, and pending actions.

Example shapes:

```json
{
  "type": "assistant_message",
  "content": "I will inspect the project context first.",
  "related_step_ids": ["step-1"]
}
```

```json
{
  "type": "action_group",
  "title": "Ran 3 commands",
  "status": "running"
}
```

```json
{
  "type": "approval_card",
  "title": "Waiting for approval",
  "status": "waiting_approval"
}
```

```json
{
  "type": "project_context",
  "title": "Project context",
  "status": "succeeded"
}
```

```json
{
  "type": "manifest_loaded",
  "title": "Manifest loaded: AGENTS.md",
  "status": "succeeded"
}
```

```json
{
  "type": "repository_analysis",
  "title": "Repository analysis",
  "status": "succeeded"
}
```

```json
{
  "type": "plan",
  "title": "Generated task plan",
  "status": "succeeded",
  "details": {
    "task": "fix CI env loading",
    "risk_level": "medium",
    "files_to_inspect": [".github/workflows/ci.yml", "tests/"],
    "validation_commands": ["python -m pytest -q"]
  }
}
```

```json
{
  "type": "task_scope",
  "title": "Generated task scope",
  "status": "succeeded",
  "details": {
    "allowed_paths": ["src/pp_agent/context/**", "tests/context/**"],
    "disallowed_paths": [".env", ".git/**", ".pp-agent/**", "*.key"],
    "allow_edit": true,
    "allow_delete": false,
    "allow_network": false,
    "risk_level": "medium"
  }
}
```

```json
{
  "type": "change_impact",
  "title": "Analyzed change impact",
  "status": "succeeded",
  "details": {
    "changed_paths": ["src/pp_agent/coding/impact.py"],
    "impacted_modules": ["coding"],
    "impacted_tests": ["tests/coding"],
    "risk_level": "medium"
  }
}
```

```json
{
  "type": "validation_plan",
  "title": "Generated validation plan",
  "status": "succeeded",
  "details": {
    "commands": [
      {
        "command": "python -m pytest tests/coding -q",
        "priority": "focused"
      }
    ],
    "risk_level": "medium"
  }
}
```

```json
{
  "type": "coding_workflow",
  "title": "Prepared coding workflow",
  "status": "prepared",
  "details": {
    "task": "fix timeline contract tests",
    "risk_level": "medium",
    "impacted_modules": ["observability"],
    "validation_commands": ["python -m pytest tests/observability -q"],
    "predicted_impact_not_actual": true
  }
}
```

```json
{
  "type": "scope_enforcement",
  "title": "Task scope check failed",
  "status": "failed",
  "details": {
    "allowed": false,
    "action": "apply_patch",
    "reason": "Path is explicitly disallowed by task scope.",
    "risk_level": "high",
    "failed_path": ".env",
    "matched_rule": ".env",
    "checked_paths": [".env"],
    "warnings": []
  }
}
```

```json
{
  "type": "execution_session",
  "title": "Prepared controlled execution session",
  "status": "prepared",
  "details": {
    "status": "prepared",
    "phase": "prepared",
    "write_scope": {
      "source": "task_scope",
      "max_files_changed": 8
    },
    "pending_approvals_count": 0,
    "predicted_impact_not_actual": true
  }
}
```

```json
{
  "type": "execution_guardrails",
  "title": "Configured execution guardrails",
  "status": "succeeded",
  "details": {
    "max_tool_calls": 20,
    "max_shell_commands": 5,
    "max_patch_candidates": 3,
    "stop_on_approval": true,
    "stop_on_scope_block": true,
    "stop_on_test_failure": true
  }
}
```

```json
{
  "type": "controlled_tool_loop",
  "title": "Controlled execution paused for approval",
  "status": "waiting_approval",
  "details": {
    "task": "fix failing test",
    "stop_reason": "approval_required",
    "pending_approvals_count": 1,
    "runtime_execution_context": {
      "session_id": "coding-exec-123",
      "counters": {
        "tool_calls": 1,
        "shell_commands": 0,
        "patch_candidates": 0
      }
    }
  }
}
```
