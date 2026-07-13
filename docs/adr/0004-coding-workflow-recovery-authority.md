# ADR 0004: Coding Workflow Recovery Authority and State Ownership

## Status

Accepted for Mission 08 design review.

## Context

Mission 07 added a bounded validation and repair loop for controlled coding workflows, but its first version is run-local. Process restart loses repair and re-validation invariants, selected validation command continuity, validation execution count, and terminal workflow completion.

Existing durable owners already exist:

- `SessionStore` owns transcript and runtime/session snapshots.
- `PendingActionStore` owns staged actions and approval lifecycle.
- `TraceStore` owns diagnostic events.

Mission 08 needs durable recovery without creating a second session store, second approval state, second tool execution state, generic workflow engine, or full event-sourcing rewrite.

## Decision

Create a coding-owned durable recovery checkpoint contract for controlled coding workflows.

Primary ownership:

- `src/pp_agent/coding` owns coding workflow recovery checkpoint semantics.
- `SessionStore` / `SessionHost` continue to own session identity, transcript, runtime/session snapshot, and generic continuation state.
- `PendingActionStore` continues to own staged action payloads, approval tokens, approval lifecycle, and action execution lifecycle.
- `TraceStore` remains diagnostic, audit, and explainability infrastructure only.

The coding checkpoint owns only workflow facts:

- workflow kind;
- workflow phase;
- revision or generation;
- selected logical validation command identity;
- validation execution count;
- repair attempted;
- re-validation attempted;
- last committed workflow transition;
- safe pending action reference;
- final outcome summary;
- completion marker.

The checkpoint must not copy approval lifecycle state, raw approval tokens, raw provenance nonce, raw attestation, complete transcript, runtime objects, full stdout/stderr, full patch, environment variables, secrets, or pickle data.

Recovery must load and validate checkpoint state, inspect authoritative session and pending-action owners, reject impossible combinations, return a typed resume decision, and execute nothing unless the user explicitly requests resume.

## Consequences

- Mission 08 can persist Mission 07 invariants without changing Mission 07 runtime semantics.
- Repeated resume of a completed workflow returns the terminal outcome and performs no action.
- Ambiguous side-effect windows fail closed instead of guessing.
- Doctor can add read-only consistency checks later, but doctor must not resume, approve, run tools, run tests, or repair state.
- CLI inspect/resume/cancel remains presentation and orchestration over authoritative owners; it does not become a state owner.

## Non-goals

- No generic workflow engine.
- No second approval store.
- No second tool execution state.
- No second runtime/model loop.
- No full session format rewrite.
- No database requirement.
- No distributed lock.
- No OpenCode session, permission, or agent-loop framework port.
- No Mission 07 semantic change.
