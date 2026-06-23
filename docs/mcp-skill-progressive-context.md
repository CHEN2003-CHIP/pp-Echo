# MCP & Skill Progressive Context

## Why This Exists

pp-Echo treats tools, MCP servers, skills, plugins, memory, and project maps as different surfaces with different trust boundaries. Capability Governance answers what exists and whether it may be exposed. ContextPipeline answers what is actually assembled for a model call and why items were included or dropped.

This integration lets MCP and Skill contribute `ContextItem` objects progressively instead of dumping full descriptors, full skill bodies, or raw metadata into the prompt. The result is budgeted, source-referenced, and trace-visible context.

## OpenClaw-Style Responsibilities

OpenClaw-style separation is useful for pp-Echo:

- Tool: executable action with approval, risk, and runtime result handling.
- Skill: reusable instructions and optional artifacts that guide the agent.
- Plugin: packaging/distribution surface that may provide tools, skills, MCP servers, UI, or docs.

pp-Echo keeps the same boundary: MCPManager owns MCP discovery/execution, the Skill loader owns skill discovery/materialization, Capability Governance owns inventory and policy, and ContextPipeline owns budgeted model-facing context.

## Hermes-Style Progressive Disclosure

Hermes-style skill disclosure inspired the three-level skill model:

- Level 0: metadata card only. Includes skill name, description, origin, root, and discovery mode. It never materializes `SKILL.md` body.
- Level 1: explicit `SKILL.md` body. Loaded through existing `materialize_skill()` so lazy loading and cache behavior stay intact.
- Level 2: explicit artifact file from `references/`, `templates/`, or `scripts/`. Path resolution is constrained to the skill directory and traversal is denied.

Level 1 and Level 2 are explicit activation paths. Level 0 may appear in selected capabilities or project context because it is small and safe.

## Skill Context Rules

`SkillContextProvider` emits `ContextItem` objects with `SourceRef(source_type="capability", source_id="skill:<name>")` for Level 0/1 and `SourceRef(source_type="project_map", source_id="skill:<name>")` for Level 2 artifacts.

Optional `SKILL.md` frontmatter fields are supported without requiring old skills to migrate:

- `version`
- `category`
- `tags`
- `requires_capabilities`
- `optional_capabilities`
- `permissions`
- `context.default_level`
- `context.activation_level`
- `context.max_artifacts`
- `evals`

Manifest metadata is copied only after secret-like keys such as `secret`, `token`, `password`, and `api_key` are removed.

## MCP Context Rules

`MCPContextProvider` builds descriptor cards for MCP tools, resources, and prompts using the existing `MCPManager` list APIs. It does not call tools, read resources, or execute prompts.

Each card includes only a compact summary:

- server name
- tool name, resource URI, or prompt name
- description
- risk level
- approval mode
- remote/auth flags
- schema key summary

Raw MCP metadata is not copied into context. It is scanned deterministically for prompt injection and exfiltration indicators before any model-facing card is created.

## MCP Metadata Trust

MCP descriptors can come from local packages, remote servers, or third-party tooling. Descriptor descriptions and metadata are not inherently trustworthy, so pp-Echo scans them for patterns such as:

- ignoring previous instructions
- revealing system prompts
- bypassing approval
- hiding behavior from the user
- reading `.env`
- sending secrets or exfiltrating data
- suspicious URLs
- base64-like obfuscation

High-risk descriptors are dropped from model-facing context by default. The dropped item is still recorded in `ContextBudgetReport` with reason `mcp_metadata_scan_high_risk`.

## Permission Overlay

`MCPServerConfig` supports a pp-Echo overlay:

- `denied_tools`
- `allowed_tools`
- `tool_approval_overrides`
- `tool_risk_overrides`

`denied_tools` wins first. If `allowed_tools` is non-empty, only listed tools can enter context or capability exposure. Overrides affect pp-Echo `ContextItem` and Capability exposure only; they do not mutate original MCP descriptors or MCP server behavior.

## ContextPipeline Integration

`SkillContextAdapter` and `MCPContextAdapter` convert providers into inputs accepted by `ContextPipeline`.

Dropped MCP/Skill entries are passed through `pre_dropped_items` so `ContextBudgetReport` can record policy and scan drops alongside budget drops. Stable reasons include:

- `mcp_tool_denied`
- `mcp_metadata_scan_high_risk`
- `skill_artifact_path_denied`
- `context_budget_exceeded`

This keeps ContextPipeline as the budget and audit authority without replacing MCPManager, the Skill loader, or Capability Governance.

## Trace And Eval Verification

The existing `context_built` trace payload includes ContextPack summaries, included sources, dropped sources, section usage, and budget report. MCP and Skill context can be verified by checking:

- included Skill Level 0/1/2 item ids and source refs
- included MCP card ids and scan summaries
- dropped MCP/Skill item ids and drop reasons
- section budget usage in `selected_capabilities` and `project_context`

Deterministic tests cover lazy Skill disclosure, Level 2 path denial, MCP descriptor-only discovery, metadata scan flags, permission overlay drops, and budget report recording for MCP/Skill drops.

## Future Cleanup

After compatibility cleanup, pp-Echo can remove legacy context-hook direct trace fields and rely on ContextPipeline trace payloads as the canonical context audit channel. MCP Governance and Skill progressive disclosure can then connect to future MCP governance policy and activation-level routing without changing model-call semantics.
