# ContextPipeline

## Why pp-Echo Needs This Layer

pp-Echo has separate ownership for model profiles, runtime orchestration, memory, attachments, capabilities, tools, MCP, skills, traces, and evals. Before ContextPipeline, model-facing context could be assembled by several nearby systems with limited shared accounting. ContextPipeline creates one auditable place to explain what entered the model call, where it came from, what budget it used, and what was dropped.

This layer is intentionally additive. It does not replace AgentRuntime, Memory, AttachmentService, ToolRegistry, or CapabilityPolicy. Runtime now builds a trace-safe `ContextPack` and `ContextBudgetReport` after existing context hooks have produced the final provider messages, without changing the messages sent to the model.

## ContextPack Structure

`ContextPack` is the serializable output of the pipeline. It groups included `ContextItem` objects into model-facing sections:

- `system_instructions`
- `model_profile_summary`
- `runtime_profile_summary`
- `core_memory_snapshot`
- `episodic_memory_items`
- `attachment_previews`
- `selected_capabilities`
- `project_context`
- `recent_turns`
- `runtime_notes`
- `source_refs`
- `budget_report`

The pack stores items rather than one flattened prompt string. This keeps source references, priorities, and budget accounting inspectable until the final model adapter chooses how to render messages.

## ContextItem

`ContextItem` is the smallest independently budgeted unit. It contains:

- `id`
- `type`
- `title`
- `content`
- `source_ref`
- `priority`
- `estimated_tokens`
- `estimated_chars`
- `metadata`

The current budget strategy uses `estimated_chars` and falls back to `len(content)`. Later tokenizer-aware accounting can fill `estimated_tokens` without changing the pack shape.

## SourceRef Structure

`SourceRef` records trace-safe provenance:

- `source_type`: `core_memory`, `episodic_memory`, `attachment`, `project_map`, `module_doc`, `adr`, `capability`, or `conversation`
- `source_id`
- `path`
- `line_start`
- `line_end`
- `page`
- `heading`
- `confidence`
- `metadata`

Trace summaries omit `metadata` by default so source references can remain useful without becoming a secret or prompt dump channel.

## BudgetReport Structure

`ContextBudgetReport` explains the budgeting result:

- `total_budget`
- `used`
- `per_section`
- `included_items`
- `dropped_items`
- `drop_reasons`

Each section has its own budget. When a droppable section exceeds budget, the pipeline drops whole `ContextItem` objects by priority and records every dropped item with `section_budget_exceeded`. Core memory is different: it is non-droppable in this first implementation, so an oversized core memory item raises `ContextBudgetExceeded` and records `core_memory_budget_exceeded_not_truncated`. That prevents silent truncation of durable memory.

## Relationship To Existing Systems

`ModelProfile` and runtime profile inputs become bounded summary items. Provider secrets and token-like keys are excluded from simple mapping summaries.

Memory remains owned by `src/pp_agent/memory/`. ContextPipeline consumes memory provider output as `ContextItem` objects and does not retrieve, write, compact, or classify memory by itself.

Attachments remain owned by `src/pp_agent/attachments/`. The pipeline expects attachment previews or manifests, matching the existing "manifest and preview, read on demand" strategy.

Capability governance remains owned by `src/pp_agent/capabilities/`. ContextPipeline can include selected capability summaries, but it does not enable, approve, route, or execute capabilities.

AgentRuntime remains the execution owner. This layer can be wired in later as a pre-call builder or as a side-channel debug report without changing model invocation semantics.

## Trace Event

`build_context_built_event()` and Runtime use the v2 trace payload shape:

- `name`: `context_built`
- `attributes`: `model_id`, `runtime_id`, included count, dropped count
- `payload.context_payload_version`: `2`
- `payload.context`: `budget_report`, `included_sources`, `dropped_sources`, `sections`, `pack_summary`, and optional `memory_recall`

Runtime emits these fields through the existing `context_built` lifecycle event and `context.build` trace span. TraceInspect reads the same trace detail API and displays the budget report without adding a separate debug page.

Legacy flat fields such as `context_budget_report`, `context_included_sources`, `context_dropped_sources`, `context_sections`, and top-level `memory_recall` are no longer emitted by Runtime. Consumers should read `context_payload_version == 2` and then use the nested `context` object.

## Future Integrations

MCP Governance can contribute capability and project-context `ContextItem` providers after policy selection, while preserving MCPManager as the session and execution owner.

Skill progressive disclosure can contribute only `SKILL.md` summaries at first, then add specific referenced files as separate `ContextItem` objects when a task needs them. The budget report will make those disclosure decisions visible in traces and evals.
