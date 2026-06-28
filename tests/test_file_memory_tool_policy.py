from __future__ import annotations

from pathlib import Path

from pp_agent.app.bootstrap import create_tool_registry, load_settings


def test_file_memory_tools_are_registered_and_policy_gated(tmp_path: Path) -> None:
    settings = load_settings(tmp_path)
    settings.memory.file_memory_allow_remote_embedding = False
    registry = create_tool_registry(tmp_path)

    specs = {item["function"]["name"] for item in registry.openapi_specs()}
    metadata = registry.metadata()
    decision = registry.evaluate_call("memory_get", {"path": "MEMORY.md"})

    assert {"memory_search", "memory_get"}.issubset(specs)
    assert metadata["memory_get"].category == "memory"
    assert metadata["memory_get"].known_safe_inspect is True
    assert decision.action == "allow"


def test_memory_search_uses_local_recall_for_runtime_policy_when_remote_embedding_configured(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir()
    (project_dir / "config.json").write_text(
        '{"memory": {"embedding_enable": true, "vector_enable": true, "file_memory_allow_remote_embedding": true}}',
        encoding="utf-8",
    )
    registry = create_tool_registry(tmp_path)

    metadata = registry.metadata()["memory_search"]
    decision = registry.evaluate_call("memory_search", {"query": "pytest"})

    assert metadata.requests_network_hint is False
    assert metadata.known_safe_inspect is True
    assert decision.action == "allow"


def test_core_memory_tools_declare_read_and_write_metadata(tmp_path: Path) -> None:
    registry = create_tool_registry(tmp_path)
    metadata = registry.metadata()

    assert metadata["memory_search"].permission_domain == "read"
    assert metadata["memory_search"].known_safe_inspect is True
    assert metadata["memory_propose"].permission_domain == "read"
    assert metadata["memory_propose"].exact_effect_mode == "auto"
    assert metadata["memory_propose"].known_safe_inspect is False
    assert metadata["memory_pending"].known_safe_inspect is True
    assert metadata["memory_approve"].requires_confirmation is True
    assert metadata["memory_approve"].permission_domain == "approval"
    assert metadata["memory_approve"].exact_effect_mode == "auto"
    assert metadata["memory_archive"].requires_confirmation is True
