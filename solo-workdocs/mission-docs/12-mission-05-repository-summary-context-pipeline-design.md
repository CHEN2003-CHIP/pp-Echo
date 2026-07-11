# Mission 05 Repository Summary ContextPipeline Integration

Status: ratified / 05A completed / ready for 05B planning

## Mission 05 Official Definition

Mission 05 integrates the bounded `RepositorySummary` produced by Mission 04 into pp-Echo's existing runtime/context path.

The approved architecture is:

`RepositorySummary -> selected sections -> ContextItem(section="project_context") -> ContextPipeline -> ContextPack -> final_messages`

Mission 05 is an integration mission, not a new context framework. It should make selected repository summary content model-facing only through the existing context pipeline.

## 05A Conclusions

05A is complete.

Codebase reconnaissance found that `RepositorySummary` is currently not provider-facing context. The current chain is:

`prepare_coding_workflow() -> _build_repository_summary() -> CodingWorkflow.repository_summary -> workflow details / metadata`

The missing chain is:

`RepositorySummary -> ContextPipeline -> ContextPack -> final_messages`

The existing `ContextPipeline` is mature enough for Mission 05 and should be reused. The selected approach is Option B:

`selected RepositorySummary sections -> multiple ContextItem(section="project_context")`

The adapter should select only approved project instructions and relevant module guidance.

## Human Decisions Recorded

`HUMAN DECISION: A FIRST, B SECOND`

Decision A comes first: integrate repository summary content into the existing `ContextPipeline`.

Decision B comes second: scoped repository instructions belong to a future Mission 06.

The first version serves only runtime/context consumption. It does not add a standalone CLI/Web display path.

Generic recursive scanning is not allowed for the first version.

## OpenCode Decision Record

`OPENCODE COMPARISON COMPLETED`

Mission 05 adopts these principles:

- project instructions should be model-facing when relevant;
- instruction provenance should be explicit;
- duplicate instruction injection should be avoided;
- prompt content is not a permission boundary.

Mission 05 intentionally does not copy:

- OpenCode's session/prompt framework;
- raw instruction string injection path;
- per-message instruction claims;
- dynamic nearby `AGENTS.md` discovery;
- dynamic nearby `CLAUDE.md` discovery;
- custom instruction globs;
- global rules system;
- remote URL instructions.

Dynamic nearby instruction discovery is deferred to Mission 06, not rejected permanently.

The future Mission 06 research target should include OpenCode source-level scoped instruction behavior, especially:

`packages/opencode/src/session/instruction.ts`

## Architecture Boundary

Mission 05 must reuse:

- `ContextPipeline`;
- `ContextPack`;
- `final_messages`;
- `context_built`;
- `ContextBudgeter`;
- `SourceRef`;
- canonical `project_context` section.

Mission 05 should use a minimal `RepositorySummarySource -> SourceRef` adapter. The adapter may translate identity and provenance from repository-summary terms into the existing context/source terms, but it must not become a second source identity framework.

The Mission 04 collector remains responsible for bounded source extraction and read safety.

The `ContextPipeline` remains responsible for model-facing budget, drop behavior, rendering, and final provider messages.

This double budget is intentional:

- Mission 04 controls what repository files are read and summarized.
- Mission 05 controls what selected summary content reaches the model context.

## 05B Boundary

05B should implement the smallest adapter that converts selected `RepositorySummary` content into existing `ContextItem(section="project_context")` entries.

Allowed 05B behavior:

- consume an already-built `RepositorySummary`;
- select approved project instructions;
- select relevant module guidance;
- preserve source provenance through `SourceRef`;
- produce multiple context items instead of one raw JSON blob;
- leave warnings trace-only by default;
- avoid duplicate instruction injection where the same source/content would otherwise repeat.

05B must not:

- reread repository files;
- recursively scan for instruction files;
- discover nearby `AGENTS.md` or `CLAUDE.md`;
- inject raw `RepositorySummary.to_dict()` JSON into prompts;
- create a new canonical section;
- create a new renderer;
- create a new budget engine;
- alter provider message semantics.

## 05C Boundary

05C should integrate the 05B adapter into the existing context build path and verify release-gate behavior.

Expected 05C checks:

- `RepositorySummary` selected content appears in `project_context` context items;
- final messages are still built by the existing `ContextPipeline`;
- context trace remains bounded and source-aware;
- warnings remain trace-only unless explicitly promoted later;
- Mission 04 repository summary tests still pass;
- runtime/context regression tests still pass.

05C should not introduce a second pipeline or a new provider-message path.

## Future Mission 06 Boundary

Future Mission 06 candidate:

`Mission 06 - Scoped Repository Instructions`

Mission 06 is a research and design candidate only. It is not implemented or ratified by Mission 05.

Mission 06 should study:

- current task / target file / active path;
- ancestor-chain nearby instruction resolution;
- `AGENTS.md` canonical behavior;
- `CLAUDE.md` compatibility fallback;
- scoped relevance;
- lazy activation;
- duplicate suppression;
- integration with the existing `ContextPipeline`.

Mission 06 should avoid generic full-repository instruction scans such as:

- `rglob("**/AGENTS.md")`;
- `glob("**/CLAUDE.md")`;
- generic recursive rules scanning.

Candidate lookup should be O(directory depth), not full repo search.

Same-directory fallback preference:

`AGENTS.md` canonical, `CLAUDE.md` compatibility fallback.

Human preference for ancestor behavior:

bounded cumulative instructions, with nearest scope receiving higher priority.

This preference still needs formal 06A research before implementation.

## Mission 06 Open Questions

- How should active path be determined for a coding task with multiple touched files?
- Should ancestor instructions be cumulative, nearest-only, or priority-merged?
- How should duplicate or conflicting scoped instructions be suppressed?
- How should `AGENTS.md` and `CLAUDE.md` interact when both exist in the same directory?
- What is the trace representation for scoped instruction activation?
- Should scoped instructions ever be user-visible before model injection?
- What budget should be reserved for scoped instructions versus repository summary context?
- How should prompt-injection risk be described when instructions are prompt content, not a permission boundary?

## Explicit Non-goals

Mission 05 does not add:

- `CodingContextBundle`;
- `RepositoryContextBundle`;
- a new canonical section such as `repository_summary`, `repository_context`, or `coding_context`;
- a new `ContextPipeline`;
- a new budget engine;
- a new renderer;
- a new trace schema;
- a new provider message path;
- raw `RepositorySummary.to_dict()` prompt injection;
- dynamic nearby `AGENTS.md` / `CLAUDE.md` discovery;
- automatic ancestor instruction lookup;
- recursive scans;
- repository file rereads in the adapter;
- runtime execution semantic changes;
- provider semantic changes;
- tool semantic changes;
- approval semantic changes;
- policy semantic changes.

Mission 05 does not implement Mission 06.

## Success Criteria

- Mission 05 is formally defined in `solo-workdocs/02-missions.md`.
- 05A is marked completed.
- `HUMAN DECISION: A FIRST, B SECOND` is recorded.
- `OPENCODE COMPARISON COMPLETED` is recorded.
- Mission 05 keeps repository summary integration inside the existing `ContextPipeline`.
- Mission 06 scoped-instruction direction is preserved and clearly deferred.
- No production code or tests are changed in this scope ratification step.
- No duplicate context framework is introduced.

## Task Split

### 05A: Scope Ratification and Architecture Reconnaissance

Status: completed.

Deliverables:

- current code path analysis;
- OpenCode comparison;
- Mission 05 / Mission 06 boundary;
- formal design record.

### 05B: RepositorySummary to ContextItem Adapter

Goal:

Implement the minimal adapter that turns selected `RepositorySummary` content into existing `ContextItem(section="project_context")` entries.

Suggested focused tests:

- adapter emits no items for empty summary;
- approved project instructions produce `project_context` items;
- relevant module guidance produces `project_context` items;
- source provenance is represented through `SourceRef`;
- warnings remain trace-only by default;
- no raw `RepositorySummary.to_dict()` JSON appears in rendered context.

### 05C: Runtime Context Integration and Release Gate

Goal:

Wire the adapter into the existing context build path and verify release-gate behavior.

Suggested checks:

- context pipeline tests;
- repository summary tests;
- runtime trace/context tests;
- workflow doctor/report if runtime readiness is affected;
- full suite before merge review.

## Verification and Release Gate Plan

For this ratification step:

- `git diff --check`;
- `git status --short`;
- manual review of Mission 05 scope boundaries;
- verify only `solo-workdocs/02-missions.md` and this design document changed.

For 05B:

- focused adapter tests under the existing coding/context test area;
- no provider or execution-loop changes.

For 05C:

- focused context pipeline and runtime context tests;
- Mission 04 repository summary regression tests;
- workflow doctor/report if readiness output changes;
- full test suite before merge review.
