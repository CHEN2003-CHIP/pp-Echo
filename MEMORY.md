# Project Memory

<!-- pp-echo-memory:begin -->
## pp-Echo Bootstrap Memory

Short-lived prompt memory for durable preferences, project decisions, and navigation.
Use `memory_search` and `memory_get` for detailed notes in `memory/**/*.md`.

### Learned Notes
Source: session=8c695242-be85-4232-aab5-093b1d973659 turn=turn-4
  Source: session=8c695242-be85-4232-aab5-093b1d973659 turn=turn-5
- **Memory Management Location**: Project-specific learning and memory are maintained in dedicated files: MEMORY.md for core state and PROJECT_LEARNING.md for accumulated insights, alongside a 'memory' folder for detailed context.
  Evidence: Existence of MEMORY.md, PROJECT_LEARNING.md, and a 'memory' directory in the root.
- **Smoke Test Documentation Naming**: Use the naming convention 'docs/worktree-smoke-[component].md' for isolated smoke test documentation files.
  Evidence: The task explicitly requested creating 'docs/worktree-smoke-web.md' with a specific content line indicating an isolated worktree smoke test.
  Source: session=8778eb07-2fa5-4bc2-8529-d8028df354d9 turn=turn-1
- **Smoke Test Documentation Naming**: Isolated worktree smoke tests for web components should be documented in files named `docs/worktree-smoke-web.md` containing a single line summary.
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

### Detailed Memory Index
- `memory/architecture.md` - Architecture
- `memory/bugs.md` - Bugs
- `memory/lessons.md` - Lessons
- `memory/workflows.md` - Workflows
<!-- pp-echo-memory:end -->
