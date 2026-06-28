# Runtime Layers

pp-Echo keeps Provider, Model, Runtime, and Channel responsibilities separate.
This follows mature agent-runtime practice seen in projects such as OpenClaw:
providers expose model access, model profiles describe model behavior, Runtime
owns the prepared agent loop, and channels only handle ingress and delivery.

The runtime boundary is `AgentRuntime`. Channel adapters must not construct final
answers by calling providers, `ToolRegistry`, or `ContextPipeline` directly.
Adapters may normalize external messages into runtime input, preserve identity
fields, call runtime once per user turn, and deliver the resulting runtime output.

The default profile is currently `profile_id="default"` when a richer profile is
not supplied. Session and channel identity should be preserved in trace metadata
when available so a run can be audited from inbound message through delivery.

Internal adapter-facing payloads should use `RuntimeInput`, `RuntimeResult`, and
`RuntimeContext` from `pp_agent.runtime`. Existing `AgentRuntime.prompt(text)`
callers remain supported; the contract types stabilize identity and trace fields
for current and future adapters.
