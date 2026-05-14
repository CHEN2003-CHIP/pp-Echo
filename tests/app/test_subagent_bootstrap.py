from __future__ import annotations

from pp_agent.app import bootstrap
from pp_agent.storage.sessions import SessionStore
from pp_agent.storage.settings import Settings
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
    assert "orchestrate_agents" in tool_names
    assert metadata.model_callable is True
    assert metadata.tool_family == "subagent"
    assert metadata.exact_effect_mode == "none"
    orchestrate_metadata = registry.metadata()["orchestrate_agents"]
    assert orchestrate_metadata.model_callable is True
    assert orchestrate_metadata.tool_family == "subagent"
    decision = registry.evaluate_call("orchestrate_agents", {"goal": "analyze tests"})
    assert decision.action in {"allow", "ask"}


def test_configured_subagent_specs_apply_turn_budget_settings(tmp_path) -> None:
    settings = Settings.load(tmp_path)
    settings.subagents.default_max_turns = 5
    settings.subagents.max_turns = {"memory-scout": 2}

    specs = bootstrap.configured_subagent_specs(settings)

    assert specs["memory-scout"].max_turns == 2
    assert specs["repo-researcher"].max_turns == 5
