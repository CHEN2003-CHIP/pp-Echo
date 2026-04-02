from __future__ import annotations

from pathlib import Path

from pp_agent.api import sdk


class FakeRuntime:
    def __init__(self) -> None:
        self.session_id = "session-1"
        self.state = type(
            "State",
            (),
            {
                "pending_plan_token": None,
                "pending_tool_calls": [],
                "queued_messages": [],
                "messages": [type("Message", (), {"role": "assistant", "content": [type("Part", (), {"text": "done"})()]})()],
            },
        )()

    def prompt(self, text: str):
        self.last_prompt = text
        event = type("Event", (), {"model_dump": lambda self, mode="json": {"type": "agent_end"}})()
        return [event]

    def continue_(self):
        event = type("Event", (), {"model_dump": lambda self, mode="json": {"type": "agent_end"}})()
        return [event]


class FakeHost:
    def create_session(self, workspace: Path, *, lifecycle_subscribers=None):
        return FakeRuntime()

    def restore_session(self, workspace: Path, session_id: str, *, lifecycle_subscribers=None):
        return FakeRuntime()

    def list_sessions(self, workspace: Path):
        return []

    def get_tree(self, workspace: Path, session_id=None, *, sort_mode="branch", lifecycle_subscribers=None):
        return type("View", (), {"model_dump": lambda self, mode="json": {"session_id": session_id, "sort_mode": sort_mode}})()

    def fork_session(self, workspace: Path, session_id: str, *, head_id=None, lifecycle_subscribers=None):
        return type("Result", (), {"model_dump": lambda self, mode="json": {"session_id": "forked"}})()

    def rewind_session(self, workspace: Path, session_id: str, *, turn_count=None, message_count=None, lifecycle_subscribers=None):
        return type("Result", (), {"model_dump": lambda self, mode="json": {"session_id": "rewound"}})()

    def approvals_summary(self, workspace: Path):
        return {"count": 0, "by_type": {}, "tokens": [], "items": []}


def test_sdk_run_does_not_return_events_by_default(tmp_path: Path) -> None:
    result = sdk.run("hello", tmp_path, host=FakeHost())

    assert result["session_id"] == "session-1"
    assert result["pending_plan_token"] is None
    assert result["event_count"] == 1
    assert result["assistant"] == "done"
    assert "stats" not in result
    assert "events" not in result


def test_sdk_run_collects_events_only_when_requested(tmp_path: Path) -> None:
    result = sdk.run("hello", tmp_path, collect_events=True, host=FakeHost())

    assert result["event_count"] == 1
    assert result["events"] == [{"type": "agent_end"}]


def test_sdk_run_uses_stats_for_optional_expansion(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    runtime.state.pending_tool_calls = [object()]
    runtime.state.queued_messages = [object()]

    class StatsHost(FakeHost):
        def create_session(self, workspace: Path, *, lifecycle_subscribers=None):
            return runtime

    result = sdk.run("hello", tmp_path, host=StatsHost())

    assert result["stats"] == {"pending_tool_call_count": 1, "queued_message_count": 1}
