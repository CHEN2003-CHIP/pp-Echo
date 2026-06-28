# Adapter Contract

Channel adapters are not execution engines. They are contract-bound ingress and
egress adapters around `AgentRuntime`.

Required adapter behavior:

- Normalize external messages into runtime input.
- Preserve `profile_id`, `session_id`, `channel_id`, `user_id`, and `source_ref`
  or their nearest platform equivalents.
- Call `AgentRuntime` exactly once for each accepted user turn.
- Deliver only a `RuntimeResult` or equivalent runtime snapshot.
- Record delivery traces with `runtime_trace_run_id` and `parent_id` linked to
  the runtime trace run.

Forbidden adapter behavior:

- Calling providers directly to produce final answers.
- Executing tools directly or bypassing `ToolRegistry`.
- Building context directly through `ContextPipeline` to construct a final answer.
- Attaching bot delivery to an unrelated runtime run.

This contract reflects OpenClaw-style Runtime/Channel separation and the
multi-platform adapter discipline visible in OpenClaw and Hermes Agent.
