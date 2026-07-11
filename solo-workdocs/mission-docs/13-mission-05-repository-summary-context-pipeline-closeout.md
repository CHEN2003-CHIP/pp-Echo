# Mission 05 Repository Summary ContextPipeline Closeout

Status: completed / ready for human merge review

## Goal

Mission 05 connected selected bounded `RepositorySummary` content to pp-Echo's existing runtime/context pipeline:

`RepositorySummary -> repository_summary_to_context_items() -> ContextItem(section="project_context") -> ContextPipeline -> ContextPack -> final_messages -> context_built trace`

The mission stayed inside the existing `ContextPipeline` and did not create a second context framework.

## 05A Seam Audit

05A confirmed that `RepositorySummary` was already built during coding preparation but was not provider-facing context.

Existing chain before Mission 05:

`prepare_coding_workflow() -> _build_repository_summary() -> CodingWorkflow.repository_summary -> workflow details / metadata`

Missing chain:

`RepositorySummary -> ContextPipeline -> ContextPack -> final_messages`

Decision:

- reuse `ContextPipeline`;
- reuse `project_context`;
- reuse `ContextItem`;
- reuse `SourceRef`;
- defer scoped repository instructions to future Mission 06.

## 05B Adapter

05B added:

- `src/pp_agent/coding/repository_summary_context.py`
- `repository_summary_to_context_items(summary: RepositorySummary) -> tuple[ContextItem, ...]`

The adapter is pure and consumes only an already-built `RepositorySummary`.

It outputs model-facing items only for:

- `project_instruction`;
- `module_doc`.

It excludes:

- languages;
- frameworks;
- repository structure;
- entrypoints;
- test commands;
- project metadata;
- warnings.

Warnings remain trace-only by default.

## 05C Integration

05C added an optional `repository_summary` parameter to:

`build_runtime_context_pack(..., repository_summary: RepositorySummary | None = None)`

When provided, the runtime bridge calls `repository_summary_to_context_items()` once and passes the resulting items through the existing `project_context_providers` seam.

When `repository_summary is None`, behavior remains unchanged.

No existing positional callers were broken.

## Selected Model-facing Subset

The model-facing subset is intentionally narrow:

- approved project instructions already present in `RepositorySummary`;
- relevant module guidance already present in `RepositorySummary`.

Mission 05 does not perform new discovery and does not add nearby instruction lookup.

## Excluded Duplicate Facts

Mission 05 does not re-inject general repository facts already owned by existing context systems:

- `ProjectContext`;
- `RepositoryAnalysis`;
- `ValidationPlan`;
- existing runtime bridge context items.

The adapter avoids duplicate ownership at the source instead of relying on downstream dedupe to hide broad semantic duplication.

## SourceRef Mapping

05B maps `RepositorySummarySource` to existing `SourceRef`:

```text
RepositorySummarySource.source_key -> SourceRef.source_id
RepositorySummarySource.source_kind -> SourceRef.source_type
RepositorySummarySource.path -> SourceRef.path
```

Additional safe metadata includes:

- `repository_summary_source_kind`;
- `bytes_consumed`;
- `truncated`;
- `symbol`, when present.

Paths remain repository-relative.

## Double Budget Ownership

Mission 04 owns source extraction and read safety:

- bounded source reads;
- rejected/skipped sources;
- truncation before summary construction.

Mission 05 owns model-facing context integration:

- selected semantic subset;
- conversion to `ContextItem`;
- existing `ContextPipeline` budget/drop/render behavior.

No Mission 05-specific budget engine was added.

## Final Messages Verification

Focused tests verify that selected repository summary content reaches:

- `ContextPack.project_context`;
- `ContextPack.final_messages`.

They also verify that excluded general metadata does not appear as summary-derived model-facing content.

## Existing Trace Reuse

Mission 05 reuses existing `context_built` trace details and existing `context_pack_to_trace_details()` behavior.

Summary-derived items are visible through existing:

- included item summaries;
- dropped item summaries;
- source refs;
- project context section item ids;
- model input preview.

No new trace event or trace schema was added.

## No New ContextPipeline

Mission 05 did not add:

- a new `ContextPipeline`;
- a new renderer;
- a new budget engine;
- a new trace schema;
- a new provider-message path;
- a new canonical context section.

The generic context package does not import `RepositorySummary`.

## No Mission 06 Implementation

Mission 05 did not implement:

- nearby `AGENTS.md` discovery;
- nearby `CLAUDE.md` discovery;
- ancestor-chain lookup;
- active path resolution;
- lazy scoped instruction activation;
- instruction claims;
- custom globs;
- global rules;
- remote instructions.

These remain future Mission 06 concerns.

## Tests

Release-gate commands run:

- `python -m pytest tests\coding\test_repository_summary_context.py -q`
- `python -m pytest tests\context\test_context_runtime_adapter.py -q`
- `python -m pytest tests\coding\test_repository_summary.py tests\coding\test_repository_summary_collector.py tests\coding\test_repository_summary_context.py tests\coding\test_orchestrator.py -q`
- `python -m pytest tests\context -q`
- `python -m pytest tests\runtime -q`
- `python -m pytest tests -q`
- `python -m pp_agent.cli.main workflow doctor --json`
- `git diff --check`

Final full suite:

`1440 passed, 5 skipped, 2 warnings`

Doctor:

`status: ok`

## Release Gate

Mission 05 release gate passed:

- 05B adapter remains pure;
- selected content enters existing `ContextPipeline`;
- selected content enters `final_messages`;
- existing budget/drop behavior applies;
- existing trace is observable;
- `SourceRef` provenance is retained;
- general metadata is not duplicated as summary-derived prompt content;
- no new source reread;
- no Mission 06 implementation;
- full suite passed;
- doctor status ok.

## Commits

- `8bd49c4 docs: define Mission 05 context pipeline integration`
- `1a2290b feat: add repository summary context adapter`
- `a431e37 feat: integrate repository summary with context pipeline`
- closeout commit pending at document creation time

## Known Limitations

- `build_runtime_context_pack()` accepts an optional already-built `RepositorySummary`, but the runtime loop does not yet automatically source one from a live `CodingWorkflow`.
- Scoped instruction discovery is intentionally absent.
- `project_instruction` and `module_doc` selection remains owned by the 05B adapter.
- Existing `ProjectContext` and `RepositoryAnalysis` remain separate context owners for general repository facts.

## Future Mission 06 Boundary

Future Mission 06 should focus on scoped repository instructions:

- active task/path resolution;
- ancestor-chain lookup;
- `AGENTS.md` canonical behavior;
- `CLAUDE.md` compatibility fallback;
- bounded cumulative scope handling;
- duplicate suppression;
- prompt-injection risk framing.

Mission 06 should avoid generic full-repository recursive scans as the default approach.
