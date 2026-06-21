# Memory Architecture

pp-Echo now treats long-term memory as four explicit layers: Core Memory,
Episodic Memory, File Memory, and Learning Memory. They cooperate, but their
storage, approval rules, and runtime responsibilities stay separate.

## Core Memory

Core Memory is the small, curated snapshot that may be injected into the model at session start. It is for stable, high-value facts only: user preferences, durable project facts, explicit decisions, repeatable workflows, and important agent notes.

Core Memory is intentionally bounded. More memory is not better; accurate, stable, controllable, and auditable memory is better.

Each item is stored as structured data with an id, scope, section, type, content, provenance, confidence, status, timestamps, supersession history, optional expiry, and metadata. The active statuses are:

- `pending`: proposed but not injectable.
- `active`: approved and eligible for the next session snapshot.
- `rejected`: blocked or declined, never injected.
- `archived`: historical record, never injected.

Scopes:

- `workspace`: project-specific memory isolated by workspace id.
- `global`: user-level preferences only. Project facts, workflows, and error fixes are not allowed as global memory.

Sections render in a fixed order:

- `user_profile`
- `project_profile`
- `agent_notes`

Default budgets are character based:

- `user_profile`: 1200 chars
- `project_profile`: 2000 chars
- `agent_notes`: 1500 chars
- total snapshot: 4000 chars

When memory exceeds budget, the renderer selects whole memory items by confidence, update time, and type weight. It does not silently delete, compress, or cut sentences.

## Episodic Memory

Episodic Memory is the existing history retrieval system: chunks, keyword/vector/hybrid retrieval, BM25, embeddings, and reranking. It is used to recall prior conversation details only when relevant. Retrieved snippets remain separate from Core Memory and include source metadata.

Episodic snippets are not promoted to Core Memory automatically. Promotion must go through candidate creation, safety checks, dedupe/conflict checks, pending state, and approval.

The stable `memory.enable` project config key controls this episodic/history
memory layer. It is retained for existing workspaces, but it is not a global
switch for every memory subsystem. Effective runtime recall also respects
`memory.episodic_memory.enabled`; Core Memory and File Memory can remain
available when Episodic Memory is disabled. UI status labels should call this
`Episodic memory`, not generic `Memory`, to avoid confusing it with the whole
memory system.

## File Memory and Learning Memory

File Memory indexes durable Markdown files such as `MEMORY.md` and
`memory/**/*.md` for explicit search/read workflows. Learning Memory extracts
candidate lessons and can write approved or auto-applied items into those
Markdown files. Neither layer bypasses Core Memory approval, and neither layer
depends on `memory.enable`.

## Service Boundary

`CoreMemoryService` is the single policy entry point for CLI, tools, runtime,
and Web/API routes. `CoreMemoryStore` only owns SQLite persistence, CRUD,
queries, and migrations. This keeps governance behavior consistent:

- `propose(candidate, source, reason)`
- `approve(memory_id, actor)`
- `reject(memory_id, actor, reason)`
- `archive(memory_id, actor, reason)`
- `replace(old_id, candidate, actor, reason)`
- `snapshot(workspace_id, session_id)`
- `search(query, scope, workspace_id)`
- `audit(memory_id, limit)`

Every write path records an audit row with action, actor, source, before/after
status, reason, created time, and metadata. Duplicate, safety, conflict, budget,
replacement, archive, and defensive snapshot skips are traceable.

## Approval Flow

Long-term memory is not active by default.

The safe write path is:

1. Extract or submit a candidate.
2. Run safety scan.
3. Run dedupe check.
4. Run conflict detection.
5. Store as `pending`.
6. User approves or rejects.
7. Approved memory becomes `active` and appears in the next session snapshot.

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
```

`merge-preview` detects duplicate active memory groups. `merge-apply` creates
pending replacement candidates and does not archive source memories until the
replacement is approved.

`compact-preview` reports budget pressure, skipped ids, and compaction groups.
`compact-apply` creates pending replacement candidates for over-budget sections.
The default summarizer is deterministic and local. `automation.use_llm_summary`
can be enabled later; if no LLM summarizer is registered, pp-Echo records a
`llm_unavailable_deterministic_fallback` summary method and still uses the local
deterministic summarizer.

## Safety Rules

Candidates are rejected when they look like secrets, credentials, API keys, tokens, passwords, prompt injection, high-risk shell instructions, credential exfiltration, or invisible/control-character tricks. Rejected items keep their structured record and reason for audit.

The snapshot renderer repeats the safety scan defensively. If an active memory
is later considered unsafe, it is skipped and an audit warning is written instead
of being injected.

## Runtime Extraction

The runtime recognizes explicit user instructions such as `记住...`, `以后...`,
`remember...`, and `from now on...`. These create Core Memory candidates with
session and turn provenance. They remain pending unless configuration explicitly
allows auto-approval for explicit user memory.

Pending, rejected, and archived memories are never injected. A session snapshot
is frozen; approvals made after a session starts affect the next session,
restore, or fork, not the already-built snapshot.

## API Management

The Web/API management surface calls the same `CoreMemoryService`:

- `GET /api/memory/core/pending`
- `GET /api/memory/core/active`
- `POST /api/memory/core/propose`
- `POST /api/memory/core/{id}/approve`
- `POST /api/memory/core/{id}/reject`
- `POST /api/memory/core/{id}/archive`
- `POST /api/memory/core/{id}/replace`
- `GET /api/memory/core/snapshot`
- `GET /api/memory/core/audit`
- `GET /api/memory/core/compact-preview`
- `POST /api/memory/core/compact-apply`
- `GET /api/memory/core/merge-preview`
- `POST /api/memory/core/merge-apply`
- `GET /api/memory/core/provider/status`

The UI should not auto-merge or auto-compact memories; it should present pending,
active, snapshot, and audit views over these routes.

## Provider Interface

`MemoryProviderPlugin` is reserved for additive providers such as Honcho or
Mem0-style plugins. The built-in Core Memory remains authoritative for the
curated snapshot. Providers may prefetch context, sync turns, extract candidates
on session end, mirror core writes, and report status, but they do not replace
Core Memory.

The default provider is `LocalMemoryProviderPlugin`, a small SQLite mirror stored
at `.pp-agent/core-memory-provider.db`. It records mirrored core writes and turn
sync metadata for audit/debugging. Set `core_memory.provider.enabled=false` to
use `NoopMemoryProviderPlugin`.

## Hermes Alignment

This design follows the Hermes-style split:

- bounded core memory
- curated and approved facts
- stable session snapshot
- workspace scoped project facts
- separate episodic/session search
- audit trail for rejected, archived, and superseded records

The prompt injection order is:

1. System Instructions
2. Core Memory Snapshot
3. Workspace Context
4. Retrieved Episodic Memory
5. Attachment/File Memory Preview
6. Current Conversation
