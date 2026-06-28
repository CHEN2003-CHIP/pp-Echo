# New Adapter Template

Future channel adapters should be thin ingress/egress boundaries around
`AgentRuntime`.

```python
from pp_agent.runtime import RuntimeContext, RuntimeInput, RuntimeResult


def normalize_inbound(payload: dict) -> RuntimeInput:
    return RuntimeInput(
        text=str(payload["text"]),
        context=RuntimeContext(
            profile_id=str(payload.get("profile_id") or "default"),
            session_id=str(payload["session_id"]),
            channel_id=str(payload["channel_id"]),
            external_user_id=str(payload["user_id"]),
            source_ref=str(payload["event_id"]),
        ),
    )


def handle_message(payload: dict, runtime) -> RuntimeResult:
    runtime_input = normalize_inbound(payload)
    events = runtime.prompt(runtime_input.text)
    runtime_trace_run_id = find_latest_runtime_trace_run_id(runtime_input.session_id)
    result = RuntimeResult(
        text=extract_final_answer(events),
        context=RuntimeContext(
            profile_id=runtime_input.profile_id,
            session_id=runtime_input.session_id,
            channel_id=runtime_input.channel_id,
            external_user_id=runtime_input.user_id,
            source_ref=runtime_input.source_ref,
            runtime_trace_run_id=runtime_trace_run_id,
        ),
        events=events,
    )
    record_delivery_trace(result)
    deliver(result)
    return result
```

Delivery traces must include `runtime_trace_run_id` and `parent_id` set to the
runtime trace run id.

Adapters must not:

- Call `ToolRegistry` directly.
- Call providers directly.
- Construct a final answer outside `AgentRuntime` output.
- Mutate prompts after `ContextPipeline` has prepared runtime context.
- Create unrelated `run_id` values for delivery traces.
