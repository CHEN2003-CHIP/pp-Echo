# Markdown-first Memory Governance

pp-Echo uses Markdown files as the durable source of truth for long-term
memory. Core Memory is now the governance layer over that source of truth, not
a second prompt fact store.

## Layers

- Markdown Memory is the fact source: `global/MEMORY.md`, workspace
  `MEMORY.md`, and workspace `memory/**/*.md`.
- Core Memory governs candidates, safety checks, dedupe, conflicts, approval,
  audit, merge/compact previews, and Markdown patch previews.
- `memory_search` and `memory_get` retrieve Markdown memory chunks on demand.
- `GlobalMemoryContextHook` and `ProjectMemoryContextHook` inject the current
  Markdown files on each context transform.

## Remember Flow

For an explicit request such as "remember that I prefer concise answers":

1. Runtime or a tool proposes a Core Memory candidate.
2. Core Memory builds a Markdown patch preview with a stable marker.
3. Approval applies the patch to the routed Markdown file by default.
4. The File Memory index is refreshed when available.
5. The next model turn reads the updated Markdown through the global or
   project memory hook.

Already-sent model requests are not changed retroactively. The guarantee is
that the next context build sees the updated Markdown.

## Routing

- `global/user_profile/preference` writes to `global/MEMORY.md` under
  `User Preferences`.
- `global/user_profile/general` writes to `global/MEMORY.md` under
  `User Notes`.
- `workspace/project_profile/project_fact` writes to `MEMORY.md` under
  `Project Facts`.
- `workspace/project_profile/decision` writes to `MEMORY.md` under
  `Decisions`.
- `workspace/project_profile/workflow` writes to `MEMORY.md` under
  `Workflows`.
- `workspace/agent_notes/error_fix` writes to `memory/bugs.md` under
  `Bug Fixes`.
- `workspace/agent_notes/general` writes to `memory/lessons.md` under
  `Lessons`.
- Other workspace memory writes to `MEMORY.md` under `Notes`.

Every written bullet includes a `pp-memory:id=...` marker so approval is
idempotent and later exports do not duplicate old active memories.

## Core Memory Hook

`CoreMemoryContextHook` is kept for compatibility and debugging. By default it
does not insert SQLite active memories into the prompt. It records governance
metadata for trace/debug surfaces and can still render a debug snapshot when
called directly.

## Learning Boundary

Learning can continue writing Markdown notes and managed sections. Explicit
user memory should prefer the Core Memory proposal and approval path, because
that path records safety, review, audit, and the Markdown patch target before
the fact becomes active.

## Migration

Use `pp-agent memory export-to-markdown` or the `memory_export_to_markdown`
tool to export old active SQLite Core Memory records that do not already have a
Markdown marker. Export uses the same router and writer as normal approval and
records `exported_to_markdown` audit entries.
