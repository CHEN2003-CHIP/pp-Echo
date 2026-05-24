# Project Memory

<!-- pp-echo-memory:begin -->
## pp-Echo Workspace Bootstrap Memory

Short-lived prompt memory for durable preferences, project decisions, and navigation.
Use `memory_search` and `memory_get` for detailed notes in `memory/**/*.md`.

### Learned Notes
Source: session=8778eb07-2fa5-4bc2-8529-d8028df354d9 turn=turn-1
  Evidence: The specific task requested creating `docs/worktree-smoke-web.md` with the content 'pp-Echo isolated worktree smoke test'.
  Source: session=b1b826c9-027b-410e-b7a9-30f3ea5d0285 turn=turn-1
- **Orchestration Requirement for Code Changes**: Code changes must be executed using the 'orchestrate_agents' workflow rather than direct file editing tools.
  Evidence: Trusted instructions explicitly state: '不要直接调用 edit_file/write_file。请必须使用 orchestrate_agents。workflow=code_change'
  Source: session=ecc5323b-5b1c-42cf-9d1a-fca1ac986db1 turn=turn-1
- **Smoke Test Documentation Location**: Isolated worktree smoke tests should be documented in `docs/worktree-smoke-web.md` with a single-line summary description.
  Evidence: Task explicitly requested creating `docs/worktree-smoke-web.md` with content 'pp-Echo isolated worktree smoke test'.
  Source: session=be758fd5-d8dd-4a42-bbf6-908de1f3026d turn=turn-1
- **Mandatory use of orchestrate_agents for file edits**: Direct calls to edit_file or write_file are prohibited. All code changes must be executed via the orchestrate_agents tool with an appropriate workflow (e.g., code_change).
  Evidence: User instruction: '不要直接调用 edit_file/write_file。请必须使用 orchestrate_agents。'
  Source: session=e693a39c-603b-48b6-905f-e378106c6049 turn=turn-1
- **Smoke Check Documentation Format**: Web smoke check status should be recorded in docs/web-smoke-check.md containing a single line: 'web smoke ok'.
  Evidence: Task instruction explicitly requested creating docs/web-smoke-check.md with content 'web smoke ok', which was successfully executed.
  Source: session=d2530464-2306-40e1-b0fa-5c459f10557e turn=turn-2
- **Web Smoke Check Documentation File**: The project uses a file named `docs/web-smoke-check.md` to record the status of web smoke checks, containing a single line indicating success (e.g., 'web smoke ok').
  Evidence: User requested creation of `docs/web-smoke-check.md` with content 'web smoke ok' via `orchestrate_agents`.
  Source: session=9f436abf-e99f-4a47-b62c-39dbd25f7602 turn=turn-2
- **Browser Testing Procedure**: When testing browser tools, avoid using approve_pending_action and do not request user interaction. Use direct tool calls like navigate, read_state, type, click, and screenshot.
  Evidence: User instructions: '只使用 browser 工具完成，不要使用 approve_pending_action，不要请求我点击 Approve。'
  Source: session=1734d14d-9803-4fae-903a-c6800b780bad turn=turn-1
- **Windows-first platform strategy**: pp-Echo is explicitly designed as a Windows-first coding agent. While Linux and macOS support are planned, the current stable implementation, tooling (PowerShell), and documentation prioritize Windows. Users should treat non-Windows platforms as future compatibility work.
  Evidence: README.md states: 'Windows-first is the accurate description today... Linux and macOS should be treated as future compatibility work rather than current parity.'
  Source: session=867d92a1-8239-4fdf-8fd8-981a5a2deafd turn=turn-3

### Detailed Memory Index
- `memory/architecture.md` - Architecture
- `memory/bugs.md` - Bugs
- `memory/daily/2026-05-21.md` - Daily Journal
- `memory/lessons.md` - Lessons
- `memory/workflows.md` - Workflows
<!-- pp-echo-memory:end -->
