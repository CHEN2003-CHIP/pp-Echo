# Mission 03: Tool Execution Closeout

Status: Ready for human review

Date: 2026-07-07

Branch: `mission/mission-03-tool-execution`

## Mission Summary

Mission 03 forms the first safe command execution loop for pp-Echo:

`recognize test/command intent -> stage command proposal -> preview -> approve -> verify proposal digest -> execute -> return bounded result`

The implementation keeps command execution behind the existing `run_shell` approval path. It does not add a second shell executor, does not auto-run tests, and does not auto-repair failures.

## Implemented Scope

- 03A: Reference research and MVP design in `08-mission-03-tool-execution-design.md`.
- 03B: `CommandProposal` / `CommandPreview` convergence for staged `run_shell`.
- 03C: Approval-bound command proposal digest verification.
- 03D: Bounded shell execution result contract for stdout/stderr, exit code, timeout, duration, and backend metadata.
- 03E: `stage_test_command` pytest helper that stages a pending `run_shell` action.
- 03F: Registry, capability, subagent, runtime schema, and worktree direct shell result contract integration.
- 03G: E2E demo coverage and release gate documentation.

## Final Closed Loops

### `run_shell`

- Stages a pending shell action instead of executing immediately.
- Adds `details.command_proposal`.
- Derives `command_preview` from `command_proposal`.
- Approval grant records the proposal digest.
- Execution recomputes the current staged proposal digest before running.
- Digest mismatch rejects execution with `command proposal digest mismatch`.
- Execution result returns bounded stdout/stderr previews plus metadata.

### `stage_test_command`

- Accepts explicit pytest intent and a workspace-relative path target.
- Generates `python -m pytest <target> -q`.
- Stages a pending `run_shell` action.
- Adds `test_command_proposal` and `command_proposal`.
- Preview still derives from `command_proposal`.
- Approval and execution reuse the existing `run_shell` path.
- Result uses the same bounded shell result contract.

### Registry And Capability

- `stage_test_command` is model-callable.
- `stage_test_command` uses the public catalog contract `permissions_required == ["bash"]`.
- Read-only profiles cannot use `stage_test_command`.
- Host-only approval tools remain hidden from normal model tool schema.
- Worktree direct shell path reuses the same bounded shell result helper.

## Safety Invariants

- New staged `run_shell` actions must include `command_proposal`.
- The proposal digest binds the original command text, not only normalized command text.
- The user approves the concrete command proposal shown in preview.
- Preview does not execute commands.
- Approval after proposal tampering must reject execution.
- Legacy pending shell actions without `command_proposal` are compatibility fallback only, not the long-term main path.
- stdout/stderr returned to result and trace-facing details are bounded previews.
- `stage_test_command` does not directly execute tests.
- `stage_test_command` supports only explicit workspace-relative pytest paths.
- `stage_test_command` rejects absolute paths, workspace escape, shell metacharacters, whitespace injection, pytest node ids, and extra args.
- Read-only profiles cannot use the test command helper.
- Host-only approval tools are not exposed to the model as ordinary tools.

## Decisions

- `proposal_digest` binds the original command text and proposal metadata.
- `normalized_command` is only for display, comparison, and risk-analysis support.
- stdout/stderr preview limit is 8 KiB per stream for v0.x.
- The 8 KiB limit is a runtime preview default, not a permanent product constant.
- The test helper is named `stage_test_command`.
- The test helper supports only pytest path targets in this MVP.
- Pytest node ids and extra args are intentionally unsupported; future support should use separate allowlisted fields.
- Capability catalog expresses shell execution risk through `permissions_required == ["bash"]`.

## Verification

Focused verification completed during Mission 03F/03G:

- `python -m pytest tests\tools\test_tools.py -q`: 191 passed, 3 skipped, 2 warnings.
- `python -m pytest tests\tools\test_shell_sandbox_executor.py -q`: 112 passed, 2 warnings.
- `python -m pytest tests\capabilities\test_catalog.py -q`: 13 passed, 2 warnings.
- `python -m pytest tests\subagents -q`: 46 passed, 2 warnings.
- `python -m pytest tests\runtime\test_tool_approval_trace_consistency.py -q`: 7 passed, 2 warnings.
- `python -m pytest tests\runtime\test_tool_execution_context.py -q`: 19 passed, 2 warnings.
- `git diff --check`: passed with Git LF/CRLF warnings only.

Release gate full-suite result:

- `python -m pytest tests -q`: 1389 passed, 4 skipped, 2 warnings.

Skipped tests are expected in the current Windows environment where symlink creation is unavailable or restricted. Pytest cache warnings did not affect test results.

## Known Risks

- Full suite must pass before commit.
- 8 KiB stdout/stderr preview threshold may need configuration later.
- PowerShell, Git Bash, and Bash parsing differences remain a long-term safety concern.
- The pytest helper is intentionally conservative and may feel narrow until node id / extra args are separately designed.
- Worktree direct shell result contract should stay under regression coverage.
- Shell safety policy can still be strengthened in future missions.
- Prompt injection remains a long-term governance risk for command tools.
- Legacy shell pending action fallback should be removed after schema/version migration.

## Non-goals / Not Done

- No arbitrary shell helper beyond existing `run_shell`.
- No second shell executor.
- No bypass around `run_shell`.
- No pytest node id support.
- No extra args support.
- No auto-run tests.
- No auto retry.
- No auto repair.
- No CI or GitHub Actions.
- No package install automation.
- No remote execution.
- No multi-command transaction.
- No background task support.
- No Mission 04.

## Need Human Review

- Confirm whether the 8 KiB preview limit remains acceptable for v0.x.
- Confirm whether package manager, git mutation, and network commands should become hard-deny or remain high-risk ask in a later mission.
- Confirm whether legacy shell pending fallback should be removed in a future schema migration.
