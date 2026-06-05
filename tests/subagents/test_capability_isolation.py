from __future__ import annotations

from types import SimpleNamespace

import pytest

from pp_agent.app.skills_runtime import SkillRuntime
from pp_agent.domain import ChatMessage, TextPart
from pp_agent.runtime.hooks import ContextHookEntry, RuntimeHooks
from pp_agent.storage.settings import Settings
from pp_agent.subagents.capabilities import MCPPolicy, SubAgentProfile, ToolCapabilityPolicy
from pp_agent.subagents.runtime_adapter import SubAgentRuntimeAdapter
from pp_agent.subagents.specs import default_subagent_specs
from pp_agent.tools.registry import ToolRegistry


def _tool_names(registry: ToolRegistry) -> list[str]:
    return [item["function"]["name"] for item in registry.openapi_specs()]


def test_apply_profile_removes_child_mcp_and_skill_hooks(tmp_path):
    calls: list[str] = []

    def runtime_hook(_state, messages):
        calls.append("runtime")
        return messages

    def mcp_hook(_state, messages):
        calls.append("mcp")
        return messages

    def skill_hook(_state, messages):
        calls.append("skill")
        return messages

    runtime = SimpleNamespace(
        runtime_hooks=RuntimeHooks(
            transform_context=[
                ContextHookEntry("runtime", "runtime", runtime_hook, enabled_for_subagent=True),
                ContextHookEntry("mcp", "mcp", mcp_hook),
                ContextHookEntry("skill", "skill", skill_hook),
            ]
        ),
        tool_registry=ToolRegistry(tmp_path),
        mcp_runtime=SimpleNamespace(tool_registry=None),
        skill_runtime=SimpleNamespace(),
    )
    profile = default_subagent_specs()["repo-researcher"].resolved_profile()

    SubAgentRuntimeAdapter(runtime).apply_profile(profile)

    assert [hook.name for hook in runtime.runtime_hooks.transform_context_hooks] == ["runtime"]
    assert runtime.mcp_runtime.subagent_mcp_policy.enabled is False
    assert runtime.skill_runtime.subagent_skill_policy.enabled is False


def test_registry_filters_and_denies_residual_mcp_tool(tmp_path):
    registry = ToolRegistry(tmp_path)
    registry._register_dynamic_tool_internal(
        name="local-docs.search",
        description="Search docs",
        parameters={"type": "object", "properties": {}},
        executor=lambda _workspace, _arguments: "ok",
        category="mcp",
        tool_family="mcp",
        exact_effect_mode="auto",
        non_side_effectful=True,
        known_safe_inspect=True,
    )
    registry.set_capability_profile(
        SubAgentProfile(
            name="api-scout",
            tool=ToolCapabilityPolicy(allowlist=["read_file"]),
            mcp=MCPPolicy(enabled=False),
        )
    )

    assert "local-docs.search" not in _tool_names(registry)
    with pytest.raises(PermissionError):
        registry.execute("local-docs.search", {})


def test_registry_allows_only_mcp_policy_dynamic_whitelist(tmp_path):
    registry = ToolRegistry(
        tmp_path,
        capability_profile=SubAgentProfile(
            name="api-scout",
            tool=ToolCapabilityPolicy(allowlist=["local-docs.search"], allow_dynamic_tools=False),
            mcp=MCPPolicy(
                enabled=True,
                allowed_servers=["local-docs"],
                allowed_tools=["local-docs.search"],
                allow_dynamic_tools=True,
            ),
        ),
    )

    for name in ("local-docs.search", "local-docs.write"):
        registry._register_dynamic_tool_internal(
            name=name,
            description=name,
            parameters={"type": "object", "properties": {}},
            executor=lambda _workspace, _arguments, tool=name: tool,
            category="mcp",
            tool_family="mcp",
            exact_effect_mode="auto",
            non_side_effectful=True,
            known_safe_inspect=True,
        )

    assert "local-docs.search" in registry.metadata()
    assert "local-docs.write" not in registry.metadata()
    assert _tool_names(registry) == ["local-docs.search"]


def test_read_only_profile_denies_write_execute_even_if_tool_is_present(tmp_path):
    registry = ToolRegistry(
        tmp_path,
        capability_profile=SubAgentProfile(
            name="readonly",
            tool=ToolCapabilityPolicy(allowlist=["write_file"]),
        ),
    )

    assert "write_file" not in _tool_names(registry)
    with pytest.raises(PermissionError):
        registry.execute("write_file", {"path": "x.txt", "content": "x"})


def test_skill_policy_disabled_prevents_prompt_injection(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / "home"))
    skill_path = tmp_path / "skills" / "review-helper" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("---\nname: review-helper\ndescription: Review code\n---\nbody", encoding="utf-8")
    settings = Settings.load(tmp_path)
    runtime = SkillRuntime(workspace=tmp_path, user_root=settings.global_dir, config=settings.capabilities.skills)
    runtime.subagent_skill_policy = default_subagent_specs()["repo-researcher"].resolved_profile().skill
    messages = [ChatMessage(role="system", content=[TextPart(text="base")], timestamp=0)]
    state = SimpleNamespace(messages=[ChatMessage(role="user", content=[TextPart(text="use review-helper")], timestamp=0)])

    transformed = runtime.transform_context(state, messages)

    assert transformed == messages
    assert runtime.active_skills() == []
