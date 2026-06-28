from __future__ import annotations

from typing import Any

from pp_agent.runtime import RuntimeContext, RuntimeInput, RuntimeResult


class RecordingRuntime:
    def __init__(self, result: RuntimeResult | None = None) -> None:
        self.calls: list[RuntimeInput] = []
        self.result = result or RuntimeResult(
            "runtime-ok",
            context=RuntimeContext(session_id="session-1", runtime_trace_run_id="trace-run-1"),
        )

    def run_turn(self, runtime_input: RuntimeInput) -> RuntimeResult:
        self.calls.append(runtime_input)
        return self.result


class FakeChannelAdapter:
    """Contract-bound adapter used by P5 tests.

    It normalizes ingress, calls runtime once, and records delivery linked to the
    runtime trace. It intentionally has no provider, tool registry, or context
    pipeline dependency.
    """

    def __init__(self, runtime: RecordingRuntime) -> None:
        self.runtime = runtime
        self.deliveries: list[dict[str, Any]] = []

    def normalize(self, message: dict[str, Any]) -> RuntimeInput:
        return RuntimeInput(
            text=str(message["text"]),
            context=RuntimeContext(
                profile_id=str(message.get("profile_id") or "default"),
                session_id=str(message["session_id"]),
                channel_id=str(message["channel_id"]),
                external_user_id=str(message["user_id"]),
                source_ref=str(message["source_ref"]),
            ),
        )

    def handle(self, message: dict[str, Any]) -> RuntimeResult:
        runtime_input = self.normalize(message)
        result = self.runtime.run_turn(runtime_input)
        self.deliver(result, runtime_input)
        return result

    def deliver(self, result: RuntimeResult | None, runtime_input: RuntimeInput) -> None:
        if result is None:
            raise RuntimeError("Channel adapter cannot deliver without RuntimeResult")
        self.deliveries.append(
            {
                "text": result.text,
                "profile_id": runtime_input.profile_id,
                "session_id": runtime_input.session_id,
                "channel_id": runtime_input.channel_id,
                "user_id": runtime_input.user_id,
                "source_ref": runtime_input.source_ref,
                "runtime_trace_run_id": result.runtime_trace_run_id,
                "parent_id": result.runtime_trace_run_id,
            }
        )
