# ContextPipeline

## Position

ContextPipeline is pp-Echo's context engine. Retrieval tools find information; ContextPipeline decides what the model sees, how it is ordered, why it fits budget, and what was dropped.

The current runtime keeps the new rendered-message path behind `use_context_pipeline_messages=false` by default. Even with the flag off, runtime builds the canonical `ContextPack` for trace and audit. Tests can enable the flag to verify the new provider -> item -> pack -> final messages path without a broad AgentRuntime rewrite.

## Separation

OpenClaw-style memory separation is the boundary:

- `memory_search` and `memory_get` are retrieval tools.
- `global/MEMORY.md` and workspace `MEMORY.md` are bootstrap markdown memory sources.
- `memory/**/*.md` is durable file memory, but it is not fully injected into prompts. It is read through retrieval tools or explicit compact previews.
- Core Memory is governance, preview, approval, audit, and trace metadata. SQLite active core memories are not prompt facts by default.

Hermes-style progressive disclosure is the capability boundary:

- Skills enter context as level 0 metadata cards by default.
- Full `SKILL.md` bodies are materialized only after explicit selection.
- Skill artifacts under `references/`, `templates/`, or `scripts/` are read only after explicit request and path validation.
- MCP tools/resources/prompts enter context as compact cards after permission overlay and metadata scan.
- Denied, blocked, or high-risk capability cards are dropped and reported; they are not exposed to the model.

## Sections

Canonical sections are:

- `system`
- `markdown_memory`
- `core_governance`
- `project_context`
- `episodic_recall`
- `file_memory_preview`
- `attachments`
- `capabilities`
- `mcp`
- `skills`
- `conversation`
- `runtime_notes`

Legacy names are accepted as aliases: `system_instructions`, `core_memory_snapshot`, `episodic_memory_items`, `attachment_previews`, `selected_capabilities`, and `recent_turns`.

## Markdown Memory

`pp_agent.context.markdown_memory` reads only:

- `global/MEMORY.md`
- workspace `MEMORY.md`

Each read produces a `ContextItem` with `section=markdown_memory`, `type=markdown_memory`, the exact injected Markdown content, and a `SourceRef` containing path, line range, heading, `content_hash`, `truncated`, `char_limit`, and marker ids when present.

The files are read on every context build, so approved memory written to Markdown is visible on the next turn. If content exceeds the character limit, the provider truncates from the tail by a deterministic rule, marks `metadata.truncated=true`, and emits a warning/drop accounting rather than silently hiding the decision.

## Budget And Drops

Default section budgets protect system/context essentials while keeping large surfaces bounded:

- `system`: 4000
- `markdown_memory`: 4000
- `core_governance`: 800, debug only
- `project_context`: 3000
- `episodic_recall`: 3000
- `file_memory_preview`: 1200
- `attachments`: 3000
- `capabilities`: 2500
- `mcp`: 1500
- `skills`: 1500
- `conversation`: bounded by caller/runtime policy
- `runtime_notes`: 1000

Every dropped item must have a reason. Current reasons include section and total budget pressure, duplicate context, disabled policy, capability/MCP/skill denial, attachment preview size, markdown truncation, core prompt injection disabled, and legacy adapter classification failures.

## Trace

Runtime emits `context_payload_version=3` in `context_built`. The nested `context` payload includes:

- total and per-section budget usage
- included and dropped item summaries
- drop reasons
- source refs
- markdown memory paths, hashes, and truncation status
- core governance prompt-injection status
- capability, MCP, and skill counts
- warnings

This lets TraceInspect answer four questions for a turn:

- What did the model see?
- Why did it see those items?
- What was dropped?
- Why was each item dropped?

## Runtime Path

The orchestrated path is:

1. Providers produce `ContextItem`.
2. `ContextPipeline.collect_items()` normalizes sections and aliases.
3. `ContextPipeline.build_pack()` applies policy, dedupe, and budget.
4. `ContextPack` stores included items, dropped items, source refs, warnings, and budget report.
5. `ContextPipeline.render_messages()` produces final `ChatMessage` objects.
6. AgentRuntime uses rendered messages only when `use_context_pipeline_messages=true`.
7. Runtime emits the v3 `context_built` trace either way.

`build_context_pack_from_messages()` remains as a legacy observer/fallback for already-rendered runtime messages.
