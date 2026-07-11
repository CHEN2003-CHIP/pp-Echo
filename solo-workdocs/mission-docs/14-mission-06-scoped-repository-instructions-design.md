# Mission 06 Scoped Repository Instructions

Status: ratified / 06A completed / ready for 06B planning

## Mission 06 Official Definition

Mission 06 - Scoped Repository Instructions

Goal:

Automatically resolve repository-local `AGENTS.md` and `CLAUDE.md` instructions relevant to concrete task/read paths, activate them lazily and safely, and deliver them only through the existing `ContextItem -> ContextPipeline -> ContextPack -> final_messages` path.

Mission 06 does not replace Mission 05. Mission 05 owns `RepositorySummary` and root project instruction integration. Mission 06 owns scoped repository instruction discovery and activation for concrete nested task/read paths.

This ratification step is docs-only. It does not implement a resolver, modify runtime code, modify file tools, modify tests, or start 06B.

## 06A Benchmark Record

06A - OpenCode Source-Level Benchmark and Scoped Instruction Semantics

Status: COMPLETED

Pinned OpenCode benchmark:

```text
repo: https://github.com/anomalyco/opencode.git
branch: dev
commit: 9976269ab1accfc9f9dc98a4a688c516934de422
benchmark date: 2026-07-11
```

Source evidence:

```text
packages/opencode/src/session/instruction.ts
packages/opencode/src/session/prompt.ts
packages/opencode/src/tool/read.ts
packages/core/src/fs-util.ts
```

This is a pinned benchmark of OpenCode behavior, not a dependency and not a code-copy target.

## OpenCode Benchmark Conclusions

System instruction loading:

- project candidate precedence is `AGENTS.md -> CLAUDE.md -> deprecated CONTEXT.md`;
- system-level lookup may accumulate ancestor matches for the selected filename;
- system rules enter model context before model processing;
- OpenCode supports global, custom, and remote instruction sources.

Nearby lazy resolution:

```text
successful read target
-> walk target directory ancestors
-> find nearby instruction
-> skip system-loaded/already-loaded/currently-claimed paths
-> attach instruction to read tool result
-> next model continuation sees instruction
```

Nearby instruction does not affect the model call that already decided to perform the read. It affects the continuation after the tool result.

Duplicate suppression distinguishes:

- system-loaded paths;
- historically loaded paths;
- per-message claims.

pp-Echo must adapt the principle, not copy OpenCode's exact state model.

## Human Decisions Recorded

### Decision 1: A First, B Now

Mission lineage:

- Mission 05: `RepositorySummary` / root project instruction integration.
- Mission 06: scoped repository instruction discovery and activation.

Mission 06 must not replace Mission 05.

Mission 05 remains the owner of preparation-time root project instructions.

Mission 06 owns repository-local scoped instruction discovery and activation.

### Decision 2: Same-directory Precedence

First-version semantics:

```text
AGENTS.md = canonical
CLAUDE.md = compatibility fallback
```

For one directory:

```text
if AGENTS.md exists and is eligible:
    use AGENTS.md
else if CLAUDE.md exists and is eligible:
    use CLAUDE.md
else:
    no instruction for this directory
```

Do not load both by default.

Do not support `CONTEXT.md` in the first version.

Rationale:

- lowers duplicate and conflict risk;
- remains compatible with the OpenCode principle;
- keeps `AGENTS.md` as pp-Echo's canonical collaboration file;
- supports `CLAUDE.md` compatibility.

### Decision 3: Bounded Cumulative Ancestor Semantics

For a target such as:

```text
repo/packages/frontend/src/app.py
```

scoped resolution conceptually walks:

```text
repo/packages/frontend/src/
repo/packages/frontend/
repo/packages/
```

up toward the repository root.

Rules:

1. O(directory depth) only.
2. No recursive scan.
3. No `rglob("**/AGENTS.md")`.
4. No generic repository rules index.
5. Each directory contributes at most one instruction file.
6. Same-directory fallback is `AGENTS.md > CLAUDE.md`.
7. Multiple applicable ancestor scopes may accumulate.
8. The repository root itself is not automatically duplicated by scoped resolution.

### Decision 4: Ordering Semantics

Logical inheritance order:

```text
root project instruction
-> shallow scoped instruction
-> deeper scoped instruction
-> nearest scoped instruction
```

This is general to specific.

Requirements:

- deterministic;
- traceable;
- no semantic conflict resolver;
- no LLM-based override selection.

Render order, budget selection priority, and discovery order do not have to be identical internally. They must be explicit and traceable.

This document does not fix numeric `ContextItem.priority` values. 06B and 06C must inspect existing priority conventions before choosing values.

Under budget pressure, more locally relevant scoped instructions should not be systematically dropped before less relevant intermediate ancestors.

Do not create a new budget engine.

### Decision 5: First-version Trigger

Official first-version trigger design:

```text
TaskScope seed
+
actual successful read_file lazy activation
```

Preparation-time seed:

- concrete target paths already known from `TaskScope` may seed likely scoped instruction resolution before the first model call;
- only concrete, repository-contained target paths are eligible;
- broad workspace root, arbitrary shell cwd, unconstrained wildcard, and vague model inference are not automatic triggers.

Runtime lazy trigger:

- a successful actual `read_file` path may activate missing scoped instructions relevant to that path;
- newly discovered instructions become available on the next context build / next model continuation;
- activation is not retroactive to the model call that triggered the read.

### Decision 6: Activation Lifetime

Discovery / activation cache lifetime:

```text
controlled coding loop run
```

The run may remember scoped instructions that were safely discovered. There is no session-global persistence.

Duplicate claim lifetime:

```text
current turn / model continuation
```

Purpose:

- prevent repeated resolution/read work;
- prevent duplicate activation attempts within the same continuation.

Provider-facing active set:

At each context build, include the bounded union of scoped instructions relevant to:

```text
TaskScope-seeded concrete paths
+
actual successfully-read paths observed in the current controlled run
```

No session-global rule accumulation.

No hidden permanent memory.

### Decision 7: Instruction Identity

Do not use one identity key for every concern.

Source identity:

```text
normalized repository-relative path
```

Used for provenance, trace, and stable source identity.

Content freshness:

```text
content digest
```

Used for changed-content detection and stale reuse prevention.

Scope:

```text
instruction file parent directory
```

Used for applicability and hierarchy.

Activation dedupe:

```text
normalized repository-relative path + content digest
```

Used for repeated activation suppression.

Do not use filename only as scoped instruction identity.

Do not use fuzzy semantic comparison.

### Decision 8: Scoped Reader

Mission 06 must not call the whole Mission 04 collector as a runtime resolver.

Mission 04 collector:

```text
preparation-time bounded repository summary collection
```

Mission 06 resolver:

```text
runtime target-path-scoped instruction resolution
```

Official direction:

```text
narrow scoped instruction reader using existing pp-Echo safety semantics
```

Required safety behavior:

- repository-root containment;
- symlink escape rejection before read;
- sensitive/protected rejection;
- bounded per-file read;
- supported text only;
- binary rejection;
- controlled decoding;
- repository-relative path;
- trace-safe `SourceRef` provenance.

Implementation rule:

- if Mission 04 safety logic is already exposed as safely reusable primitives, reuse it;
- if equivalent logic is embedded in collector-private code, extract the smallest shared pure safety helper.

Do not copy/paste a second safety implementation.

Do not call the full collector.

Do not call the public `read_file` tool internally and inherit tool UX/approval side effects.

Do not create a generic filesystem framework.

### Decision 9: Domain Contract

Mission 06 may introduce one minimal domain record:

```text
ScopedInstruction
```

Purpose:

```text
represent a safely resolved scoped instruction before model-facing ContextItem adaptation
```

Candidate conceptual fields:

- source identity;
- repository-relative path;
- scope root;
- source kind;
- bounded content;
- content digest;
- truncated/skipped metadata where applicable.

Exact fields belong to 06B contract design.

Do not introduce `RulesManager`, `InstructionRegistry`, `InstructionFramework`, `InstructionProviderSystem`, or `RuleEngine` unless a concrete blocker proves necessary.

### Decision 10: Context Integration

Official integration path:

```text
ScopedInstruction
-> minimal adapter
-> ContextItem(section="project_context")
-> existing ContextPipeline
-> ContextPack
-> final_messages
```

Requirements:

- reuse `ContextItem`;
- reuse `SourceRef`;
- reuse existing section budgets;
- reuse existing dedupe;
- reuse existing drop reasons;
- reuse existing rendering;
- reuse existing `context_built` trace.

Forbidden:

```text
ScopedInstruction -> raw prompt string
ScopedInstruction -> direct provider message injection
ScopedInstruction -> RepositorySummary
```

Runtime lazy state must not be forced back into preparation-time `RepositorySummary`.

## Root CLAUDE.md Compatibility Check Requirement

Mission 05 remains canonical owner of root project instructions.

Concept:

```text
repository-root instruction -> Mission 05 / RepositorySummary path
nested scoped instruction -> Mission 06 scoped resolver
```

Mission 06 must not create a second root instruction path.

Required 06B pre-implementation check:

Verify whether the existing Mission 04/05 root instruction discovery already supports:

```text
root AGENTS.md
root CLAUDE.md fallback
```

If root `CLAUDE.md` fallback is already supported, make no change.

If it is not supported, allow only the smallest extension to the existing root-instruction discovery seam.

Do not solve this by letting the scoped resolver independently own repository-root instructions.

## Mission 05 Ownership Upgrade Boundary

Current Mission 05 root duplicate ownership logic remains valid for:

```text
root ProjectContext manifest excerpt
vs
root RepositorySummary project_instruction
```

Mission 06 must not immediately replace it.

First-version rule:

```text
root ownership and scoped ownership remain separate
```

Mission 06 may introduce stronger scoped identity based on repository-relative path and digest.

Do not refactor Mission 05 ownership logic unless a concrete integration test proves it necessary.

If Mission 06 integration exposes a real root/scoped ownership conflict, stop for explicit follow-up design.

Do not introduce a generic semantic dedupe engine.

## Trace Strategy

First version should prefer existing trace infrastructure:

- `ContextItem.metadata`;
- `SourceRef`;
- `context_built`;
- existing included/dropped `ContextPack` details.

Candidate trace-safe metadata:

```text
scope_root
trigger_kind = task_scope | read_file
trigger_path
content_digest or bounded digest identifier
```

Do not expose:

- absolute machine path;
- raw OS exception;
- unrestricted full source metadata.

Do not create a new global event framework.

A new dedicated event type is not assumed necessary.

If 06C proves existing `context_built` cannot explain activation lifecycle, stop and request human review before adding a new trace schema.

## First-version Explicit Scope

Mission 06 first version includes:

- repository-local `AGENTS.md`;
- repository-local `CLAUDE.md` fallback;
- O(directory depth) ancestor lookup;
- bounded cumulative scoped inheritance;
- `TaskScope` concrete-path seeding;
- actual `read_file` lazy activation;
- run-scoped discovery/activation cache;
- turn/continuation-scoped duplicate claims;
- narrow safe scoped reader;
- minimal `ScopedInstruction` contract;
- `ScopedInstruction -> ContextItem` adapter;
- `SourceRef` provenance;
- existing `ContextPipeline` integration;
- existing `context_built` trace reuse;
- deterministic ordering;
- path/digest duplicate suppression;
- Windows path normalization tests.

## Explicit Deferred Scope

Deferred:

- actual edit-path activation;
- global `~/.config` rules;
- global `~/.claude` rules;
- custom instruction globs;
- organization-wide rules;
- config DSL;
- `CONTEXT.md` compatibility;
- semantic conflict resolution;
- generic rules engine;
- session-global activation.

Rejected for first version:

- remote URL instructions;
- network-fetched instructions;
- recursive repository scan;
- LLM-based rule selection;
- embedding-based rule matching;
- fuzzy semantic dedupe;
- raw prompt injection;
- second `ContextPipeline`;
- second provider-message path.

## Threat and Edge-case Requirements

Future tests must cover:

- target outside repository root;
- symlinked target escaping root;
- instruction symlink escaping root;
- nested `AGENTS.md`;
- nested `CLAUDE.md`;
- `AGENTS.md` + `CLAUDE.md` in the same directory;
- empty instruction;
- oversized instruction;
- unreadable instruction;
- binary `AGENTS.md`;
- target itself is an instruction file;
- root instruction already Mission-05-owned;
- same scoped instruction already activated;
- instruction content changes during run;
- target moves to another module;
- multi-target `TaskScope`;
- Windows path case differences;
- repository-relative path normalization.

## Mission Split

### 06A: OpenCode Source-Level Benchmark and Semantics Decision

Status: COMPLETED

No code.

### 06B: ScopedInstruction Contract and Bounded Resolver

Single goal:

```text
target path -> safe bounded ancestor resolution -> ScopedInstruction records
```

Includes:

- minimal domain contract;
- same-dir precedence;
- ancestor-chain lookup;
- bounded safe scoped reader;
- path/digest identity;
- `SourceRef`-compatible provenance;
- focused tests.

Does not include:

- runtime activation state;
- `TaskScope` integration;
- `read_file` trigger integration;
- `ContextPipeline` runtime integration.

Recommended commit boundary:

```text
feat: add bounded scoped instruction resolver
```

### 06C: Scoped Activation State and Triggers

Single goal:

```text
TaskScope concrete paths + successful read_file paths -> run-scoped activation state
```

Includes:

- `TaskScope` seed;
- `read_file` lazy trigger;
- activation dedupe;
- turn/continuation claims;
- deterministic active set;
- focused lifecycle tests.

Does not include:

- edit trigger;
- global rules;
- remote rules;
- custom globs.

Recommended commit boundary:

```text
feat: add scoped instruction activation lifecycle
```

### 06D: ContextPipeline Integration and Release Gate

Single goal:

```text
active ScopedInstruction records -> ContextItem -> existing ContextPipeline -> final_messages -> existing trace
```

Includes:

- adapter;
- ordering/priority integration;
- budget/drop verification;
- final_messages verification;
- trace/provenance verification;
- Mission 05 ownership regression;
- closeout;
- full release gate.

Recommended integration commit:

```text
feat: integrate scoped instructions with context pipeline
```

Recommended closeout commit:

```text
docs: close Mission 06 scoped repository instructions
```

## OpenCode Adoption and Divergence Record

Direct evidence:

- system instruction loading;
- nearby ancestor resolution;
- `AGENTS.md` / `CLAUDE.md` candidate precedence;
- lazy post-read activation;
- system-loaded / loaded / claims duplicate suppression;
- per-message claims lifecycle.

Adapt principle:

- nearby scoped relevance;
- ancestor-chain lookup;
- lazy activation after actual file read;
- duplicate activation suppression;
- `AGENTS.md` canonical / `CLAUDE.md` fallback.

Reuse pp-Echo:

- Mission 04 safety semantics;
- Mission 05 root instruction ownership;
- `TaskScope`;
- `ContextItem`;
- `SourceRef`;
- `ContextPipeline`;
- `ContextPack`;
- `context_built`;
- approval/policy/guardrail boundaries.

Intentional divergence:

- no raw `<system-reminder>` prompt injection;
- no absolute path prompt provenance;
- no OpenCode exact `MessageID` claims data model;
- no remote URL instruction loading;
- no global Claude/OpenCode rule loading;
- no `CONTEXT.md` compatibility.

## Do-not-reinvent Record

| Requirement | Decision |
| --- | --- |
| safe path normalization | REUSE PP-ECHO |
| root containment | REUSE PP-ECHO |
| symlink rejection | REUSE PP-ECHO |
| bounded reads | REUSE / EXTRACT MINIMAL SHARED HELPER |
| ContextItem | REUSE PP-ECHO |
| SourceRef | REUSE PP-ECHO |
| ContextPipeline | REUSE PP-ECHO |
| trace | REUSE PP-ECHO |
| ancestor scoped resolver | NEW MINIMAL PP-ECHO SEAM |
| activation state | NEW MINIMAL PP-ECHO SEAM |
| duplicate claims | ADAPT OPENCODE PRINCIPLE |
| global/custom/remote rules | DEFER / REJECT FIRST VERSION |

## Validation Plan for This Ratification

Docs-only validation:

- `git diff --check`;
- `git status --short`;
- `git diff --stat`;
- `git diff -- solo-workdocs/02-missions.md solo-workdocs/mission-docs`.

Human-check list:

- Mission 06 official name is consistent;
- 06A is marked completed;
- Design B is ratified;
- `TaskScope` seed + `read_file` lazy trigger are recorded;
- edit trigger is deferred;
- `AGENTS.md > CLAUDE.md` fallback is recorded;
- bounded cumulative ancestry is recorded;
- root ownership remains Mission 05;
- root `CLAUDE.md` fallback pre-implementation audit is recorded;
- run-scoped cache and turn claims are separated;
- no session-global activation;
- no `RepositorySummary` misuse;
- no raw prompt path;
- no Mission 06 implementation.

No full pytest suite is required for docs-only ratification.
