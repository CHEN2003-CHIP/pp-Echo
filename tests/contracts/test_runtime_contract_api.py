from __future__ import annotations

from pp_agent.runtime import RuntimeContext, RuntimeInput, RuntimeResult
from pp_agent.runtime.contracts import runtime_context_from_mapping


def test_runtime_input_and_result_preserve_identity_fields() -> None:
    context = RuntimeContext(
        profile_id="default",
        session_id="session-1",
        channel_id="channel-1",
        external_user_id="external-user",
        source_ref="qq:event-1",
        run_id="run-1",
        runtime_trace_run_id="trace-run-1",
    )

    runtime_input = RuntimeInput("hello", context=context)
    result = RuntimeResult("ok", context=context)

    assert runtime_input.profile_id == "default"
    assert runtime_input.session_id == "session-1"
    assert runtime_input.channel_id == "channel-1"
    assert runtime_input.user_id == "external-user"
    assert runtime_input.source_ref == "qq:event-1"
    assert result.run_id == "run-1"
    assert result.runtime_trace_run_id == "trace-run-1"


def test_runtime_context_mapping_defaults_profile() -> None:
    context = runtime_context_from_mapping({"session_id": "s1"})

    assert context.profile_id == "default"
    assert context.session_id == "s1"
