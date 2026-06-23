# Memory Architecture

pp-Echo treats long-term memory as Markdown-first governed context. Markdown
files are the durable source of truth; Core Memory is the governance, preview,
approval, audit, and trace layer over those files. Episodic Memory, File
Memory, and Learning Memory remain separate cooperating layers.

## Markdown Memory

Long-term facts land in human-readable Markdown:

- `global/MEMORY.md` for global user preferences and notes.
- workspace `MEMORY.md` for project facts, decisions, workflows, and notes.
- workspace `memory/**/*.md` for detailed bug, lesson, workflow, and journal
  notes.

These files are injected by `GlobalMemoryContextHook` and
`ProjectMemoryContextHook`, which read the files each time context is
transformed. After approval writes Markdown, the next model turn can see the
new memory.

## Core Memory Governance

Core Memory manages candidate lifecycle and audit. It does not act as the
default prompt fact source.

Each governed item is stored in SQLite with id, scope, section, type, content,
provenance, confidence, status, timestamps, supersession history, optional
expiry, and metadata. Active statuses are:

- `pending`: proposed but not applied as durable Markdown memory.
- `active`: approved and, by default, applied to Markdown.
- `rejected`: blocked or declined.
- `archived`: retained for history but no longer active governance state.

Core Memory remains bounded for previews and debug reports. The SQLite
snapshot renderer still exists, but `CoreMemoryContextHook` is debug-only by
default and does not insert active SQLite memories into the prompt.

## Service Boundary

`CoreMemoryService` is the shared policy entry point for CLI, tools, runtime,
and Web/API routes. `CoreMemoryStore` owns the SQLite governance ledger. The
Markdown router and writer own fact-source patches.

Important service operations:

- `propose(candidate, source, reason)`
- `markdown_preview(memory_id)`
- `approve(memory_id, actor, apply_to_markdown=True, immediate_effect=True)`
- `markdown_apply(memory_id, actor, reason)`
- `reject(memory_id, actor, reason)`
- `archive(memory_id, actor, reason)`
- `replace(old_id, candidate, actor, reason)`
- `snapshot(workspace_id, session_id)` for debug/governance only
- `search(query, scope, workspace_id)` for governance records
- `audit(memory_id, limit)`
- `export_active_core_memories_to_markdown()`

Every write path records audit metadata. Markdown apply records target path,
heading, marker id, before/after content hashes, diff hash, and whether
immediate effect was enabled.

## Approval Flow

The safe write path is:

1. Extract or submit a candidate.
2. Run safety scan.
3. Run dedupe check.
4. Run conflict detection.
5. Store as `pending`.
6. Preview the Markdown patch.
7. User approves or rejects.
8. Approval applies the Markdown patch by default.
9. File Memory index refreshes when available.
10. The next context transform reads the updated Markdown.

CLI commands:

```powershell
pp-agent memory propose "Prefer concise engineering answers." --section user_profile --type preference
pp-agent memory pending
pp-agent memory approve <memory-id>
pp-agent memory reject <memory-id>
pp-agent memory archive <memory-id>
pp-agent memory replace <old-memory-id> "Use pytest for focused checks." --type workflow
pp-agent memory snapshot
pp-agent memory audit [memory-id]
pp-agent memory compact-preview
pp-agent memory compact-apply --reason "manual review"
pp-agent memory merge-preview
pp-agent memory merge-apply --reason "dedupe"
pp-agent memory provider-status
pp-agent memory export-to-markdown
```

## File Memory Retrieval

File Memory indexes durable Markdown files such as `MEMORY.md`,
`global/MEMORY.md`, and `memory/**/*.md` for explicit search/read workflows.
`memory_search` finds relevant chunks and `memory_get` reads exact line ranges.
This retrieval layer is separate from Core Memory governance and does not
depend on `memory.enable`.

## Episodic Memory

Episodic Memory is the conversation-history retrieval layer: chunks,
keyword/vector/hybrid retrieval, BM25, embeddings, and reranking. It recalls
prior conversation details only when relevant. Retrieved snippets remain
separate from Markdown Memory and Core Memory governance.

The stable `memory.enable` config key controls this episodic/history layer. It
is not a global switch for Core Memory or File Memory.

## Learning Memory

Learning extracts candidate lessons and can write approved or auto-applied
items into Markdown memory files. Explicit user memory should prefer the Core
Memory proposal/approval path so safety, review, target preview, and audit are
recorded before the fact is applied.

Learning-managed sections and Core-approved bullets can coexist in
`MEMORY.md`; Core-approved bullets use `pp-memory:id=...` markers for
idempotency.

## Provider Interface

`MemoryProviderPlugin` is reserved for additive providers such as Honcho or
Mem0-style plugins. The built-in Markdown files remain authoritative for
durable facts. Providers may prefetch context, sync turns, extract candidates,
mirror governance writes, and report status, but they do not replace Markdown
Memory.

The default provider is `LocalMemoryProviderPlugin`, a small SQLite mirror
stored at `.pp-agent/core-memory-provider.db`. It records mirrored governance
writes and turn sync metadata for audit/debugging.

## Prompt Order

The intended prompt context order is:

1. System Instructions
2. Global/Project Markdown Memory
3. Workspace Context
4. Retrieved Episodic Memory
5. Attachment/File Memory Preview
6. Current Conversation
