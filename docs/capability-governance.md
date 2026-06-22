# Capability Governance Layer

pp-Echo needs Capability Governance because Tool, MCP, Skill, SubAgent, Connector, and future runtime adapters all expose outside power into an Agent run. The governance layer gives those powers one shared descriptor, binding, policy, router, and trace shape without replacing `ToolRegistry`, `MCPManager`, `SkillRuntime`, `Bot Center`, or `AgentRuntime`.

## Descriptor And Binding

`CapabilityDescriptor` describes what a capability is: id, kind, source, schemas, risk, effects, tags, status, cost, latency, and trace-safe metadata.

`CapabilityBinding` describes whether a scope may use that capability: global, workspace, bot, connector, or session enablement, approval policy, trust-level allow/deny lists, call limits, timeout hints, and reason metadata.

The v0.3.0 cleanup removed the deprecated `CapabilityDescriptor.path` and `CapabilityDescriptor.origin_type` aliases, removed legacy `low/medium/high` risk normalization from the descriptor model, and deleted `pp_agent.capabilities.compatibility`.

## Unified Capability Sources

Current discovery is snapshot-only:

- `ToolRegistry` tools become `builtin_tool`.
- MCP tools, resources, and prompts become `mcp_tool`, `mcp_resource`, and `mcp_prompt`.
- Skill folders and `SKILL.md` files become `skill`.
- `SubAgentSpec` entries become `subagent`.
- Bot connector configs become `connector`.
- Existing extension descriptors remain available as `extension` catalog entries while execution stays owned by the extension runtime.

Discovery does not execute tools, call MCP tools, materialize skill bodies, or start bots.

## Router

`CapabilityRouter.select()` accepts task text, a `CapabilityCatalog`, bindings, route context, and `max_capabilities`. It filters disabled or denied capabilities through `CapabilityPolicy`, blocks trust-level violations, scores remaining descriptors by simple keyword matches over name, description, and tags, and prefers `safe/read` risks ahead of write, network, shell, and destructive risks.

The router deliberately does not use embeddings, LLM calls, or execution-time side effects.

## Approval, Trace, And Eval

Capability Governance is the layer before exposure and routing. Approval Gate still owns execution approval, `ToolRegistry` still evaluates tool effects, and runtime events still flow through lifecycle and TraceInspect.

`build_capability_selected_event_payload()` provides a testable event payload:

```json
{
  "type": "capability_selected",
  "selected": [{"id": "attachment.search", "kind": "builtin_tool", "risk_level": "read"}],
  "blocked": [{"id": "shell.exec", "reason": "denied_by_trust_level"}],
  "policy_context": {"bot_id": "qq-main", "connector_id": "qqbot", "trust_level": "group"}
}
```

Future runtime wiring can emit this payload after run start or before provider tool exposure without changing the execution path.

## Why This Enables Later Work

This layer creates a common vocabulary for ContextPipeline, MCP Governance, SkillManifest, BotProfile, and Eval. Those systems can reason over one catalog and policy model instead of reading ToolRegistry metadata, MCP descriptors, skill loader state, and Bot Center config directly.

## Safety Notes

MCP and extension metadata can be attacker-controlled or misleading. Capability metadata is JSON-serializable, rejects sensitive keys such as `api_key`, `secret`, `token`, and `password`, and is intended to be filtered and traced before it influences capability exposure.

## Staged Migration

v0.2.0 added descriptor v2, binding, policy, router, trace payload builder, and compatibility adapters while keeping old modules available.

v0.2.1 migrates read surfaces toward `CapabilityCatalog`, `CapabilityPolicy`, and `CapabilityRouter`:

- `/api/capability-config` includes a catalog snapshot for UI consumers.
- `/api/sessions/{session_id}/tools` returns descriptor-derived tool data instead of direct registry metadata.
- Runtime emits `capability_selected` trace events before provider tool exposure.
- TraceInspect displays capability selection records.
- Bot Center displays connector capability governance status.
- Deprecated compatibility helpers were isolated from the main discovery providers before removal.
- Capability catalog, policy, router, and discovery boundaries now carry explicit docstrings for the staged migration contract.
- Tests lock the main discovery module away from deprecated compatibility adapters and verify binding specificity order.

v0.3.0 removes descriptor aliases, old discovery helpers, legacy capability risk labels, compatibility-only tests, and `pp_agent.capabilities.compatibility`.

## Current Status

Capability Governance is currently an additive governance layer. It inventories and routes capabilities for listing, policy checks, and trace visibility, while execution remains in the existing runtime modules.

The mature v0.3.0 state now has:

- Descriptor v2, binding, policy, router, and trace payloads in place without compatibility adapters.
- Tool listing, capability config, TraceInspect, Bot Center, and Capability Workbench reading governance catalog snapshots for visibility.
- Main discovery providers emitting native v2 descriptor fields.
- Focused tests for descriptor safety, catalog snapshots, policy specificity, router ordering, trace payload shape, lifecycle emission, and Web config inventory.

Readiness is currently measured through focused governance tests plus `workflow doctor --json`. Doctor reports status `ok`, with existing pending workspace actions/config effects still visible in the report.

## Next Round Plan

Capability Governance cleanup is complete. Future work should move to other pp-Echo upgrade areas instead of continuing this feature line.

- Add persisted binding storage only after the settings/config schema is ready.
- Keep ToolRegistry, MCP client, Skill loader, Bot Center, and AgentRuntime as execution owners.
- Re-run doctor/report as the readiness gate for later upgrade areas.

## v0.3.0 Removal Checklist

- Done: removed `path` and `origin_type` compatibility aliases from `CapabilityDescriptor`.
- Done: removed legacy `low/medium/high` risk normalization from `CapabilityDescriptor`.
- Done: deleted `pp_agent.capabilities.compatibility`.
- Done: removed compatibility-only helper surface; remaining tests verify native v2 descriptors.
- Done: TraceInspect, Bot Center, tool listing, Capability Workbench, and capability config pages read catalog snapshots for governance visibility.
- Done: MCP, Skill, SubAgent, Connector, extension, and builtin tool discovery emit native v2 descriptor fields.
