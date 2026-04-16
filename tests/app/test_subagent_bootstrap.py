from __future__ import annotations

from pp_agent.app import bootstrap
from pp_agent.storage.sessions import SessionStore
from pp_agent.tools.registry import ToolRegistry


def test_register_spawn_subagent_tool_adds_model_callable_tool(tmp_path) -> None:
    registry = ToolRegistry(tmp_path, current_session_id="session-1")
    session_store = SessionStore(tmp_path / "sessions")

    bootstrap._register_spawn_subagent_tool(
        workspace=tmp_path,
        session_store=session_store,
        tool_registry=registry,
        current_session_id="session-1",
    )

    tool_names = [item["function"]["name"] for item in registry.openapi_specs()]
    metadata = registry.metadata()["spawn_subagent"]

    assert "spawn_subagent" in tool_names
    assert metadata.model_callable is True
    assert metadata.tool_family == "subagent"
    assert metadata.exact_effect_mode == "none"
