# Mission 04: Bounded Repository Scan and Deterministic Project Summary

Status: Ratified scope / implementation not started

Date: 2026-07-10

Branch: `mission/mission-04-planning`

## Scope Ratification

Mission 04 is formally defined from Roadmap Week 4, "Repo Scan 与项目摘要".

Authoritative source:

- `solo-workdocs/01-roadmap.md`, Week 4: Repo Scan 与项目摘要.
- `solo-workdocs/02-missions.md`, Mission 04 entry.

Approved human decisions:

- Mission 04 name: **Bounded Repository Scan and Deterministic Project Summary**.
- First version serves only the existing runtime/context path.
- First version does not add standalone CLI or Web display.
- First version does not allow generic, unbounded recursive repository scanning.
- Mission 03 tool execution, approval, policy, guardrail, shell safety, and file safety are stable boundaries and must not be rewritten.
- OpenCode is a design benchmark only; pp-Echo does not adopt the full OpenCode agent, permission, session, task, config, MCP, ACP, or LSP framework.

## Goal

Build a bounded, deterministic, traceable, JSON-friendly repository summary that gives the existing coding runtime/context layer project-level background.

The summary should help a coding workflow understand:

- project languages and frameworks;
- known entrypoints;
- likely test commands;
- shallow module information;
- project instruction sources;
- do-not-touch or protected areas;
- key risks;
- source citations;
- skipped, missing, or truncated source information.

## Primary User-Visible Outcome

When a coding workflow prepares task context, it can receive a stable project summary derived from approved sources. The summary is intended for runtime/context consumption and future timeline display, not for a new CLI/Web repo browser in the first version.

## Approved Sources

Mission 04 first version may aggregate only:

- existing `ProjectContext` from `src/pp_agent/context/project.py`;
- existing `RepositoryAnalysis` from `src/pp_agent/coding/repository.py`;
- repository-root `AGENTS.md` or an equivalent project instruction file;
- known project-map document such as `.pp-echo/project-map.json`;
- relevant `MODULE` documents for the current target module;
- existing explicit entrypoint and test command analysis results.

Mission 04 must not default to reading all source files.

Mission 04 must not perform a generic recursive repository scan. Any file read must come from an explicit allowlist, an existing context object, or a narrowly derived module-document candidate.

## Determinism Requirements

The repository summary must be deterministic:

- stable sorting for paths, sections, warnings, and sources;
- same inputs produce the same output;
- no model calls;
- no dependency on current time;
- no dependency on operating-system directory traversal order;
- stable output when optional documents are missing;
- explicit representation for truncation, skipped sources, missing sources, and read failures.

## Safety And Budget Boundaries

Minimum first-version safety requirements:

- All paths must resolve inside the repository root.
- Symlinks that escape the repository root must not be followed.
- Exclude `.git`, virtual environments, caches, build artifacts, and dependency directories by default.
- Exclude `.env`, credential, secret, key, token, certificate, and similar sensitive files by default.
- Read only approved text documents.
- Binary files are recorded as skipped and their content is not read.
- Permission errors, encoding errors, and disappearing files are recorded as controlled skipped sources.
- No arbitrary file is copied in full into the summary.
- Every section should have a bounded output budget.

Conservative default budgets for 04B/04C design and test calibration:

- Per-file read budget: 16 KiB.
- Total document read budget: 64 KiB.
- Maximum approved document count: 12.
- Per-section rendered text budget: 4 KiB.
- Maximum warnings per summary: 20.

These numbers are v0.x defaults for focused tests and should be calibrated during implementation. Mission 04 should not introduce a complex configuration system for them.

## Proposed Minimal Data Contract

The first implementation should stay close to existing `ProjectContext` and `RepositoryAnalysis` rather than creating a large domain model.

Draft concepts:

```text
RepositorySummary
- workspace_name
- project_type
- languages
- frameworks
- entrypoints
- test_commands
- modules
- instruction_sources
- protected_areas
- risks
- sections
- warnings
- skipped_sources
- truncated_sources
- source_citations
```

```text
RepositorySummarySource
- source_id
- path
- source_type
- bytes_read
- truncated
- skipped
- skip_reason
```

```text
RepositorySummarySection
- section_id
- title
- content
- source_ids
- truncated
```

```text
RepositorySummaryWarning
- code
- message
- source_id
```

Contract constraints:

- JSON-friendly dataclasses or dicts only.
- No general document AST.
- No plugin framework.
- No provider abstraction.
- No session persistence.
- No full file contents in the structure.
- Every summary section should trace back to one or more source IDs.
- The contract must be easy to test for stable sorting and JSON serialization.

## Mission Boundaries

Mission 04 may:

- add a pure data contract;
- add a bounded summary builder;
- aggregate existing context and repository analysis;
- read a small number of explicitly approved project documents;
- connect the summary to existing coding preparation/context;
- add focused tests and necessary integration tests.

Mission 04 may not:

- rewrite `run_controlled_coding_loop()`;
- rewrite `AgentRuntime`;
- modify Mission 03 tool execution semantics;
- introduce an agent mode framework;
- introduce a permission DSL;
- introduce a child-session system;
- introduce a generic code index;
- introduce embeddings or a vector database;
- introduce model-driven repository summaries;
- introduce background scans;
- introduce a filesystem watcher;
- introduce a full CLI/Web repo browser;
- introduce MCP/LSP/ACP expansion;
- introduce complex config merging;
- automatically modify repository content.

## OpenCode Benchmark Record

Mission 04A benchmarked official `anomalyco/opencode` materials:

- official docs for agents, permissions, tools, config, commands, LSP, and MCP servers;
- source-level mechanisms around agent configuration, permission checks, tool runtime, session processing, task/subagent flow, config loading, MCP, and LSP;
- permission tests around ordered matching, allow/ask/deny, and approval behavior.

The benchmark was based on then-visible `dev` branch content and was not pinned to a reliable commit SHA. Treat it as a non-pinned architecture benchmark.

Adopted OpenCode principles:

- `COPY PRINCIPLE - already satisfied; preserve unchanged`: permissions must be enforced at execution boundaries.
- `COPY PRINCIPLE - already satisfied; preserve unchanged`: prompt text is not a security boundary.
- `ADAPT LIGHTLY`: output should be deterministic, traceable, and audit-friendly.
- `ADAPT LIGHTLY`: extension surfaces must not bypass existing capability and approval boundaries.

Rejected for Mission 04 MVP:

- full OpenCode agent framework;
- full permission DSL;
- child-session system;
- task/subagent execution framework;
- config merge system;
- MCP/ACP/LSP expansion.

## Proposed Implementation Split

### Mission 04B: RepositorySummary Contract

Goal:

- Define the smallest JSON-friendly summary contract.
- Define source, warning, skipped, and truncation representation.
- Define stable sorting.
- Keep behavior pure-data and pure-function level.
- Do not integrate runtime yet.
- Do not perform generic file scanning.

Allowed modules:

- `src/pp_agent/coding/`
- `src/pp_agent/context/`
- focused tests for the new contract.

Non-goals:

- No runtime loop changes.
- No tool execution changes.
- No source collection beyond explicit fixtures.

### Mission 04C: Bounded Source Collection

Goal:

- Aggregate existing `ProjectContext` and `RepositoryAnalysis`.
- Read approved AGENTS/project-map/MODULE documents with explicit budgets.
- Enforce path, text-file, sensitive-file, symlink, and budget boundaries.
- Preserve skipped/truncated metadata.
- Do not change tool execution or approval behavior.

Allowed modules:

- `src/pp_agent/coding/`
- `src/pp_agent/context/`
- focused context/coding tests.

Non-goals:

- No generic recursive scan.
- No model-driven summary.
- No complex configuration system.

### Mission 04D: Context Integration and Release Gate

Goal:

- Connect repository summary to existing coding preparation/context.
- Ensure output is trace-safe and JSON-friendly.
- Add integration tests.
- Run focused tests, full suite, doctor/report as applicable, and release gate.
- Do not add UI or a new execution loop.

Allowed modules:

- `src/pp_agent/coding/`
- `src/pp_agent/context/`
- trace/context adapters only if needed for existing context plumbing.

Non-goals:

- No CLI/Web display.
- No Mission 03 execution loop changes.
- No MCP/LSP/ACP expansion.

## Testing Strategy

04B focused tests:

- JSON serialization is stable.
- Sorting is stable.
- Missing optional sections produce stable output.
- Section source IDs are preserved.
- No full file content fields exist in the contract.

04C focused tests:

- AGENTS/project-map/MODULE approved reads work.
- Absolute paths and parent traversal are rejected.
- Symlink escape is skipped.
- Sensitive filenames are skipped.
- Binary files are skipped.
- Per-file and total budgets truncate predictably.
- Permission/encoding/missing-file errors become skipped sources.
- No generic recursive scan is used.

04D integration tests:

- Existing coding workflow includes repository summary context.
- Summary is trace-safe and JSON-friendly.
- Existing `ProjectContext` and `RepositoryAnalysis` tests still pass.
- Mission 03 tool execution focused tests still pass.

Release gate:

- focused context/coding tests;
- relevant runtime/context adapter tests;
- `python -m pytest tests -q`;
- `python -m pp_agent.cli.main workflow doctor --json` if runtime readiness is touched;
- `git diff --check`.

## Risks

- Scope creep into a general code index.
- Accidental recursive scanning of large or sensitive trees.
- Summary sections copying too much source text.
- Treating project instructions as trusted execution authority.
- Rewriting Mission 03 execution semantics while trying to improve context.
- Over-designing config, session, or extension systems before the summary contract is stable.

## Need Human Review

- Confirm whether the conservative default budgets are acceptable for 04B/04C calibration.
- Confirm the exact set of equivalent project instruction filenames beyond root `AGENTS.md`, if any.
- Confirm whether relevant MODULE documents should be selected by target path, module map, or explicit caller hint in 04C.

## Not Done

- No runtime/source implementation.
- No tests changed.
- No Mission 04B implementation.
- No generic recursive scan.
- No CLI/Web repo browser.
- No execution-loop changes.
- No commit in this document by itself.
