# Mission 04 Closeout: Bounded Repository Summary

Status: Completed / ready for human merge review

Branch: `mission/mission-04-planning`

## Authoritative Goal

Mission 04 implemented a bounded, deterministic, traceable, JSON-friendly repository summary for the existing coding preparation/context path.

The first version serves runtime/context consumers only. It does not add a standalone CLI/Web repository browser.

## Completed Work

### 04B: RepositorySummary Contract

Implemented the minimal summary contract:

- `RepositorySummary`
- `RepositorySummarySection`
- `RepositorySummarySource`
- `RepositorySummaryWarning`
- `repository_summary_to_dict()`

The contract provides stable ordering, JSON-friendly serialization, source-reference validation, explicit truncation metadata, skipped-source metadata, and stable warning payloads.

### 04B Follow-up: Source Reference Integrity

Added validation so sections and warnings cannot serialize dangling `source_key` references.

This keeps summary payloads auditable and prevents legal `to_dict()` output with broken provenance links.

### 04C: Bounded Collector

Implemented `build_repository_summary(...)` as an explicit, bounded collector over:

- existing `ProjectContext`;
- existing `RepositoryAnalysis`;
- fixed root instruction document candidates;
- fixed project-map paths;
- explicit or module-map-derived `MODULE.md` candidates.

The collector enforces:

- repository-root containment;
- symlink escape rejection;
- sensitive path rejection before opening files;
- approved text document types only;
- UTF-8 / UTF-8 BOM decoding;
- per-file, total, document-count, section, and warning budgets;
- deterministic source, section, and warning payloads.

Default v0.x budgets:

- per-file read: 16 KiB;
- total document read: 64 KiB;
- max approved docs: 12;
- per-section output: 4 KiB;
- max warnings: 20.

### 04D: Coding Preparation Integration

Integrated repository summary into the existing `CodingWorkflow` preparation contract as:

```python
repository_summary: RepositorySummary | None
```

`prepare_coding_workflow()` now builds the summary once after `ProjectContext` and `RepositoryAnalysis` are available. The summary can be disabled with:

```python
include_repository_summary=False
```

Serialization reuses `repository_summary_to_dict()` through the existing workflow details path. No new timeline/event framework was added.

## Safety Boundaries

Mission 04 did not change:

- runtime execution behavior;
- `AgentRuntime`;
- `ToolRegistry`;
- tool approval semantics;
- policy or guardrail behavior;
- Mission 03 shell/test execution loop;
- model/provider request behavior.

Mission 04 does not perform:

- generic recursive scan;
- source-code indexing;
- model-driven summary;
- shell execution;
- Git command execution from production code;
- cache/index persistence;
- background scanning;
- filesystem watching;
- embeddings or vector database work;
- OpenCode framework adoption;
- CLI/Web repository browser expansion.

## Determinism Guarantees

The summary avoids:

- timestamps;
- UUIDs;
- object IDs;
- filesystem enumeration order dependence;
- absolute machine paths in summary payloads;
- raw OS exception text in warnings.

Candidate paths are fixed, explicit, or narrowly derived from `RepositoryAnalysis.module_map`.

## Trace-safe Behavior

Summary payloads preserve:

- section keys;
- source keys;
- warning codes;
- skipped-source reasons;
- truncation flags;
- repository-relative POSIX paths.

Payloads do not include:

- full unbounded source documents;
- sensitive file contents;
- absolute local temp paths;
- Python object reprs;
- raw exception messages.

## Tests And Release Gate

Focused coverage includes:

- `RepositorySummary` contract serialization and source integrity;
- bounded collector path, text, sensitive-file, symlink, budget, and determinism behavior;
- coding preparation integration;
- JSON-friendly workflow serialization;
- collector call count;
- controlled warning behavior;
- programmer error propagation.

Release gate executed during Mission 04D:

```text
python -m pytest tests\coding\test_orchestrator.py -q
python -m pytest tests\coding\test_repository_summary.py tests\coding\test_repository_summary_collector.py -q
python -m pytest tests\context\test_project_context.py tests\coding\test_repository_analyzer.py -q
python -m pytest tests\coding -q
python -m pytest tests\cli\test_coding_cli.py tests\web\test_coding_service.py -q
python -m pytest tests -q
python -m pp_agent.cli.main workflow doctor --json
git diff --check
```

## Commits

- `a08b5c1 docs: define Mission 04 repository summary scope`
- `6f25d47 feat: add repository summary contract`
- `0429899 fix: validate repository summary source references`
- `6742db5 feat: add bounded repository summary collection`
- `ed04a24 feat: integrate repository summary into coding preparation`
- `docs: close Mission 04 repository summary work`

## Known Limitations

- Summary consumption remains structured; Mission 04 does not add a large prompt renderer.
- Relevant module documents are selected from explicit paths or shallow `RepositoryAnalysis.module_map`, not a repository-wide search.
- Budgets are fixed v0.x defaults, not a user configuration system.
- Closeout does not claim CLI/Web repository browsing.

## Recommended Next Boundary

The next mission should start from human-reviewed `master`.

Suggested boundary:

- evaluate how structured repository summaries should be consumed by runtime/context rendering;
- keep invocation explicit and bounded;
- avoid changing execution, approval, or tool semantics unless a new mission explicitly targets those areas.
