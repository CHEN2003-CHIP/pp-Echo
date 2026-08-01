# Mission 08: Durable Workflow Recovery and Idempotent Resume Design

Status: Planning / authoritative design accepted; 08B, 08C, 08D-P, 08D-S, 08D-R, and 08D-T implemented and ready for human review

Scope type: AUTHORITATIVE DESIGN RECORD WITH 08B/08C/08D-P/08D-S/08D-R/08D-T IMPLEMENTATION RECORD

Mission 08 defines durable recovery for the existing controlled coding workflow. Mission 08B implements the checkpoint data contract described below. Mission 08C implements atomic coding-owned checkpoint persistence, revision/CAS, and read-only reconciliation foundation. Mission 08D-P freezes schema v1 and adds schema v2 continuation intent/correlation contracts only. Mission 08D-S adds generic SessionStore durable message evidence and read-only lookup plumbing. Mission 08D-R adds explicit one-boundary resume. Mission 08D-T adds schema v3 generic terminal outcome and ordinary completion terminality. Mission 07 recovery execution, CLI, and doctor integration remain unimplemented.

## Mission

Mission 08 makes the single-task controlled coding workflow recoverable across process exit, restart, pending approval, pending tool action, validation pending, repair pending, re-validation pending, repeated resume, repeated approval, and partially stale or inconsistent state.

The durable design is:

`session transcript + pending action lifecycle + coding workflow checkpoint -> inspect/reconcile -> explicit resume decision -> explicit execution only when requested`

## Human Architecture Decision

The approved design direction is:

- workflow recovery checkpoint is owned by `src/pp_agent/coding`;
- `SessionStore` remains responsible only for transcript, runtime/session snapshots, and generic durable message evidence;
- `PendingActionStore` remains the only owner of staged action and approval lifecycle;
- checkpoint stores only safe pending action references and never copies approval state;
- `TraceStore` is diagnostic and is not a recovery fact source;
- Mission 07 `repair_attempted`, `revalidation_attempted`, validation execution count, and terminal outcome must be durable;
- checkpoint must be versioned, atomic, bounded, and fail-closed;
- recovery must inspect and reconcile before any explicit execution;
- no generic workflow engine;
- no full session format rewrite;
- no OpenCode session, permission, or agent-loop framework port.

## pp-Echo Evidence Reconfirmed

The design is based on these current pp-Echo behaviors:

- `src/pp_agent/storage/sessions.py` persists session JSONL snapshots for transcript, queued messages, pending tool calls, pending plan token, and runtime session restoration. It does not own coding workflow phase, repair counts, re-validation counts, or final Mission 07 completion.
- `src/pp_agent/storage/approvals.py` owns pending action files and approval lifecycle states. It deduplicates active actions by proposal/effect identity and carries lifecycle states such as staged, grant-attached, execution-in-progress, consumed, failed, and rejected.
- `ApprovePendingActionTool` treats already consumed grants as idempotent success, but a crash after real tool execution and before consumed state remains a fail-closed window.
- file edit checkpoints exist for safe mutation evidence and rollback support, but they are not workflow checkpoints.
- `validation_execution.py`, `validation_repair.py`, `validation_outcome.py`, and `pytest_provenance.py` define Mission 07 validation and repair contracts. The repair and re-validation counters are run-local today.
- pytest provenance artifacts are trusted, bounded, and consumed during verification. They are not retained as durable final workflow proof.
- `runtime_loop.py` owns controlled coding execution but does not persist coding workflow phase or terminal completion.
- Mission 08D preflight confirmed that `PendingActionStore` is not a complete durable bounded tool-result authority. A consumed grant without a SessionStore external approval result message is not resumable and must fail closed.
- Mission 08D preflight confirmed that `AgentRuntime.continue_()` does not persist a durable model-continuation intent before provider request. pp-Echo does not claim provider model request exactly-once.
- `TraceStore` is append-only observability. It is useful for audit and explanation, but no recovery path treats trace as authoritative state.
- `WorkspaceApplyLock` and current storage locks cover narrower mutation paths. Mission 08 needs a coding workflow single-writer rule without a distributed lock system.

## OpenCode Source Pin

OPENCODE REFERENCE LEVEL: LIGHT TARGETED

| Repository | Branch/tag | Commit SHA | Date | File | Symbol | Question |
| --- | --- | --- | --- | --- | --- | --- |
| `https://github.com/anomalyco/opencode` | `dev` | `cf7503687a2485621a690d18c4b0d1ff2060bc3e` | 2026-07-13 | `packages/opencode/src/storage/storage.ts` | `Storage.Service`, `read`, `write`, `update`, `list` | storage boundary, per-file lock, migration, JSON persistence |
| `https://github.com/anomalyco/opencode` | `dev` | `cf7503687a2485621a690d18c4b0d1ff2060bc3e` | 2026-07-13 | `packages/opencode/src/storage/schema.ts` | `SessionTable`, `MessageTable`, `PartTable` exports | database-backed durable session/message state |
| `https://github.com/anomalyco/opencode` | `dev` | `cf7503687a2485621a690d18c4b0d1ff2060bc3e` | 2026-07-13 | `packages/opencode/src/session/session.ts` | `Session.Service`, `fromRow`, `toRow`, `create`, `patch`, `messages` | session ownership and terminal/archive metadata |
| `https://github.com/anomalyco/opencode` | `dev` | `cf7503687a2485621a690d18c4b0d1ff2060bc3e` | 2026-07-13 | `packages/opencode/src/session/message-v2.ts` | `MessageV2.page`, `stream`, `latest`, `toModelMessagesEffect` | rebuilding model messages from persisted message/part rows |
| `https://github.com/anomalyco/opencode` | `dev` | `cf7503687a2485621a690d18c4b0d1ff2060bc3e` | 2026-07-13 | `packages/opencode/src/event-v2-bridge.ts` | `EventV2Bridge.Service.publish` | durable event routing and sync event metadata |
| `https://github.com/anomalyco/opencode` | `dev` | `cf7503687a2485621a690d18c4b0d1ff2060bc3e` | 2026-07-13 | `packages/opencode/src/permission/index.ts` | `Permission.Service`, `ask`, `reply`, `list` | permission pending state and approval response semantics |
| `https://github.com/anomalyco/opencode` | `dev` | `cf7503687a2485621a690d18c4b0d1ff2060bc3e` | 2026-07-13 | `packages/opencode/src/session/run-state.ts` | `SessionRunState.Service`, `ensureRunning`, `startShell`, `cancel` | in-process busy/run coordination |
| `https://github.com/anomalyco/opencode` | `dev` | `cf7503687a2485621a690d18c4b0d1ff2060bc3e` | 2026-07-13 | `packages/opencode/src/session/status.ts` | `SessionStatus.Service`, `get`, `set`, `list` | runtime status as process-local state |

## OpenCode Targeted Comparison

| Question | pp-Echo current behavior | OpenCode behavior | Reusable principle | Not suitable for pp-Echo | Decision |
| --- | --- | --- | --- | --- | --- |
| session recovery ownership | `SessionStore` owns transcript/snapshot only; coding workflow state is absent | `Session.Service` maps session rows to typed info and uses message/part rows for replay | keep session owner narrow and typed | database-backed session framework | ADOPT PRINCIPLE |
| snapshot/event reconciliation | pp-Echo session JSONL snapshots restore runtime state; trace is not recovery authority | durable event bridge emits versioned sync metadata, while DB tables carry durable rows | separate event/audit streams from durable state | full event sourcing and DB schema | ADAPT NARROWLY |
| pending permission/action recovery | `PendingActionStore` persists pending action and approval lifecycle | permission pending map is process-local; session permission rules can persist | pp-Echo should keep its stronger durable pending action owner | OpenCode in-process permission model | REJECT |
| idempotent continuation | pp-Echo can restore generic runtime session but not coding phase | model messages are rebuilt from persisted message/part rows; pending/running tool calls are represented as interrupted for replay | make interrupted state explicit and bounded | replaying full OpenCode message framework | ADAPT NARROWLY |
| crash-safe transition commit | pp-Echo lacks coding checkpoint CAS/revision | storage has per-target in-process write locks; DB tables provide stronger durable consistency in newer paths | use single-writer lock and revision checks | database transaction layer | ADAPT NARROWLY |
| completed session terminality | pp-Echo lacks coding completion marker | sessions have archive/status metadata; runtime status is separate from persisted session content | terminal state must be explicit and repeatable | OpenCode session lifecycle semantics | ADAPT NARROWLY |
| repeated resume behavior | coding resume does not exist | run-state prevents duplicate in-process runners; completed/idle status is explicit in process | repeated resume should be inspectable and idempotent | process-local runner map as durable proof | ADAPT NARROWLY |

## OpenCode Non-adoption Boundary

Mission 08 must not copy:

- complete session framework;
- complete permission framework;
- complete agent loop;
- complete event sourcing architecture;
- database layer;
- background worker model;
- distributed scheduling;
- generic workflow engine;
- cross-machine recovery;
- a state model that conflicts with `PendingActionStore`.

OPENCODE ADOPTION DECISION: PARTIAL TARGETED REFERENCE ONLY; NO FRAMEWORK PORT

## Ownership Decision

| Area | Authoritative owner | Owns | Must not own |
| --- | --- | --- | --- |
| Session authority | `SessionStore` / `SessionHost` | session identity, transcript, runtime/session snapshot, existing generic continuation state | coding workflow phase, repair count, re-validation count, Mission 07 final completion |
| Pending action authority | `PendingActionStore` | staged action payload, approval token, approval lifecycle, action execution lifecycle | coding workflow phase, repair policy, validation outcome |
| Coding workflow recovery authority | new coding-owned checkpoint contract | workflow kind, phase, revision, selected validation command identity, validation count, repair attempted, re-validation attempted, last transition, pending action reference, final outcome summary, completion marker | approval state, raw tool result authority, runtime transcript |
| Trace authority | `TraceStore` | diagnostics, audit, explainability | resume authority, final workflow truth |
| CLI authority | existing coding/workflow CLI owner | presentation, explicit inspect/resume/cancel entrypoints later | durable state ownership |

## Authoritative vs Derived State

| State | Authoritative owner | Durable location | Derived or copied? | Conflict behavior |
| --- | --- | --- | --- | --- |
| session state | `SessionStore` | session JSONL | authoritative | corrupt session blocks resume if needed |
| pending action | `PendingActionStore` | pending action files | authoritative | checkpoint mismatch fails closed |
| approval state | `PendingActionStore` | pending action lifecycle | authoritative | checkpoint must not override |
| tool result | tool boundary plus pending lifecycle | pending lifecycle and bounded result surfaces | referenced, not copied as authority | uncertain side effect fails closed |
| workflow phase | coding checkpoint | `.pp-agent/workflow-checkpoints/coding/` | authoritative for coding workflow only | invalid combination fails closed |
| `repair_attempted` | coding checkpoint | checkpoint | authoritative | count contradiction fails closed |
| `revalidation_attempted` | coding checkpoint | checkpoint | authoritative | count contradiction fails closed |
| validation count | coding checkpoint | checkpoint | authoritative | values above two fail closed |
| selected logical command | coding checkpoint | digest/identity only | authoritative identity, command details from validation plan/proposal | missing digest blocks repair/revalidation |
| final `ValidationOutcome` | coding checkpoint | bounded final summary | authoritative summary | phase/outcome mismatch fails closed |
| completion | coding checkpoint | terminal marker | authoritative | completed is terminal and repeatable |
| model continuation intent | coding checkpoint schema v2 | checkpoint | authoritative intent only | committed intent prevents retry unless durable session evidence proves completion |
| model continuation completion evidence | `SessionStore` generic correlation metadata | session snapshot/messages | authoritative session fact, not workflow owner | missing or mismatched evidence fails closed |
| trace | `TraceStore` | trace JSONL | diagnostic-only | never resolves state conflict |
| CLI status | CLI serializer | stdout/report only | derived | never persisted as authority |

No state may have two authoritative owners.

## Checkpoint Contract

Conceptual name: `CodingWorkflowCheckpoint`.

| Field | Required? | Authority | Source | Write time | Sensitive? | Model-facing? | Nullable? | Corruption behavior |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `schema_version` | yes | checkpoint | constant | create/update | no | no | no | unknown/future version fails closed |
| `workflow_id` | yes | checkpoint | generated stable ID | create | no | no | no | missing/malformed fails closed |
| `session_id` | yes | session/checkpoint relation | `SessionStore` identity | create | no | no | no | mismatch fails closed |
| `workflow_kind` | yes | checkpoint | constant `controlled_coding` | create | no | no | no | unknown kind fails closed |
| `revision` | yes | checkpoint | monotonic integer | every transition | no | no | no | stale revision fails closed |
| `phase` | yes | checkpoint | phase contract | every transition | no | inspect summary only | no | invalid phase fails closed |
| `selected_validation_command_digest` | required after selection | checkpoint | normalized command identity | before first validation staging | digest only | safe summary only | yes before selection | missing after validation phase fails closed |
| `validation_execution_count` | yes | checkpoint | validation execution transitions | after each verified execution decision | no | summary yes | no | greater than two fails closed |
| `repair_attempted` | yes | checkpoint | repair transition | before repair continuation starts | no | summary yes | no | contradiction fails closed |
| `revalidation_attempted` | yes | checkpoint | revalidation transition | before re-validation staging/execution | no | summary yes | no | contradiction fails closed |
| `pending_action_ref` | optional | pending store reference | safe action reference and digest | after staging / while awaiting approval | safe reference only | no raw token | yes | missing referenced action fails closed unless phase no longer pending |
| `last_completed_action_ref` | optional | checkpoint reference | safe action reference/digest | after action reconciliation | safe reference only | no | yes | mismatch fails closed |
| `final_outcome_summary` | required for finalized/completed | checkpoint | typed `ValidationOutcome` summary | finalization | bounded/redacted | summary yes | yes before final | phase mismatch fails closed |
| `completion_marker` | required for completed | checkpoint | terminal transition | final completed write | no | summary yes | yes before completed | completed without marker fails closed |
| `created_at` | yes | checkpoint | clock | create | no | no | no | malformed fails closed |
| `updated_at` | yes | checkpoint | clock | every transition | no | no | no | malformed fails closed |
| `integrity_digest` | required when persisted in 08C | checkpoint | canonical JSON digest excluding digest field | every future write | digest only | no | yes in the 08B in-memory contract | present-but-bad digest fails closed |

The checkpoint must not store complete runtime objects, complete transcript, raw approval token, raw provenance nonce, raw attestation, full stdout/stderr, full patch, environment variables, secrets, or pickle data.

## Checkpoint Schema Versioning

Schema v1 is frozen. Existing v1 fields and cross-field semantics must remain readable and unchanged. V1 checkpoints must not contain v2 continuation fields, must not be silently upgraded, and must not be used for model continuation recovery. Future v1 reconciliation should return inspect-only or not-resumable for continuation recovery.

Schema v2 is continuation-intent capable. It keeps the existing Mission 07 durable fields and adds an optional `model_continuation_intent` subrecord. V2 remains frozen after 08D-T and must not contain v3 terminal outcome fields.

Schema v3 is generic-terminal-outcome capable. It keeps v2 continuation evidence fields and adds optional `terminal_outcome` for completed checkpoints. A completed schema v3 checkpoint must have both `completion_marker` and `terminal_outcome`, must not have active pending action evidence, and must not have an active continuation intent. Completed checkpoints are immutable.

The schema v3 terminal outcome fields are:

- `terminal_kind`: `ordinary_completion` or `validation_completion`;
- `completed_at`: UTC terminal timestamp, matching the completion marker;
- `reason_code`: bounded terminal reason;
- `session_completion_evidence_ref`: required for ordinary completion and forbidden for validation completion;
- `validation_outcome_summary`: required for validation completion and forbidden for ordinary completion.

Ordinary completion is written only when the coding recovery layer has exact SessionStore model-continuation completion evidence, a typed `ordinary_completion` terminal outcome, a completed continuation intent whose source action/result identity matches the checkpoint, and no active pending action for the session. `session_committed` is continuation evidence only; it is not workflow terminality. Workflow completion authority remains the `pp_agent.coding` checkpoint.

Validation terminal contract is defined in schema v3, but Mission 07 validation/repair/re-validation recovery is not implemented in 08D-T.

The store may load v1, v2, and v3 checkpoints, but replace must not silently change a checkpoint's schema version. V1/V2 checkpoints are not automatically migrated to v3. Migration is deferred to a later explicit design if ever required.

## Model Continuation Intent Contract

Schema v2 adds a single orthogonal continuation subrecord instead of expanding the phase list:

- `continuation_id`: opaque, bounded, non-empty identity. It is not a path, provider request id, approval token, provenance nonce, task text digest, or workflow id.
- `source_action_ref`: safe pending-action reference for the completed action/result that permits continuation.
- `source_result_digest`: stable bounded digest for the durable result evidence.
- `pre_call_session_id` and optional `pre_call_turn_id`: safe pre-call session identity markers.
- `state`: one of `intent_committed`, `session_committed`, or `blocked_uncertain`.
- `created_at`: UTC timestamp.
- optional `completed_session_evidence_ref`: future SessionStore generic correlation evidence for `session_committed`.
- optional `blocked_reason_code`: bounded reason for `blocked_uncertain`.

The contract implements durable at-most-one continuation intent. It does not claim exactly-once provider calls. After an intent is committed, automatic model retry is forbidden unless future reconciliation finds exact durable SessionStore completion evidence. If evidence is absent or mismatched, the continuation is `blocked_uncertain` and must fail closed.

`session_committed` means SessionStore contains generic durable evidence tied to the exact session id, continuation id, source action/result identity, durable response/turn identity, and completion marker. SessionStore may store only generic runtime correlation facts; it must not own coding phase, repair/re-validation counters, checkpoint revision, or workflow completion.

`grant_consumed + no durable SessionStore external approval result = blocked_uncertain = no model continuation = no tool re-execution`.

## Mission 08D-P Implementation Record

Mission 08D-P implements schema v2 continuation-intent contracts in `src/pp_agent/coding/workflow_checkpoint.py` and minimal store compatibility in `src/pp_agent/coding/workflow_checkpoint_store.py`.

Implemented:

- schema v1 remains `schema_version=1`, with frozen canonical serialization and no v2 fields;
- schema v2 is `schema_version=2` and can serialize/validate `ModelContinuationIntent`;
- continuation states are `intent_committed`, `session_committed`, and `blocked_uncertain`;
- session completion evidence is a bounded reference contract only, not a SessionStore implementation;
- v2 validates continuation identity, source action/result binding, session evidence correlation, active pending-action conflicts, completed checkpoint conflicts, and sensitive payload rejection;
- integrity digest includes v2 fields;
- store load supports v1 and v2;
- store replace rejects silent schema-version changes.

Not implemented in 08D-P:

- no model call, `runtime.continue_()`, resume execution, SessionStore read/write, PendingActionStore read/write, tool execution, staging, approval, CLI, doctor, Mission 07 recovery, storage migration, generic workflow engine, or new dependency.

OPENCODE REFERENCE LEVEL FOR 08D-P: LIGHT TARGETED

OPENCODE ADOPTION DECISION FOR 08D-P: ADAPT NARROW CORRELATION AND TERMINALITY PRINCIPLES ONLY; NO FRAMEWORK PORT

## Mission 08D-S Implementation Record

Mission 08D-S implements generic durable session correlation evidence in `src/pp_agent/storage/sessions.py` and minimal runtime write plumbing in `src/pp_agent/runtime/runtime.py`.

Implemented:

- new messages may carry `metadata["session_message_id"]` as a bounded stable session message identity;
- generic correlation metadata uses `metadata["session_correlation"]` and remains independent of coding workflow phase;
- external approval results recorded through `record_external_approval_result()` now bind exact session id, pending action identity, stable message identity, tool name, safe timestamp, and a deterministic bounded result digest;
- `AgentRuntime.continue_(continuation_id=...)` can record generic model continuation completion evidence on the persisted assistant response when a caller supplies an opaque continuation id;
- `SessionStore.lookup_external_tool_result_evidence()` and `SessionStore.lookup_model_continuation_completion_evidence()` provide read-only typed lookup results;
- lookup distinguishes found, not found, ambiguous, session missing, session corrupt, identity mismatch, and legacy evidence insufficient;
- duplicate matches, digest mismatch, malformed metadata, missing evidence, and legacy uncorrelated messages fail closed;
- old sessions remain loadable and are not migrated or silently backfilled.

Session correlation metadata may contain only:

- opaque action or continuation identity;
- result digest;
- stable message identity;
- generic correlation kind;
- durable completion marker timestamp;
- safe turn/source references and safe tool name.

Session correlation metadata must not contain:

- coding workflow phase, checkpoint revision, repair or re-validation counters, validation execution count, Mission 07 phase, resume decision, approval state copy, raw approval token, full tool result copy, full prompt, or full response.

External tool-result evidence is established only after the session message containing the bounded result is durably persisted. `PendingActionStore` grant consumption without matching durable session result evidence is not resumable. The future recovery rule is:

`grant_consumed + no matching durable SessionStore external tool result evidence = not resumable`

Continuation completion evidence is established only after the assistant/model response and its generic correlation metadata are durably persisted in SessionStore. Provider return, trace emission, CLI output, checkpoint intent, or in-memory state alone do not count as completion. The future recovery rule is:

`committed continuation intent + no matching durable SessionStore completion evidence = blocked_uncertain; automatic model retry forbidden`

08D-S does not claim a cross-store transaction between PendingActionStore, SessionStore, checkpoint storage, tool side effects, or provider requests. It provides durable session facts and exact evidence lookup so future 08D-R reconciliation can fail closed instead of guessing.

Crash-window semantics fixed by 08D-S:

- tool side effect plus consumed grant but no session result evidence remains not resumable;
- session result evidence without checkpoint update lets future recovery advance checkpoint only, without re-executing the tool;
- committed continuation intent without completion evidence remains blocked uncertain and must not retry the model automatically;
- response plus matching completion evidence without checkpoint update lets future recovery advance checkpoint only, without re-calling the model;
- response without matching continuation id is not completion evidence.

Not implemented in 08D-S:

- no `resume_coding_workflow()`;
- no coding recovery adapter execution;
- no tool execution, staging, approval, or PendingActionStore lifecycle mutation;
- no real provider call beyond existing runtime behavior;
- no Mission 07 recovery execution;
- no CLI or doctor integration;
- no session migration, second session/tool result store, generic event-sourcing framework, or new dependency.

OPENCODE REFERENCE LEVEL FOR 08D-S: NONE

OPENCODE ADOPTION DECISION FOR 08D-S: USE PP-ECHO SESSIONSTORE SOURCE ONLY; NO OPENCODE FRAMEWORK PORT

## Mission 08B Implementation Record

Mission 08B implements `src/pp_agent/coding/workflow_checkpoint.py` as a pure coding-owned data contract.

Implemented:

- `CodingWorkflowCheckpoint` and its nested safe-reference, final-outcome-summary, and completion-marker contracts are immutable frozen dataclasses.
- Schema version is `1`; workflow kind is `controlled_coding`; initial revision is `0`.
- `CodingWorkflowPhase` implements the coding-specific phase set defined by this design, including explicit completed and blocked phases.
- Timestamps are timezone-aware UTC values serialized with the ISO-8601 `Z` suffix.
- Serialization is JSON-safe and deterministic; canonical JSON uses sorted keys and compact separators.
- Checkpoint canonical JSON is bounded to 16 KiB.
- Integrity identity uses SHA-256 over canonical JSON excluding `integrity_digest`.
- Unknown fields, unknown enum values, malformed nested data, unsupported/future schema versions, oversized canonical output, and digest mismatches fail closed.
- Pending actions are represented only by `PendingActionReference`; approval lifecycle, token, payload, and result remain owned by `PendingActionStore`.
- Selected validation command identity is digest-only and stores no command text.
- Mission 07 `validation_execution_count`, `repair_attempted`, `revalidation_attempted`, final outcome summary, and terminal completion requirements are validated without changing runtime semantics.
- Completed state requires `phase=completed`, a bounded `final_outcome_summary`, and an explicit `completion_marker`.

Not implemented in 08B:

- no checkpoint file storage, directory creation, atomic temp-and-replace write, locking, or retention;
- no compare-and-set update or stale revision reconciliation;
- no `SessionStore`, `PendingActionStore`, or `TraceStore` inspection;
- no inspect, reconcile, resume, cancel, CLI, doctor, runtime-loop, approval, tool, or Mission 07 execution integration;
- no session format rewrite, storage migration, dependency addition, generic workflow engine, or OpenCode framework port.

OPENCODE REFERENCE LEVEL FOR 08B: NONE

OPENCODE ADOPTION DECISION FOR 08B: NO NEW OPENCODE REFERENCE; USE 08A-D PINNED DESIGN ONLY

## Mission 08C Implementation Record

Mission 08C implements `src/pp_agent/coding/workflow_checkpoint_store.py` as the coding-owned checkpoint store and read-only reconciliation foundation.

Implemented:

- store owner is `pp_agent.coding`, via `CodingWorkflowCheckpointStore`;
- namespace is `.pp-agent/workflow-checkpoints/coding/`;
- checkpoint filenames are `sha256(workflow_id).json`, while the true `workflow_id` remains inside the checkpoint payload;
- create requires a valid 08B checkpoint at revision `0` and refuses duplicate create;
- persisted checkpoints include the 08B SHA-256 `integrity_digest`;
- write path uses same-directory owned temp files, flush, file fsync, `os.replace`, and best-effort directory fsync where supported;
- reads are bounded before decode and accept only UTF-8 single JSON objects;
- load verifies schema, invariants, integrity digest, and requested workflow identity;
- create and replace use the existing `WorkspaceApplyLock` as a conservative workspace single-writer lock;
- replace requires `expected_revision`, verifies current revision, requires exactly the next revision, and rejects workflow/session identity changes;
- completed checkpoints are terminal and immutable;
- failures return typed storage errors such as not found, already exists, stale revision, terminal, lock unavailable, oversized, corrupt, unsupported schema, integrity failure, identity mismatch, invariant violation, and I/O failure;
- temporary files are never recovery authority; only the canonical `.json` checkpoint file is loaded;
- `CodingRecoveryEvidence`, `PendingActionEvidence`, `CheckpointReconciliationResult`, and `ReconciliationDecision` provide read-only reconciliation over safe evidence summaries.

Read-only reconciliation decisions implemented:

- `completed`;
- `inspect_only`;
- `awaiting_authoritative_action`;
- `blocked_corrupt_state`;
- `blocked_inconsistent_state`;
- `stale_revision`;
- `not_resumable`;
- `needs_boundary_reconciliation`.

Not implemented in 08C:

- no model continuation, tool execution, action staging, approval mutation, validation, repair, or re-validation;
- no `SessionStore` schema change and no `PendingActionStore` schema change;
- no direct store adapters that read full session transcript, raw approval token, raw pending payload, raw tool result, raw trace, stdout, stderr, or file contents;
- no cross-store transaction claim between checkpoint, session, pending action, approval, model call, or tool side effect;
- no CLI inspect/resume/cancel;
- no doctor integration;
- no generic workflow engine, database, storage migration, new dependency, or OpenCode framework port.

OPENCODE REFERENCE LEVEL FOR 08C: NONE

OPENCODE ADOPTION DECISION FOR 08C: NO NEW OPENCODE REFERENCE; USE 08A-D PINNED DESIGN ONLY

## Storage Design

Storage owner: coding recovery module under `src/pp_agent/coding`.

Recommended namespace:

`.pp-agent/workflow-checkpoints/coding/`

File naming:

- one JSON checkpoint per `workflow_id`;
- implementation uses `sha256(workflow_id).json` as the file name;
- include `session_id` inside the file, not only in the filename;
- avoid raw user task text in filenames.

Rules:

- UTF-8 JSON only;
- bounded file size;
- canonical JSON for integrity digest;
- atomic temp-file write followed by replace;
- no database required;
- unknown fields fail closed for schema version 1;
- unknown or future schema version fails closed;
- malformed JSON, oversized file, bad digest, or workspace containment failure blocks resume;
- stale revision fails closed;
- cleanup and retention are separate policy work and must not delete active checkpoints automatically;
- file permissions should match the current local `.pp-agent` storage posture and avoid broader exposure;
- paths must remain contained in the active workspace `.pp-agent` tree.

If a database becomes required, Mission 08 must stop for human storage review.

## Concurrency and Revision Model

Mission 08 assumes a local single-workspace writer model, not distributed execution.

Rules:

- every checkpoint transition increments `revision`;
- update requires compare-and-set on the last loaded revision;
- stale revision returns `stale_revision` and executes nothing;
- concurrent resume attempts acquire the workflow lock or fail with inspectable busy/stale state;
- lock failure does not guess state and does not execute;
- a crash while holding the lock is handled by lock expiry or stale lock policy only if that policy is explicit and bounded;
- completed checkpoint is immutable except for optional read-only inspection metadata that does not alter terminal facts;
- terminal state must not be rewritten into a non-terminal state.

The existing workspace lock may be reused only if it can protect the coding workflow checkpoint write path without expanding into a distributed lock. If it cannot, Mission 08B must define a small coding workflow lock.

## Phase Contract

Mission 08 keeps a minimal coding-specific phase contract. It is not a generic state machine.

| Phase | Entry condition | Durable facts | Allowed next transitions | Restart behavior | Terminal? | Impossible combinations |
| --- | --- | --- | --- | --- | --- | --- |
| `prepared` | workflow prepared, no model continuation committed | workflow/session identity | `runtime_started` | inspect and continue only by explicit resume | no | pending action ref present |
| `runtime_started` | controlled coding loop has begun | revision, session relation | `awaiting_tool_approval`, `awaiting_validation_approval`, `finalized` | inspect session and pending actions | no | completed marker |
| `awaiting_tool_approval` | tool action staged by coding workflow | pending action ref with role `tool` | `tool_completed`, blocked state | show approval requirement | no | missing active/ref-compatible action |
| `tool_completed` | referenced tool action reconciled complete | last completed action ref | validation staging or runtime continuation | inspect side effect uncertainty | no | active same action still pending |
| `awaiting_validation_approval` | validation action staged | selected command digest, pending action ref | `validation_completed`, blocked state | show validation approval requirement | no | missing command digest |
| `validation_completed` | validation result reconciled | count incremented, outcome summary for cycle | `repair_started`, `finalized` | inspect next legal transition | no | count over two |
| `repair_started` | trusted failed validation permits repair | `repair_attempted=true` | `awaiting_repair_tool_approval`, `repair_completed`, blocked state | continue only if safe | no | no trusted failure |
| `awaiting_repair_tool_approval` | repair tool action staged | pending action ref role `repair_tool` | `repair_completed`, blocked state | show approval requirement | no | `repair_attempted=false` |
| `repair_completed` | repair action reconciled | last repair action ref | `awaiting_revalidation_approval` | stage re-validation only explicitly | no | no selected command digest |
| `awaiting_revalidation_approval` | same command re-validation staged | `revalidation_attempted=true`, pending action ref | `revalidation_completed`, blocked state | show approval requirement | no | command digest mismatch |
| `revalidation_completed` | second validation reconciled | count is two, cycle outcome | `finalized` | inspect only before final write | no | count not two |
| `finalized` | final `ValidationOutcome` summary written | final outcome summary | `completed` | write completion marker only if revision current | no | missing final outcome |
| `completed` | completion marker committed | final outcome summary and marker | none | repeated resume returns completed | yes | active pending action for workflow |
| `blocked_corrupt` | checkpoint/session cannot be parsed or trusted | safe error summary | none without human action | inspect only | yes for automation | auto execution |
| `blocked_inconsistent` | authoritative stores disagree | safe error summary | none without human action | inspect only | yes for automation | auto execution |

Pending approval details should be derived from `PendingActionStore`; phase should record role and reference, not copy approval lifecycle.

## Transition Commit Boundaries

| Transition | Checkpoint timing | Safe retry after crash? | Reconcile source | Side-effect rule | Revision |
| --- | --- | --- | --- | --- | --- |
| model continuation before | write intent phase before request when possible | model request may be retried only if no response/assistant turn committed | session snapshot/messages | never duplicate if response may exist | increment before intent |
| model continuation after | write committed transition after response/session durable | no blind retry | `SessionStore` | fail closed on ambiguity | increment after commit |
| tool staging before | checkpoint records staging intent | yes, staging can dedupe by digest | `PendingActionStore` | no execution | increment |
| tool staging after | store pending action ref | inspect pending action | `PendingActionStore` | no approval copied | increment |
| approval consumption before | checkpoint does not consume approval | no direct action | `PendingActionStore` | approval owner decides | no approval state copy |
| tool execution after | record completed action ref only after pending lifecycle reconciles | uncertain crash window fails closed | pending action lifecycle + external evidence | avoid duplicate side effect | increment |
| initial validation before | persist selected command digest before staging/execution | safe to inspect; execution explicit | checkpoint + pending store | same command enforced | increment |
| initial validation after | increment validation count after verified result | no blind rerun | validation outcome/provenance verification | max two | increment |
| attestation verification before | keep provenance nonce outside checkpoint | no semantic parsing | provenance verifier | raw attestation not copied | no raw nonce |
| attestation verification after | store bounded verification summary in outcome | safe to inspect | typed result | repair only on trusted failed tests | increment |
| set `repair_attempted` | write before repair continuation/model call | duplicate repair prevented | checkpoint | max one | increment |
| repair continuation after | commit session/transition after response | no blind retry | session + checkpoint | fail closed on ambiguity | increment |
| repair tool after | record completed repair action ref after reconcile | no blind re-execute | pending store | side effect uncertain fails closed | increment |
| re-validation staging | set `revalidation_attempted=true` before staging/execution | prevents third validation | checkpoint + pending store | same digest required | increment |
| re-validation after | increment count and store cycle result | no blind rerun | validation result | max two | increment |
| final outcome | write `final_outcome_summary` before completion marker | can retry marker only if revision current | checkpoint | no execution | increment |
| completion marker | atomic terminal write | repeated resume returns completed | checkpoint | no further action | final increment |

## Resume Reconciliation

Default inspect flow executes no model call, no tool, no validation, and no approval.

```text
load checkpoint
-> validate schema/version/integrity
-> validate workflow/session identity
-> acquire or reuse workflow lock
-> inspect SessionStore
-> inspect PendingActionStore
-> inspect final outcome/completion
-> compare checkpoint revision
-> reject impossible combinations
-> return typed ResumeDecision
-> execute nothing by default
```

Minimum `ResumeDecision` contract:

| Decision | Evidence | Read-only? | Explicit resume? | Needs approval? | Repeated invocation | Forbidden actions |
| --- | --- | --- | --- | --- | --- | --- |
| `completed` | terminal marker and no active workflow pending action | yes | no-op | no | same completed summary | model/tool/validation |
| `inspect_only` | valid checkpoint, no safe automatic next step requested | yes | no | maybe | same summary | execution |
| `awaiting_plan_approval` | session pending plan token | yes | after approval only | yes | same approval summary | auto approval |
| `awaiting_tool_approval` | phase/ref and active pending action | yes | after approval only | yes | same pending summary | auto approval |
| `awaiting_validation_approval` | validation phase/ref active | yes | after approval only | yes | same pending summary | auto pytest |
| `awaiting_repair_tool_approval` | repair ref active | yes | after approval only | yes | same pending summary | auto approval |
| `awaiting_revalidation_approval` | revalidation ref active | yes | after approval only | yes | same pending summary | auto approval |
| `safe_to_continue_model` | no ambiguous committed response and revision current | inspect yes | yes | no | rechecks revision | duplicate continuation |
| `safe_to_stage_validation` | command digest selected, no active validation action | inspect yes | yes | later approval | rechecks pending store | direct execution |
| `safe_to_start_repair` | trusted failed tests and `repair_attempted=false` | inspect yes | yes | maybe later | rechecks revision | second repair |
| `safe_to_stage_revalidation` | repair completed, same command digest, count below two | inspect yes | yes | later approval | rechecks revision | new command |
| `blocked_corrupt_state` | malformed/oversized/bad digest/unknown version | yes | no | human | stable block | guessing |
| `blocked_inconsistent_state` | authoritative stores disagree | yes | no | human | stable block | guessing |
| `stale_revision` | CAS or loaded revision stale | yes | reload first | no | may change after reload | execution |
| `not_resumable` | no checkpoint or unsupported state | yes | no | human | same until state changes | execution |

## Mission 07 Recovery Invariants

| Invariant | Durable field | Supporting authoritative store | Recovery rule |
| --- | --- | --- | --- |
| command selection exactly once | `selected_validation_command_digest` | validation plan/proposal digest | once set, cannot change |
| same immutable logical command | `selected_validation_command_digest` | pending action proposal digest | re-validation digest must match |
| validation executions maximum two | `validation_execution_count` | validation transitions | count above two fails closed |
| repair attempts maximum one | `repair_attempted` | checkpoint revision | set before repair continuation |
| re-validation attempts maximum one | `revalidation_attempted` | checkpoint revision | set before re-validation staging |
| trusted attestation sole repair trigger | bounded `final_outcome_summary` / cycle result | pytest provenance verifier | no stdout/stderr semantic parsing |
| no exit-code-only proof | outcome summary provenance category | pytest verifier | infrastructure failures block |
| approval token single consumption | none in checkpoint | `PendingActionStore` | checkpoint references only |
| attestation single consumption | no raw attestation in checkpoint | provenance verifier | store safe verification summary only |
| completed workflow terminality | `completion_marker` | checkpoint | repeated resume returns completed |

## Corruption and Inconsistency Behavior

Fail closed for:

- missing checkpoint when resume requires one;
- invalid JSON;
- oversized checkpoint;
- unknown or future schema;
- bad integrity digest;
- session mismatch;
- workflow kind mismatch;
- stale revision;
- missing pending action referenced by pending phase;
- pending action and phase mismatch;
- completed checkpoint with active workflow pending action;
- multiple active actions for one workflow role;
- final outcome and phase contradiction;
- validation count above two;
- repair/re-validation flags contradict count or phase;
- selected command missing after validation begins;
- orphan provenance artifact that cannot be reconciled safely;
- duplicate resume racing with another writer.

Recovery must not guess the most likely state and continue execution.

## Doctor Boundary

Doctor is suitable for read-only consistency checks:

- checkpoint schema readability;
- unknown/future version;
- orphan checkpoint;
- checkpoint/session identity mismatch;
- completed plus active pending contradiction;
- stale or invalid references;
- static count/invariant conflicts.

Resume reconciliation is responsible for:

- whether a specific action has already executed;
- whether model continuation is safe;
- whether repair can safely start;
- whether re-validation can safely stage;
- side-effect uncertainty.

Doctor must not execute resume, call a model, approve action, run pytest, modify checkpoint, or auto-repair state.

## CLI Boundary

Future CLI should reuse the existing coding/workflow CLI owner.

Conceptual commands:

- inspect;
- resume;
- cancel, only if design evidence supports safe cancellation.

Rules:

- inspect is always read-only;
- resume is always explicit;
- pending approval is never auto-approved;
- completed resume returns completed;
- corrupt or inconsistent state cannot continue;
- output must not expose raw approval token, nonce, artifact path, or raw attestation;
- no second coding CLI subsystem.

## Mission 08 Phasing

| Phase | Goal | Owner | Likely files | OpenCode reference decision | Documentation impact | Non-goals | Hard stops | Tests | Human review gate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 08A | architecture audit | docs/coding architecture | audit report only | LIGHT TARGETED | no implementation docs changed | implementation | unclear owner | read-only verification | completed by human review |
| 08A-D | targeted comparison and authoritative design | solo-workdocs + ADR | this document, mission index, ADR | LIGHT TARGETED | authoritative design created | production code | unpinned OpenCode | doc diff/check | required before 08B |
| 08B | checkpoint contract | `src/pp_agent/coding` | coding recovery contract, tests | no further unless blocked | update design if contract changes | storage engine | second approval/tool state | contract/unit tests | required |
| 08C | atomic storage, revision, reconciliation | coding storage helper | coding recovery storage tests | no further unless blocked | storage docs update | database | DB/new dependency | atomic/corruption/CAS tests | required |
| 08D preflight | approval/tool-boundary resume audit | coding architecture | no committed source changes | no further unless blocked | blocker notes | resume execution | unsafe continuation boundary | source audit | completed with STOP |
| 08D-P | durable model continuation intent contract | coding checkpoint contract | checkpoint contract/store tests | LIGHT TARGETED pinned comparison | schema v2 docs | resume execution | unsafe version evolution | v1/v2 contract tests | required |
| 08D-S | SessionStore/tool-result correlation evidence | session/runtime integration | storage/runtime correlation tests | NONE | session evidence docs updated | coding phase in SessionStore | session rewrite | correlation tests | implemented |
| 08D-R | explicit approval/tool-boundary resume execution | coding recovery orchestration | future resume tests | no further unless blocked | resume docs | auto approval | duplicate tool/model side effects | crash-window tests | required |
| 08E | Mission 07 recovery integration | coding validation/repair | validation recovery tests | no further unless blocked | Mission 07 bridge update | new validation attempts | Mission 07 semantic change | invariant tests | required |
| 08F | CLI inspect/resume/cancel | existing coding CLI owner | CLI commands/serializers | no further unless blocked | CLI docs | auto approval | second CLI system | CLI read-only/resume tests | required |
| 08G | doctor, release gate, docs, closeout | workflow doctor + docs | doctor/report docs/closeout | no further unless blocked | closeout and release docs | auto repair | doctor mutating state | doctor/readiness tests | final human review |

08B and 08C may be merged only if the checkpoint contract is small and storage support is inseparable. Approval/tool resume and Mission 07 recovery should remain separate because they touch different invariants.

## Implementation Non-goals

- no production code in 08A-D;
- no test code in 08A-D;
- no checkpoint files in 08A-D;
- no session migration;
- no resume implementation;
- no CLI implementation;
- no database;
- no new dependency;
- no generic workflow engine;
- no second approval store;
- no second tool state;
- no second runtime loop;
- no OpenCode framework port;
- no Mission 07 semantic change;
- no Mission 09.

## Mission 08D-R Explicit One-Boundary Resume

08D-R adds a coding-owned inspection and explicit resume layer:

- owner: `src/pp_agent/coding/workflow_recovery.py`;
- read-only API: `inspect_coding_workflow(...) -> CodingWorkflowInspection`;
- explicit resume API: `resume_coding_workflow(..., expected_revision, runtime, ...) -> CodingWorkflowResumeResult`;
- runtime seam: existing `AgentRuntime.continue_(continuation_id=..., stop_after_model_boundary=True)`;
- checkpoint schema: version 3 only for ordinary terminal completion workflows after 08D-T;
- v1/v2 checkpoints remain loadable but are not migrated or resumed by 08D-T recovery.

Action lifecycle recovery map:

| PendingActionStore state | Inspect result | Resume behavior | Checkpoint behavior |
| --- | --- | --- | --- |
| `staged_not_granted` / active | awaiting approval | no model, no tool execution | no mutation |
| `grant_attached` | awaiting approval | no model, no tool execution | no mutation |
| `execution_in_progress` / `execution_succeeded` | execution uncertain | fail closed | no mutation |
| `execution_failed` | execution failed | no retry | terminal/blocked decision only |
| `rejected` / `denied` | rejected | no restage | terminal/blocked decision only |
| `expired` | expired | no restage | terminal/blocked decision only |
| `grant_invalidated` / orphan/quarantine | invalidated or inconsistent | no restage | terminal/blocked decision only |
| `grant_consumed` without exact SessionStore result evidence | durable result unavailable | no model retry | no mutation |
| `grant_consumed` with exact SessionStore result evidence | ready for continuation intent | one pre-call CAS, then at most one model continuation | write intent and clear pending safe reference |
| missing/corrupt/mismatch | corrupt/inconsistent | fail closed | no blind overwrite |

Resume sequence:

1. Load checkpoint and authoritative SessionStore/PendingActionStore evidence.
2. Require schema v3, exact action identity, consumed action state, and exact durable SessionStore external-result evidence.
3. CAS the checkpoint from the caller-provided expected revision to an `intent_committed` continuation intent.
4. Release checkpoint/workspace lock before provider I/O.
5. Dispatch at most one existing runtime continuation with the durable continuation id.
6. Confirm SessionStore model-continuation completion evidence after runtime persistence.
7. CAS checkpoint to `completed` with schema v3 `ordinary_completion` terminal outcome when exact completion evidence exists and no active pending action remains.

The runtime boundary deliberately stops after one model response. If that response contains tool calls, the existing runtime planner approval owner stages one pending action and the resume call stops. Recovery does not execute those tools and does not create a second action state.

08D-R originally stopped at the session-committed continuation boundary. 08D-T supersedes that stopping point for ordinary completion: `session_committed` remains evidence, while schema v3 `terminal_outcome` plus `completion_marker` is the workflow terminality record. Mission 07 validation/repair/re-validation recovery remains deferred to 08E.

Failure and crash windows:

- pre-call CAS failure returns stale or blocked; no model call happens;
- crash after intent CAS and before provider call leaves `intent_committed`; repeated resume does not retry the model;
- provider/runtime failure after intent returns blocked uncertain; repeated resume does not retry;
- missing completion evidence after model return returns blocked uncertain;
- post-call CAS failure does not retry the model; later inspect can see SessionStore completion evidence;
- duplicate concurrent resume with the same revision allows only one intent CAS winner.
- active pending action after model continuation blocks ordinary completion and does not write completed.

Scope protection:

- no auto approval;
- no auto rejection;
- no tool execution by recovery;
- no duplicate staging by recovery;
- no trace/stdout/audit recovery authority;
- no CLI implementation;
- no doctor integration;
- no Mission 07 recovery execution;
- no new dependency;
- no SessionStore or PendingActionStore schema migration.

## Mission 08D-T Generic Terminal Outcome and Ordinary Completion

08D-T adds the formal workflow terminality record that 08D-R intentionally did not invent.

Implemented:

- CHECKPOINT SCHEMA V1: FROZEN.
- CHECKPOINT SCHEMA V2: FROZEN.
- CHECKPOINT SCHEMA V3: GENERIC TERMINAL OUTCOME CAPABLE.
- `CodingWorkflowTerminalOutcome` supports `ordinary_completion` and `validation_completion`.
- Ordinary terminal outcome requires `session_completion_evidence_ref` and forbids validation summary fields.
- Validation terminal outcome requires `validation_outcome_summary` and forbids session completion evidence fields.
- Completed schema v3 checkpoint requires `completion_marker` and `terminal_outcome`.
- Completed schema v3 checkpoint must not have active pending action evidence.
- Completed schema v3 checkpoint must not have active continuation intent; only `session_committed` continuation evidence may remain as evidence.
- Completed checkpoint is immutable in the checkpoint store.
- Store create/load supports v1, v2, and v3.
- Store replace still rejects silent schema-version changes.
- Integrity digest covers the terminal outcome.
- Recovery writes ordinary completion only from exact SessionStore model-continuation completion evidence, typed ordinary terminal outcome, matching source action/result identity, no active pending action, and checkpoint CAS.
- Repeated completed inspect/resume returns `ordinary_completed` and performs no model call, tool execution, approval mutation, or checkpoint mutation.

Not implemented in 08D-T:

- no automatic v1/v2 to v3 migration;
- no Mission 07 validation/repair/re-validation recovery;
- no CLI inspect/resume/cancel;
- no doctor integration;
- no generic workflow engine;
- no new dependency;
- no model retry;
- no tool execution or approval mutation by recovery.

Authority statement:

- `session_committed` is continuation completion evidence, not workflow terminality.
- `pp_agent.coding` checkpoint remains workflow completion authority.
- Validation terminal contract is defined only; Mission 07 recovery remains not implemented.

## Documentation Impact Decision

| Document | Changed? | Why | Authoritative effect |
| --- | --- | --- | --- |
| `solo-workdocs/02-missions.md` | yes | formally defines Mission 08 and 08A-D status | authoritative mission index |
| `solo-workdocs/mission-docs/18-mission-08-durable-workflow-recovery-design.md` | yes | creates Mission 08 design | authoritative Mission 08 design |
| `docs/adr/0004-coding-workflow-recovery-authority.md` | yes | records long-term owner boundary | authoritative architecture decision |
| `docs/architecture/README.md` | yes | indexes storage/recovery and ADR route | supporting navigation |
| Mission 07 design/closeout | yes | clarifies Mission 08 persistence bridge without changing Mission 07 semantics | supporting bridge |
| source and tests | yes | 08B adds the pure versioned checkpoint contract; 08C adds atomic checkpoint storage, CAS, and read-only reconciliation tests; 08D-S adds generic SessionStore correlation evidence tests; 08D-R adds explicit coding-owned one-boundary resume tests; 08D-T adds schema v3 generic terminal outcome and ordinary completion tests | no CLI, doctor, or Mission 07 recovery execution integration |

DOCUMENTATION IMPACT DECISION: REQUIRED AND COMPLETED FOR SCHEMA V3 AND ORDINARY TERMINALITY

DOCUMENTATION DECISION: AUTHORITATIVE MISSION 08 DESIGN RETAINED; 08B, 08C, 08D-P, 08D-S, 08D-R, AND 08D-T IMPLEMENTATION RECORDS ADDED

## Mission 08E Mission 07 Recovery Integration Closeout

08E implements durable recovery for the existing Mission 07 bounded validation and repair lifecycle without changing Mission 07 runtime semantics.

Implemented:

- Initial validation staging writes schema v3 coding workflow checkpoints with selected validation command digest, validation pending action reference, and `validation_execution_count=0`.
- Validation approval/result recovery uses PendingActionStore lifecycle plus exact SessionStore external-result evidence; consumed actions without durable evidence fail closed.
- Validation interpretation uses `SessionEvidenceReference` and `SessionStore.lookup_external_result_details()` instead of raw `ChatMessage.metadata`.
- Initial validation pass writes schema v3 validation terminal completion with `validation_execution_count=1`.
- Initial validation blocked writes schema v3 validation terminal completion with blocked status and does not trigger repair.
- Trusted pytest `tests_failed` evidence with `repair_attempted=false` makes explicit resume safe to start one repair.
- Repair explicit resume CAS-writes `repair_attempted=true` and `REPAIR_STARTED` before the model continuation.
- Repair continuation runs at most once and uses existing runtime continuation/session evidence; repeated resume does not retry the model.
- Missing repair continuation completion evidence returns `REPAIR_CONTINUATION_UNCERTAIN`.
- Repair tool approval stops at `AWAITING_REPAIR_TOOL_APPROVAL`; recovery does not approve or execute tools.
- Repair completion without a pending tool stops at `REPAIR_COMPLETED_READY_FOR_REVALIDATION`.
- Same-command revalidation explicit resume stages exactly one revalidation action from the original selected logical command digest.
- Revalidation approval/result recovery uses exact session/action evidence and returns `REVALIDATION_RESULT_READY` only when durable evidence exists.
- Final revalidation interpretation persists schema v3 validation terminal completion with `validation_execution_count=2`.
- Revalidation pass completes as passed.
- Revalidation trusted `tests_failed` completes as failed and does not trigger a second repair.
- Revalidation missing/invalid provenance, infrastructure failure, or evidence persistence failure completes as blocked.
- Completed checkpoints remain immutable and repeated completed resume has no external effect.

Authority and invariant results:

- Checkpoint remains the authority for workflow phase, counters, flags, and terminal outcome.
- PendingActionStore remains the authority for staged action and approval lifecycle.
- SessionStore remains the authority for durable external-result and continuation evidence.
- TraceStore remains diagnostic only.
- No schema v4 was introduced.
- Schema v1/v2 semantics were not changed and no automatic migration was added.
- No generic workflow engine, second runtime, second approval store, second tool state, or new dependency was added.
- Mission 07 invariants remain: max one repair continuation, max one revalidation, max two validation executions, same validation command, no stdout/stderr semantic repair trigger, and repair only from trusted pytest `tests_failed` evidence.

Technical debt:

- TD-1: schema v3 does not allow `model_continuation_intent` and active `pending_action_ref` to coexist. After a repair continuation has durably produced a repair-tool pending action and checkpoint reconciliation succeeds, the checkpoint uses `pending_action_ref(role=REPAIR_TOOL)` as the current recovery authority and does not retain the continuation intent. This is accepted for 08E and does not require a schema change in Mission 08.
- TD-2: `approve_staged_validation_cycle` remains as a compatibility alias. It no longer approves or executes anything; it delegates to the pure persisted-result interpretation path. Future cleanup may rename or remove this alias.

08E closeout status:

- Mission 08E functionality is implemented and ready for human review.
- No remaining Mission 08E blockers are known.
- Remaining Mission 08 work is outside 08E: CLI inspect/resume/cancel and doctor/release-gate integration.

## Final Design Decision

Mission 08E is implemented and ready for human review.

PRODUCTION CODE CHANGED: YES, CONTRACT, CHECKPOINT STORE, SESSION EVIDENCE, RUNTIME CORRELATION PLUMBING, CODING-OWNED EXPLICIT RESUME ORCHESTRATION, SCHEMA V3 TERMINAL OUTCOME, AND ORDINARY COMPLETION

TEST CODE CHANGED: YES, FOCUSED CONTRACT, STORAGE, CAS, ATOMICITY, RECONCILIATION, SESSION CORRELATION, EXPLICIT RESUME, SCHEMA V3 TERMINAL OUTCOME, AND ORDINARY COMPLETION TESTS

PERSISTENCE IMPLEMENTED: YES, CHECKPOINT-ONLY ATOMIC PERSISTENCE

REVISION/CAS IMPLEMENTED: YES, CHECKPOINT-ONLY

RECONCILIATION IMPLEMENTED: YES, READ-ONLY ONLY

RESUME IMPLEMENTED: YES, EXPLICIT ONE-BOUNDARY WITH SCHEMA V3 ORDINARY COMPLETION ONLY

CHECKPOINT SCHEMA V1: FROZEN

CHECKPOINT SCHEMA V2: FROZEN

CHECKPOINT SCHEMA V3: GENERIC TERMINAL OUTCOME CAPABLE

SESSION_COMMITTED: CONTINUATION EVIDENCE, NOT WORKFLOW TERMINALITY

WORKFLOW COMPLETION AUTHORITY: PP_AGENT.CODING CHECKPOINT

ORDINARY COMPLETION: IMPLEMENTED

VALIDATION TERMINAL CONTRACT: DEFINED ONLY

MISSION 07 RECOVERY: NOT IMPLEMENTED

COMPLETED CHECKPOINT: IMMUTABLE

REPEATED COMPLETED RESUME: NO EXTERNAL EFFECT

MISSION 07 RUNTIME SEMANTICS: UNCHANGED

CLI: NOT IMPLEMENTED

DOCTOR INTEGRATION: NOT IMPLEMENTED
