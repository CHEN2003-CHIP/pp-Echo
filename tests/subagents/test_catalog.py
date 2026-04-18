from __future__ import annotations

import pytest

from pp_agent.subagents.catalog import SubAgentCatalog
from pp_agent.subagents.specs import SubAgentSpec


def test_subagent_catalog_lists_builtin_specs() -> None:
    catalog = SubAgentCatalog()

    names = [spec.name for spec in catalog.list()]

    assert "repo-researcher" in names
    assert "change-reviewer" in names
    assert "test-investigator" in names
    assert "api-scout" in names


def test_subagent_catalog_registers_and_gets_copy() -> None:
    catalog = SubAgentCatalog({})
    spec = SubAgentSpec(
        name="custom-reader",
        description="Inspect docs",
        system_prompt="Read docs only",
        tool_allowlist=["read_file"],
    )

    catalog.register(spec)
    loaded = catalog.get("custom-reader")

    assert loaded is not None
    assert loaded.name == "custom-reader"
    loaded.tool_allowlist.append("search_text")
    assert catalog.get("custom-reader").tool_allowlist == ["read_file"]


def test_subagent_catalog_rejects_duplicate_registration() -> None:
    catalog = SubAgentCatalog({})
    spec = SubAgentSpec(
        name="custom-reader",
        description="Inspect docs",
        system_prompt="Read docs only",
        tool_allowlist=["read_file"],
    )

    catalog.register(spec)

    with pytest.raises(ValueError):
        catalog.register(spec)
