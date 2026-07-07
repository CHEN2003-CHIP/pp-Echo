# Mission 03A: Tool Execution Research and Design

Status: Implemented / closeout ready

Date: 2026-07-07

Branch: `mission/mission-03-tool-execution`

## Goal

Design the smallest safe tool execution loop for pp-Echo:

`recognize command -> stage command proposal -> preview -> approve -> execute -> record result -> feed observation back to trace/session`

This document is research and implementation planning only. It does not change runtime behavior.

Closeout document:

- `solo-workdocs/mission-docs/09-mission-03-tool-execution-closeout.md`

## Reference Research Summary

### opencode

Sources reviewed:

- `https://opencode.ai/docs/permissions/`
- `https://github.com/anomalyco/opencode`

Observed design:

- Commands are governed through a permission model with `ask`, `allow`, and `deny`.
- The permission domain includes `bash`.
- Rules support command pattern matching, for example broad ask-all plus narrower allow/deny rules such as allowing `git *` while denying `git commit *` or `git push *`.
- Permissions can be configured globally and per agent.

Useful for pp-Echo:

- Treat shell command execution as a first-class permission domain, not just another generic tool.
- Keep a small rule vocabulary: `allow`, `ask`, `deny`.
- Start with pattern-based classification for command heads and high-risk forms.
- Support per-agent or capability-profile overrides later.

Not suitable for current MVP:

- Full user-configurable command rule language is too much for 03B.
- Auto-allowing broad command families can be unsafe before pp-Echo has stable command proposals, trace truncation, and result redaction.

Mission 03 inspiration:

- 03B should add a canonical `command_proposal` dict to staged `run_shell` actions.
- 03C can bind approval to command proposal digest, similar to Mission 02B file proposal digest.
- Permission decisions should remain explicit and auditable.

### Claude Code / Codex-like CLI coding agents

Sources reviewed:

- Claude Code settings / permissions docs at `https://docs.anthropic.com/en/docs/claude-code/settings`
- Claude Code documentation index content covering tools reference, permissions, sandboxing, hooks, observability, checkpointing, and Windows PowerShell support.
- OpenAI Codex CLI public design knowledge available from current Codex runtime behavior: sandbox modes, approval modes, workspace-write boundaries, command prefix approval, and tool-call summaries.

Observed design:

- Command execution is mediated by permission modes and tool-specific policy.
- Claude Code exposes concepts such as tools reference, permission configuration, hooks, sandboxing, observability, and file checkpointing.
- Codex-like CLIs commonly separate model-visible tool calls from host approval/execution paths.
- Sandbox profiles usually distinguish read-only, workspace-write, and danger/full-access modes.
- Network access, install commands, destructive file operations, and long-running commands are treated as higher risk.

Useful for pp-Echo:

- Keep `run_shell` model-callable only as a staging tool, while host-only `approve_pending_action` performs execution.
- Keep command approval explicit even when a command looks like a test.
- Preserve cwd, sandbox backend, timeout, network state, exit code, stdout, stderr, duration, and truncation metadata in execution results.
- Use trace hooks for summaries, not raw unbounded output.

Not suitable for current MVP:

- Full hook/plugin ecosystems are too broad.
- Automatic mode switching or autonomous background command execution should wait.
- Rich terminal UI and persistent process management are out of scope.

Mission 03 inspiration:

- A minimal command loop should mirror the file-edit loop but avoid pretending shell is safe.
- Approval should bind exact command text, normalized command, cwd, timeout, shell kind, and risk classification.
- Trace output must be bounded and redacted.

### OpenHands / OpenDevin

Sources reviewed:

- OpenHands public docs and README-level runtime/sandbox material.
- OpenHands/OpenDevin architecture pattern: agent actions run in an isolated runtime and return observations.

Observed design:

- The project centers command/browser/file operations around an execution runtime rather than running arbitrary host commands directly.
- Agent steps are commonly represented as action and observation pairs.
- Runtime isolation is a major product boundary.

Useful for pp-Echo:

- Model command execution as an auditable action with a structured observation.
- Separate command staging, approval, execution, and observation recording.
- Keep future room for stronger sandbox backends without requiring Mission 03 to redesign Docker/local sandbox.

Not suitable for current MVP:

- Full remote runtime management, browser/runtime orchestration, and cloud sandbox lifecycle are much larger than pp-Echo's solo MVP.
- Replacing the current `SandboxExecutor` stack is unnecessary for 03B.

Mission 03 inspiration:

- Define `CommandResult`-like metadata even if kept as a lightweight dict first.
- Use existing sandbox/local executor abstraction instead of creating a new runtime layer.

### Aider and terminal assistants

Sources reviewed:

- `https://aider.chat/docs/usage/lint-test.html`
- Aider docs for `/test`, `--test-cmd`, `--auto-test`, `--lint-cmd`, and `/run`.

Observed design:

- Aider lets users configure lint and test commands.
- `/test <test-command>` runs the command and treats non-zero exit code plus stdout/stderr as feedback.
- `--auto-test` can run configured tests after AI edits.
- `/run` can run arbitrary code and ask whether to add output back into chat.

Useful for pp-Echo:

- Test commands are a distinct product use case: focused checks should be easy to propose and approve.
- Exit code plus stdout/stderr is enough for first feedback loop.
- User should control whether command output becomes model-visible context.

Not suitable for current MVP:

- Auto-fixing failed tests after command execution is out of scope.
- Auto-test after every edit is too aggressive before command safety and trace truncation are settled.

Mission 03 inspiration:

- 03E can build on existing validation planners and produce focused test command proposals.
- First implementation should execute only approved command proposals; it should not auto-repair.

### Security research and incidents

Sources reviewed:

- OWASP GenAI `LLM01:2025 Prompt Injection`
- Public prompt-injection and tool-misuse guidance for agentic systems.

Key risks:

- Prompt injection can cause an agent to misuse tools, exfiltrate credentials, run destructive commands, or install malware.
- Shell access amplifies prompt injection because text instructions can become host-side actions.
- Commands can leak secrets through stdout/stderr, environment dumps, path names, package manager logs, or network calls.
- `curl | sh`, package installs, recursive delete, chmod/ACL changes, git reset/clean, external paths, and network exfiltration need explicit controls.

Useful for pp-Echo:

- Treat command execution as high-risk by default.
- Do not let file contents, web pages, dependency output, or test failures self-authorize shell commands.
- Require host approval for commands that mutate workspace, touch network, install packages, delete files, change git state, or expose credentials.
- Redact and truncate command output before trace/model feedback.

Not suitable for current MVP:

- Comprehensive malware detection and secure remote sandboxing are not Mission 03.
- Policy should start deterministic and conservative.

Mission 03 inspiration:

- Add explicit prompt-injection language to command preview and risk classification.
- Prefer deny or ask over silent allow when classification confidence is low.

## Current State

### ToolRegistry and `run_shell`

Relevant files:

- `src/pp_agent/tools/registry.py`
- `src/pp_agent/tools/shell_tool.py`
- `src/pp_agent/tools/file_tools.py`
- `src/pp_agent/tools/effects.py`
- `src/pp_agent/storage/approvals.py`

Current behavior:

- `run_shell` is a builtin model-callable tool.
- Its ToolSpec says it stages a PowerShell command for host-side approval.
- `PowerShellTool.execute()` does not execute immediately. It stages a `PendingActionStore` payload with:
  - `action_type="run_shell"`
  - `command`
  - `details.timeout_seconds`
  - `effect` from `build_shell_effect`
  - origin metadata.
- `approve_pending_action` is host-only and executes staged shell commands.
- `ApprovePendingActionTool.execute()`:
  - loads pending payload;
  - attaches or validates an approval grant;
  - validates effect digest;
  - checks runtime guardrails for `shell_command`;
  - executes through `SandboxExecutor.run(SandboxRunRequest(...))`;
  - records failure lifecycle separately from approval invalidation;
  - returns command, timeout, return code, sandbox metadata, and possible sandbox patch candidate metadata.
- `build_shell_effect()` already normalizes commands and computes `payload_digest`.
- Shell effect analysis already classifies:
  - inspect commands;
  - workspace mutation;
  - external mutation;
  - networked;
  - destructive.
- It recognizes flags/categories including:
  - `test_runner`;
  - `package_manager`;
  - `formatter`;
  - `vcs_write`;
  - `redirection`;
  - `shell_operator`;
  - `env_write`;
  - `force`;
  - `recursive`;
  - `destructive_escalated`.

Current gap:

- There is no canonical `command_proposal` equivalent to 02B `patch_proposal`.
- Preview for shell pending actions is effect/payload oriented, not clearly derived from one canonical proposal object.
- Approval binds `effect.payload_digest`, but not a separately named command proposal digest.
- Shell baseline semantics are different from file edits and should not pretend to validate filesystem baseline in 03B.
- Execution result does not yet define a small explicit result contract for truncation, duration, and model-visible redaction.

### Approval and pending action lifecycle

Relevant file:

- `src/pp_agent/storage/approvals.py`

Current behavior:

- `PendingActionStore.stage()` deduplicates active pending actions by effect `payload_digest`.
- Lifecycle states include `staged_not_granted`, `grant_attached`, `execution_in_progress`, `execution_succeeded`, `execution_failed`, `grant_consumed`, `grant_invalidated`, `rejected`, etc.
- Approval grants include `grant_id`, `effect_id`, `payload_digest`, timestamps, status, and grant owner.
- Mission 02B added patch-proposal digest binding for file edits.

Current gap:

- Shell approvals do not yet have `command_proposal_digest`.
- Shell preview/approval/apply terminology is less productized than file edits.

### Sandbox and execution backend

Relevant files:

- `src/pp_agent/sandbox/base.py`
- `src/pp_agent/sandbox/local.py`
- `src/pp_agent/sandbox/docker.py`
- `tests/tools/test_shell_sandbox_executor.py`

Current behavior:

- `SandboxRunRequest` carries command, cwd, and timeout.
- `SandboxRunResult` carries stdout, stderr, returncode, timed_out, backend, sandbox mode, network metadata, writable roots, and optional patch/structured change metadata.
- `LocalSandboxExecutor` uses PowerShell and is documented as not a security sandbox.
- `DockerSandboxExecutor` can capture changed files, patch summaries, structured changes, and truncation markers.

Current gap:

- Command result metadata does not consistently include duration.
- Stdout/stderr truncation for model/trace feedback needs a clear contract.
- Local PowerShell vs Docker/bash behavior needs product wording; current user-facing `run_shell` says PowerShell.

### Policy and capability governance

Relevant files:

- `src/pp_agent/storage/settings.py`
- `src/pp_agent/subagents/capabilities.py`
- `src/pp_agent/runtime/execution_context.py`
- `src/pp_agent/runtime/tool_surface.py`

Current behavior:

- `ToolPolicyConfig` has `permission_mode`, allowed/denied/ask tools, `confirm_run_shell`, and `shell_timeout_seconds`.
- Permission modes include `read-only`, `workspace-write`, `danger-full-access`, and `prompt`.
- `CapabilityAdmissionGate` treats `run_shell` as a write tool and blocks it in read-only subagents.
- Runtime execution context already has `max_shell_commands`, `stop_on_approval`, and counters.
- Host-only approval tools are hidden from normal model tool calls.

Current gap:

- `run_shell` is currently one broad tool; there is no separate test-command helper or command preview contract.
- Capability metadata can identify shell risk, but does not yet encode command proposal/result lifecycle details.

### Coding validation planning

Relevant files:

- `src/pp_agent/coding/testing.py`
- `src/pp_agent/coding/planner.py`
- `src/pp_agent/coding/orchestrator.py`
- `tests/coding/test_validation_planner.py`

Current behavior:

- Existing coding intelligence can recommend focused validation commands such as:
  - `python -m pytest tests/coding -q`
  - `python -m pytest tests/runtime -q`
  - `python -m pytest tests/tools/test_shell_sandbox_executor.py -q`
  - `cd web && npm test`
  - `cd web && npm run build`
- This layer is explicitly non-executing.

Current gap:

- No direct bridge turns a validation recommendation into a staged command proposal.
- No end-to-end loop exists for "recommend focused pytest -> preview -> approve -> execute -> summarize result".

## Problem Statement

Mission 02B made single-file edits auditable and recoverable. Mission 03 should make test/command execution similarly explicit and safe.

The current `run_shell` path already stages and approves commands, but it lacks a product-level command proposal contract, consistent preview semantics, output truncation/redaction contract, and focused test-command loop. Without these, pp-Echo risks becoming a generic shell relay where prompt injection, package installs, destructive operations, or noisy outputs are hard to reason about.

Mission 03 must answer:

- What exact command did the user approve?
- What cwd, timeout, shell, sandbox, and risk class were approved?
- What command actually ran?
- What result was observed?
- What output is safe to show to the model, trace, web UI, and logs?
- Which commands are refused or require stronger approval?

## MVP Scope

Mission 03 MVP should cover:

- Agent or coding layer identifies likely test commands.
- Runtime/tooling stages a command proposal instead of executing directly.
- User can preview command, cwd, timeout, shell kind, risk class, and expected effects.
- Approval binds to command proposal digest.
- Approved command executes through existing `SandboxExecutor`.
- Execution result records:
  - exit code / return code;
  - timed out;
  - stdout preview;
  - stderr preview;
  - stdout/stderr truncation flags;
  - duration in ms;
  - cwd;
  - sandbox backend/mode/network metadata;
  - command proposal digest.
- Safety policy blocks or requires approval for high-risk commands.
- Result enters trace/session log as bounded, redacted metadata.

## Non-goals

Mission 03 does not do:

- Remote execution.
- Docker/sandbox architecture rewrite.
- CI system.
- GitHub Actions integration.
- Automatic test failure fixing.
- Arbitrary long-running background tasks.
- Multi-command transactions.
- Automatic package install execution.
- Destructive command execution.
- Git rollback.
- Full audit log rewrite.
- IDE integration.
- Third-party API integration.
- Mission 04.

## Safety Model

### Workspace cwd

- First version runs commands with cwd at workspace root unless explicitly staged otherwise.
- Cwd must resolve inside workspace.
- Relative `cd` or `Set-Location` inside command should be treated as shell syntax, not as trusted cwd metadata.
- Commands that reference absolute external paths should be classified as external mutation or denied/ask.

### Timeout

- Reuse `ToolPolicyConfig.shell_timeout_seconds`.
- Command proposal must include effective timeout.
- Approval binds timeout.
- 03B should not add background process support.

### Stdout/stderr truncation

- Store raw executor result only where existing execution path already stores it; do not add new unbounded trace payloads.
- Command result should include bounded previews and flags:
  - `stdout_preview`;
  - `stderr_preview`;
  - `stdout_truncated`;
  - `stderr_truncated`;
  - `stdout_bytes` or char count;
  - `stderr_bytes` or char count.
- Trace/session messages must not include unbounded output.
- Output may contain secrets; treat command output as sensitive by default.

### Denylist and high-risk command policy

Initial deny/ask classification should include:

- Destructive delete:
  - `rm -rf`;
  - `Remove-Item -Recurse -Force`;
  - `del /s`;
  - `git clean`;
  - `git reset --hard`.
- Package install/update/remove:
  - `pip install`;
  - `python -m pip install`;
  - `uv add/install`;
  - `npm install`;
  - `pnpm install`;
  - `yarn add`;
  - `poetry add/install`.
- Network:
  - `curl`;
  - `wget`;
  - `Invoke-WebRequest`;
  - `Invoke-RestMethod`;
  - `iwr`;
  - `irm`.
- Credential/secret exposure:
  - `env`;
  - `Get-ChildItem Env:`;
  - reading `.env`, `.pem`, `.key`;
  - printing known token env vars.
- Shell pipeline install patterns:
  - `curl ... | sh`;
  - `irm ... | iex`;
  - `Invoke-Expression`.
- Permission/ACL changes:
  - `chmod`;
  - `icacls`;
  - `Set-Acl`.
- Git publication/history mutation:
  - `git push`;
  - `git commit`;
  - `git rebase`;
  - `git checkout` / `restore` / `switch` when it may overwrite worktree.

For 03B, this can remain classification plus preview. Hard blocks can be formalized in 03C after digest-bound approval is in place.

### Approval gate

- `run_shell` remains model-callable as a staging path.
- `approve_pending_action` remains host-only.
- Approval must bind exact normalized command, cwd, shell kind, timeout, risk class, and proposal digest.
- If proposal digest changes after approval, execution is rejected.

### Model-visible vs host-only

- Model may request staging a command.
- Model may see safe preview metadata and bounded execution observations.
- Model must not directly call host-only approval/execution controls.
- Recovery, approval, and policy override remain host/control plane.

### Trace redaction

- Trace may include:
  - command summary;
  - command digest;
  - command head;
  - risk class;
  - cwd label;
  - timeout;
  - exit code;
  - duration;
  - truncated stdout/stderr previews.
- Trace should not include:
  - unbounded stdout/stderr;
  - full environment dumps;
  - secrets;
  - credential file content;
  - long command output that can reconstruct user files.

### Prompt injection

- Treat instructions from files, command output, web pages, package logs, and test logs as untrusted observations.
- Do not let command output grant approval for the next command.
- Do not auto-run a command solely because a file/test says to.
- Preview should surface when command was model-generated from untrusted context if that metadata is available.

### Windows / PowerShell / Bash differences

- Current `run_shell` is PowerShell-oriented.
- Mission 03 should not pretend Bash semantics apply on Windows.
- Command parsing must be conservative because PowerShell quoting, aliases, pipelines, and redirection differ from Bash.
- First MVP can define `shell_kind="powershell"` for local Windows execution.
- Cross-shell support can wait until the proposal contract exists.

## Proposed Mission 03 Breakdown

### 03A: Research and design

- Complete this document.
- No runtime code changes.

### 03B: CommandProposal / CommandPreview convergence

Smallest implementation target:

- Add lightweight `command_proposal` dict to staged `run_shell` payload details.
- Include:
  - `action_type`;
  - `command`;
  - `normalized_command`;
  - `command_head`;
  - `cwd`;
  - `workspace_relative_cwd`;
  - `shell_kind`;
  - `timeout_seconds`;
  - `risk_class`;
  - `flags`;
  - `requests_network`;
  - `destructive_hint`;
  - `touches_external`;
  - `proposal_digest`;
  - optional `effect_payload_digest`.
- Derive shell preview from `command_proposal`.
- Do not change execution behavior yet.
- Do not add approval rejection based on proposal digest yet.

### 03C: Approval-bound command execution

- Record approved `command_proposal_digest`.
- Recompute digest before execution.
- Reject if approved proposal digest does not match current staged proposal.
- Keep effect digest validation.
- Keep approval host-only.

### 03D: Execution result / trace / truncation

- Define bounded command result metadata.
- Add stdout/stderr preview truncation.
- Include duration.
- Ensure trace details never include full unbounded output.
- Keep failure details useful but bounded.

### 03E: Test command helper / focused pytest recommendation

- Bridge existing `ValidationPlan` commands into staged `run_shell` proposals.
- Prefer focused pytest / module tests.
- Do not auto-run.
- Do not auto-fix failed tests.

Implementation note:

- MVP adds `stage_test_command` as a thin model-callable helper for explicit pytest targets.
- It accepts only `framework=pytest` and a workspace-relative target, generating `python -m pytest <target> -q`.
- It delegates to the existing `run_shell` staging path, so preview, approval digest validation, execution, and bounded result metadata remain owned by `run_shell`.
- It does not support arbitrary commands, package installs, network commands, automatic execution, retry, or auto-fix.
- The helper validates target paths against absolute paths, workspace escape, and shell metacharacter injection.

### 03F: Registry / capability integration

- Confirm `run_shell` remains normal staged model-callable tool.
- Confirm approval execution remains host-only.
- Add capability metadata for command proposal/result if useful.
- Re-check subagent read-only/staged/worktree behavior.

### 03G: E2E demo / release gate

- Verify:
  - focused test command stage;
  - preview;
  - approve;
  - execute;
  - result with exit code/output preview/duration;
  - trace-safe metadata;
  - denial/ask for high-risk command.

## Tests Plan

### 03B tests

- `run_shell` staged action includes `details.command_proposal`.
- Command proposal digest is stable for the same command/cwd/timeout/shell kind.
- Changing command changes proposal digest.
- Changing timeout changes proposal digest.
- Preview is derived from `command_proposal`.
- Preview displays risk class and flags.
- Existing shell staging tests still pass.

### 03C tests

- Approving and executing unchanged command proposal succeeds.
- Tampering with staged `command_proposal.command` after approval rejects execution.
- Tampering with timeout after approval rejects execution.
- Effect digest mismatch remains rejected.
- Error message clearly says command proposal digest mismatch.

### 03D tests

- Successful command result includes exit code, duration, cwd, timeout, proposal digest.
- Failed command result includes exit code and bounded stdout/stderr previews.
- Large stdout is truncated.
- Large stderr is truncated.
- Trace details do not include unbounded command output.
- Timeout result is recorded clearly.

### 03E tests

- Validation plan command can be staged as a command proposal.
- Focused pytest recommendation preserves command string.
- Web validation command with `cd web && npm test` is classified conservatively because of shell operator and cwd semantics.
- Test command helper does not execute without approval.

### 03F tests

- `run_shell` remains model-callable staging tool.
- `approve_pending_action` remains host-only.
- Read-only subagent profile denies `run_shell`.
- Worktree direct shell does not bypass guardrails unexpectedly.
- Capability catalog metadata marks shell risk.

### 03G tests

- E2E happy path:
  - stage `python -m pytest tests/coding -q`;
  - preview;
  - approve;
  - execute through injected fake executor;
  - result includes bounded observation.
- High-risk command preview marks deny/ask:
  - package install;
  - destructive delete;
  - network fetch;
  - git push/reset.

## Risks

| Risk | Level | Why It Matters | Mitigation |
| --- | --- | --- | --- |
| Shell command danger | High | A command can delete files, mutate git, leak secrets, install packages, or contact network. | Default to staged approval; classify high-risk commands conservatively. |
| Prompt injection | High | Untrusted text can ask the agent to run malicious shell commands. | Never let observations self-approve commands; keep host approval gate. |
| PowerShell/Bash differences | Medium | Windows aliases, quoting, pipelines, and redirection differ from Bash examples. | First MVP declares PowerShell shell kind and keeps parser conservative. |
| Long-running tests | Medium | Test commands can hang or block UX. | Enforce timeout and no background process support. |
| Huge stdout/stderr | Medium | Output can flood trace/model context or expose secrets. | Truncate and record counts/digests. |
| Environment dependency | Medium | Tests may fail due missing tools, not code. | Preserve exit code/stderr and mark as observation, not automatic failure cause. |
| Package install | High | Install modifies environment and may execute arbitrary code. | Ask/deny first version; no automatic package install. |
| Hidden credentials | High | Env vars and logs can leak tokens. | Redact trace output; deny/ask credential-like commands. |
| Flaky tests | Medium | Agent may overreact to nondeterministic failures. | Record result only; no auto-fix in MVP. |

## Recommended First Implementation Task

Start with **03B: CommandProposal / CommandPreview convergence**.

Smallest coding task:

- In `run_shell` staging, add a lightweight `details.command_proposal` dict.
- Generate it from existing `build_shell_effect()` analysis and normalized arguments.
- Add `proposal_digest` for stable identity.
- Update `preview_pending_action` shell preview to render from `command_proposal`.
- Do not change command execution or approval rejection semantics.

Why first:

- It mirrors the successful 02B pattern without over-engineering.
- It gives 03C a stable digest to bind approvals.
- It is testable without executing real shell commands.
- It does not require sandbox, runtime loop, or capability architecture changes.

## Need Human Review

- Confirm whether Mission 03 should keep first-version shell kind as PowerShell only.
- Confirm whether package manager commands should be hard-denied in MVP or staged as high-risk ask.
- Confirm whether `git commit` and `git push` should be hard-denied or host-only/manual outside model flow.
- Confirm stdout/stderr preview limits for 03D, for example 8 KiB per stream or smaller.
- Confirm whether focused test command helper should be a new host/control helper or only reuse `run_shell` staging.
- Confirm whether web commands like `cd web && npm test` are acceptable in first MVP or should be decomposed into cwd + command.

## Not Done

- No runtime code changes.
- No test changes.
- No new shell capability.
- No Mission 03B implementation.
- No dependency changes.
- No commit.
