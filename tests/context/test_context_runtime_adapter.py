from __future__ import annotations

import json
from pathlib import Path

import pytest

from pp_agent.coding import (
    RepositorySummary,
    RepositorySummarySection,
    RepositorySummarySource,
    ScopedInstruction,
    ScopedInstructionActivationRecord,
    scoped_instruction_records_to_context_items,
)
from pp_agent.capabilities.descriptor import CapabilityDescriptor
from pp_agent.capabilities.router import BlockedCapability, CapabilitySelection
from pp_agent.context import build_project_context
from pp_agent.context.adapters import build_context_pack_from_messages, context_pack_to_trace_details
from pp_agent.context.runtime_bridge import build_runtime_context_pack
from pp_agent.coding.repository import repository_analysis_to_context_item
from pp_agent.domain import ChatMessage, TextPart
from pp_agent.runtime.state import AgentState
from pp_agent.storage.settings import Settings


CORE_MEMORY_METADATA_KEY = "core_memory_snapshot"
RECALL_METADATA_KEY = "memory_recall"


def _message(role: str, text: str, *, metadata: dict | None = None) -> ChatMessage:
    return ChatMessage(role=role, content=[TextPart(text=text)], metadata=metadata or {}, timestamp=0.0)  # type: ignore[arg-type]


def _scoped_record(
    source_path: str,
    content: str,
    *,
    scope_root: str,
    digest: str,
    trigger_kind: str = "task_scope",
    trigger_path: str = "src/a.py",
    source_kind: str = "AGENTS.md",
) -> ScopedInstructionActivationRecord:
    return ScopedInstructionActivationRecord(
        instruction=ScopedInstruction(
            source_path=source_path,
            scope_root=scope_root,
            source_kind=source_kind,  # type: ignore[arg-type]
            content=content,
            content_digest=digest,
            bytes_consumed=len(content),
            truncated=False,
        ),
        trigger_kind=trigger_kind,
        trigger_path=trigger_path,
    )


def test_adapter_classifies_runtime_context_messages() -> None:
    messages = [
        _message("system", "You are pp-Echo."),
        _message("system", "Runtime notes:\n- Active session id: s1."),
        _message("system", "Core memory snapshot", metadata={CORE_MEMORY_METADATA_KEY: {"workspace_id": "w1", "snapshot_hash": "h1"}}),
        _message("system", "Relevant long-term memory snippets", metadata={RECALL_METADATA_KEY: {"retrieval_version": "v2"}}),
        _message("system", "Current session attachments:\n- att1 preview_only=short"),
        _message("system", "Active skills loaded for this turn:\n- python"),
        _message("user", "hello"),
    ]

    pack = build_context_pack_from_messages(state=None, messages=messages)

    assert pack.system_instructions[0].id == "message:0:system"
    assert pack.runtime_notes[0].id == "message:1:runtime_notes"
    assert pack.core_memory_snapshot[0].source_ref.source_type == "core_governance"
    assert pack.episodic_memory_items[0].source_ref.source_type == "episodic_memory"
    assert pack.attachment_previews[0].source_ref.source_type == "attachment"
    assert pack.skills[0].source_ref.source_type == "skill"
    assert pack.recent_turns[0].source_ref.source_type == "conversation"


def test_context_trace_details_do_not_include_attachment_full_content() -> None:
    messages = [
        _message("system", "You are pp-Echo."),
        _message("system", "Current session attachments:\n- att1 preview_only=short SECRET_FULL_TEXT_SHOULD_NOT_TRACE"),
    ]

    details = context_pack_to_trace_details(build_context_pack_from_messages(state=None, messages=messages))

    assert "SECRET_FULL_TEXT_SHOULD_NOT_TRACE" not in json.dumps(details, ensure_ascii=False)
    assert details["context_payload_version"] == 3
    assert details["context"]["sections"]["attachment_previews"]["count"] == 1  # type: ignore[index]
    assert "context_budget_report" not in details


def test_core_memory_budget_error_is_trace_visible_without_mutating_messages() -> None:
    messages = [
        _message("system", "You are pp-Echo."),
        _message("system", "x" * 4000, metadata={CORE_MEMORY_METADATA_KEY: {"workspace_id": "w1"}}),
        _message("user", "hello"),
    ]
    before = [message.model_dump(mode="json") for message in messages]

    pack = build_context_pack_from_messages(state=None, messages=messages)
    details = context_pack_to_trace_details(pack)

    assert [message.model_dump(mode="json") for message in messages] == before
    assert details["context"]["core_memory_budget_error"] is True
    assert details["context"]["dropped_sources"][0]["reason"] == "core_memory_budget_exceeded_not_truncated"  # type: ignore[index]


def test_runtime_bridge_adds_capability_selection_and_blocks_dropped(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    selection = CapabilitySelection(
        selected=[
            CapabilityDescriptor(
                kind="builtin_tool",
                name="list_files",
                description="List files",
                source="builtin:list_files",
                risk_level="read",
            )
        ],
        blocked=[BlockedCapability(capability_id="run_shell", reason="trust_denied", policy="deny")],
    )

    pack = build_runtime_context_pack(
        state=AgentState(system_prompt="system"),
        messages=[_message("system", "system"), _message("user", "hello")],
        settings=settings,
        session_id="s1",
        capability_selection=selection,
    )
    rendered_text = "\n".join(part.text for message in pack.final_messages for part in message.content if isinstance(part, TextPart))

    assert pack.capabilities[0].id == "capability:list_files"
    assert pack.budget_report.drop_reasons["capability:run_shell"] == "capability_blocked"
    assert "run_shell" not in rendered_text


def test_runtime_bridge_includes_repository_analysis_in_project_context(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    pack = build_runtime_context_pack(
        state=AgentState(system_prompt="system"),
        messages=[_message("system", "system"), _message("user", "hello")],
        settings=settings,
        session_id="s1",
    )

    assert any(item.title == "Repository analysis" for item in pack.project_context)
    assert any(item.metadata.get("repository_analysis") for item in pack.project_context)
    assert repository_analysis_to_context_item.__doc__


def test_runtime_bridge_repository_summary_instruction_reaches_final_messages(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    settings.context_pipeline.context_pipeline_mode = "on"
    summary = RepositorySummary(
        workspace_name="demo",
        sections=[
            RepositorySummarySection(
                "project_instruction:AGENTS.md",
                "Project instruction: AGENTS.md",
                "project_instruction",
                "Use focused tests from repository summary.",
                ["agents"],
            ),
            RepositorySummarySection("project_metadata", "Project metadata", "project_context", {"languages": ["Python"]}, ["project-context"]),
        ],
        sources=[
            RepositorySummarySource("agents", "project_instruction", path="AGENTS.md"),
            RepositorySummarySource("project-context", "project_context"),
        ],
    )

    pack = build_runtime_context_pack(
        state=AgentState(system_prompt="system"),
        messages=[_message("system", "system"), _message("user", "hello")],
        settings=settings,
        session_id="s1",
        repository_summary=summary,
    )
    rendered_text = "\n".join(part.text for message in pack.final_messages for part in message.content if isinstance(part, TextPart))

    assert any(item.id == "repository-summary:project_instruction:AGENTS.md" for item in pack.project_context)
    assert "Use focused tests from repository summary." in rendered_text
    assert "languages" not in rendered_text


def test_runtime_bridge_repository_summary_module_guidance_reaches_final_messages(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    settings.context_pipeline.context_pipeline_mode = "on"
    summary = RepositorySummary(
        workspace_name="demo",
        sections=[
            RepositorySummarySection(
                "module_doc:src:pp_agent:coding:MODULE.md",
                "Module guidance: src/pp_agent/coding/MODULE.md",
                "module_doc",
                "Keep repository summary adapters pure.",
                ["module"],
            )
        ],
        sources=[RepositorySummarySource("module", "module_doc", path="src/pp_agent/coding/MODULE.md")],
    )

    pack = build_runtime_context_pack(
        state=AgentState(system_prompt="system"),
        messages=[_message("system", "system"), _message("user", "hello")],
        settings=settings,
        session_id="s1",
        repository_summary=summary,
    )
    details = context_pack_to_trace_details(pack)
    rendered_text = "\n".join(part.text for message in pack.final_messages for part in message.content if isinstance(part, TextPart))

    assert "Keep repository summary adapters pure." in rendered_text
    assert any(ref.path == "src/pp_agent/coding/MODULE.md" for ref in pack.source_refs)
    assert "repository-summary:module_doc:src:pp_agent:coding:MODULE.md" in details["context"]["sections"]["project_context"]["item_ids"]  # type: ignore[index]


def test_runtime_bridge_repository_summary_none_and_empty_preserve_behavior(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    messages = [_message("system", "system"), _message("user", "hello")]

    without_summary = build_runtime_context_pack(
        state=AgentState(system_prompt="system"),
        messages=messages,
        settings=settings,
        session_id="s1",
        repository_summary=None,
    )
    empty_summary = build_runtime_context_pack(
        state=AgentState(system_prompt="system"),
        messages=messages,
        settings=settings,
        session_id="s1",
        repository_summary=RepositorySummary(workspace_name="demo"),
    )

    assert [item.id for item in without_summary.project_context] == [item.id for item in empty_summary.project_context]
    assert [message.model_dump(mode="json") for message in without_summary.final_messages] == [
        message.model_dump(mode="json") for message in empty_summary.final_messages
    ]


def test_runtime_bridge_repository_summary_budget_drop_uses_existing_reason(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    settings.context_pipeline.section_budgets = {"project_context": 20}
    summary = RepositorySummary(
        workspace_name="demo",
        sections=[
            RepositorySummarySection(
                "project_instruction:AGENTS.md",
                "Project instruction: AGENTS.md",
                "project_instruction",
                "This repository instruction is intentionally too large for the tiny project context budget.",
                ["agents"],
            )
        ],
        sources=[RepositorySummarySource("agents", "project_instruction", path="AGENTS.md")],
    )

    pack = build_runtime_context_pack(
        state=AgentState(system_prompt="system"),
        messages=[_message("system", "system"), _message("user", "hello")],
        settings=settings,
        session_id="s1",
        repository_summary=summary,
    )
    rendered_text = "\n".join(part.text for message in pack.final_messages for part in message.content if isinstance(part, TextPart))

    assert "repository-summary:project_instruction:AGENTS.md" in pack.budget_report.drop_reasons
    assert pack.budget_report.drop_reasons["repository-summary:project_instruction:AGENTS.md"] == "section_budget_exceeded"
    assert "intentionally too large" not in rendered_text


def test_runtime_bridge_repository_summary_adapter_called_once_and_trace_is_existing_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pp_agent.context import runtime_bridge

    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    summary = RepositorySummary(
        workspace_name="demo",
        sections=[RepositorySummarySection("project_instruction:AGENTS.md", "Project instruction: AGENTS.md", "project_instruction", "One call only.", ["agents"])],
        sources=[RepositorySummarySource("agents", "project_instruction", path="AGENTS.md")],
    )
    calls = 0
    real_adapter = runtime_bridge.repository_summary_to_context_items

    def spy_adapter(value: RepositorySummary):
        nonlocal calls
        calls += 1
        return real_adapter(value)

    monkeypatch.setattr(runtime_bridge, "repository_summary_to_context_items", spy_adapter)

    pack = build_runtime_context_pack(
        state=AgentState(system_prompt="system"),
        messages=[_message("system", "system"), _message("user", "hello")],
        settings=settings,
        session_id="s1",
        repository_summary=summary,
    )
    details = context_pack_to_trace_details(pack)

    assert calls == 1
    assert details["context_payload_version"] == 3
    assert any(source.get("path") == "AGENTS.md" for source in details["context"]["source_refs"])  # type: ignore[index]
    assert "repository-summary:project_instruction:AGENTS.md" in details["context"]["sections"]["project_context"]["item_ids"]  # type: ignore[index]
    assert "schema_version" not in json.dumps(details)


def test_runtime_bridge_repository_summary_integration_does_not_reread_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("summary integration must not reread repository summary sources")

    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    summary = RepositorySummary(
        workspace_name="demo",
        sections=[RepositorySummarySection("project_instruction:AGENTS.md", "Project instruction: AGENTS.md", "project_instruction", "Already loaded.", ["agents"])],
        sources=[RepositorySummarySource("agents", "project_instruction", path="AGENTS.md")],
    )
    monkeypatch.setattr(Path, "open", fail)
    monkeypatch.setattr(Path, "read_text", fail)
    monkeypatch.setattr(Path, "read_bytes", fail)

    pack = build_runtime_context_pack(
        state=AgentState(system_prompt="system"),
        messages=[_message("system", "system"), _message("user", "hello")],
        settings=settings,
        session_id="s1",
        repository_summary=summary,
    )

    assert any(item.id == "repository-summary:project_instruction:AGENTS.md" for item in pack.project_context)


def test_runtime_bridge_repository_summary_final_messages_are_deterministic(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    summary = RepositorySummary(
        workspace_name="demo",
        sections=[
            RepositorySummarySection("module_doc:src:MODULE.md", "Module guidance: src/MODULE.md", "module_doc", "Module rule.", ["module"]),
            RepositorySummarySection("project_instruction:AGENTS.md", "Project instruction: AGENTS.md", "project_instruction", "Project rule.", ["agents"]),
        ],
        sources=[
            RepositorySummarySource("module", "module_doc", path="src/MODULE.md"),
            RepositorySummarySource("agents", "project_instruction", path="AGENTS.md"),
        ],
    )
    messages = [_message("system", "system"), _message("user", "hello")]

    first = build_runtime_context_pack(state=AgentState(system_prompt="system"), messages=messages, settings=settings, session_id="s1", repository_summary=summary)
    second = build_runtime_context_pack(state=AgentState(system_prompt="system"), messages=messages, settings=settings, session_id="s1", repository_summary=summary)

    assert [item.id for item in first.project_context] == [item.id for item in second.project_context]
    assert [message.model_dump(mode="json") for message in first.final_messages] == [message.model_dump(mode="json") for message in second.final_messages]


def test_runtime_bridge_repository_summary_does_not_duplicate_existing_manifest_excerpt(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    sentinel = "UNIQUE_PROJECT_INSTRUCTION_SENTINEL"
    (tmp_path / "AGENTS.md").write_text(sentinel, encoding="utf-8")
    summary = RepositorySummary(
        workspace_name="demo",
        sections=[
            RepositorySummarySection(
                "project_instruction:AGENTS.md",
                "Project instruction: AGENTS.md",
                "project_instruction",
                sentinel,
                ["agents"],
            )
        ],
        sources=[RepositorySummarySource("agents", "project_instruction", path="AGENTS.md")],
    )

    pack = build_runtime_context_pack(
        state=AgentState(system_prompt="system"),
        messages=[_message("system", "system"), _message("user", "hello")],
        settings=settings,
        session_id="s1",
        repository_summary=summary,
    )
    rendered_text = "\n".join(part.text for message in pack.final_messages for part in message.content if isinstance(part, TextPart))

    assert rendered_text.count(sentinel) == 1


def test_runtime_bridge_without_repository_summary_keeps_manifest_excerpt(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    sentinel = "NO_SUMMARY_PROJECT_INSTRUCTION_SENTINEL"
    (tmp_path / "AGENTS.md").write_text(sentinel, encoding="utf-8")

    pack = build_runtime_context_pack(
        state=AgentState(system_prompt="system"),
        messages=[_message("system", "system"), _message("user", "hello")],
        settings=settings,
        session_id="s1",
        repository_summary=None,
    )
    rendered_text = "\n".join(part.text for message in pack.final_messages for part in message.content if isinstance(part, TextPart))

    assert rendered_text.count(sentinel) == 1


def test_runtime_bridge_module_only_repository_summary_keeps_manifest_excerpt(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    manifest_sentinel = "MODULE_ONLY_PROJECT_INSTRUCTION_SENTINEL"
    module_sentinel = "MODULE_ONLY_SUMMARY_SENTINEL"
    (tmp_path / "AGENTS.md").write_text(manifest_sentinel, encoding="utf-8")
    summary = RepositorySummary(
        workspace_name="demo",
        sections=[
            RepositorySummarySection(
                "module_doc:src:MODULE.md",
                "Module guidance: src/MODULE.md",
                "module_doc",
                module_sentinel,
                ["module"],
            )
        ],
        sources=[RepositorySummarySource("module", "module_doc", path="src/MODULE.md")],
    )

    pack = build_runtime_context_pack(
        state=AgentState(system_prompt="system"),
        messages=[_message("system", "system"), _message("user", "hello")],
        settings=settings,
        session_id="s1",
        repository_summary=summary,
    )
    rendered_text = "\n".join(part.text for message in pack.final_messages for part in message.content if isinstance(part, TextPart))

    assert rendered_text.count(manifest_sentinel) == 1
    assert module_sentinel in rendered_text


def test_runtime_bridge_scoped_instruction_reaches_final_messages_and_trace(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    settings.context_pipeline.context_pipeline_mode = "on"
    scoped_items = scoped_instruction_records_to_context_items(
        [_scoped_record("src/AGENTS.md", "Use scoped runtime rules.", scope_root="src", digest="scoped-digest")]
    )

    pack = build_runtime_context_pack(
        state=AgentState(system_prompt="system"),
        messages=[_message("system", "system"), _message("user", "hello")],
        settings=settings,
        session_id="s1",
        scoped_instruction_items=scoped_items,
    )
    details = context_pack_to_trace_details(pack)
    rendered_text = "\n".join(part.text for message in pack.final_messages for part in message.content if isinstance(part, TextPart))

    assert "Use scoped runtime rules." in rendered_text
    assert "scoped-instruction:src/AGENTS.md" in details["context"]["sections"]["project_context"]["item_ids"]  # type: ignore[index]
    assert any(source.get("path") == "src/AGENTS.md" for source in details["context"]["source_refs"])  # type: ignore[index]
    scoped_message = next(message for message in pack.final_messages if message.metadata.get("context_item_id") == "scoped-instruction:src/AGENTS.md")
    assert scoped_message.metadata["scoped_instruction_source_kind"] == "AGENTS.md"
    assert scoped_message.metadata["scope_root"] == "src"
    assert scoped_message.metadata["content_digest"] == "scoped-digest"


def test_runtime_bridge_scoped_instruction_budget_uses_existing_drop_reason(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    settings.context_pipeline.section_budgets = {"project_context": 20}
    scoped_items = scoped_instruction_records_to_context_items(
        [_scoped_record("src/AGENTS.md", "This scoped instruction is too large for the project context budget.", scope_root="src", digest="d1")]
    )

    pack = build_runtime_context_pack(
        state=AgentState(system_prompt="system"),
        messages=[_message("system", "system"), _message("user", "hello")],
        settings=settings,
        session_id="s1",
        scoped_instruction_items=scoped_items,
    )
    rendered_text = "\n".join(part.text for message in pack.final_messages for part in message.content if isinstance(part, TextPart))

    assert pack.budget_report.drop_reasons["scoped-instruction:src/AGENTS.md"] == "section_budget_exceeded"
    assert "too large for the project context budget" not in rendered_text


def test_runtime_bridge_scoped_budget_prefers_nearest_but_renders_shallow_to_nearest(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    settings.context_pipeline.section_budgets = {"project_context": 70}
    shallow_content = "SHALLOW_SCOPED_RULE " + ("s" * 45)
    nearest_content = "NEAREST_SCOPED_RULE " + ("n" * 45)
    scoped_items = scoped_instruction_records_to_context_items(
        [
            _scoped_record("src/AGENTS.md", shallow_content, scope_root="src", digest="d1", trigger_path="src/a.py"),
            _scoped_record("src/pkg/AGENTS.md", nearest_content, scope_root="src/pkg", digest="d2", trigger_path="src/pkg/a.py"),
        ]
    )

    pack = build_runtime_context_pack(
        state=AgentState(system_prompt="system"),
        messages=[_message("system", "system"), _message("user", "hello")],
        settings=settings,
        session_id="s1",
        scoped_instruction_items=scoped_items,
    )
    rendered_text = "\n".join(part.text for message in pack.final_messages for part in message.content if isinstance(part, TextPart))

    assert "NEAREST_SCOPED_RULE" in rendered_text
    assert "SHALLOW_SCOPED_RULE" not in rendered_text
    assert pack.budget_report.drop_reasons["scoped-instruction:src/AGENTS.md"] == "section_budget_exceeded"

    enough_budget = Settings.load(tmp_path)
    enough_budget.global_dir = tmp_path / ".pp-agent"
    enough_budget.context_pipeline.section_budgets = {"project_context": 1000}
    full_pack = build_runtime_context_pack(
        state=AgentState(system_prompt="system"),
        messages=[_message("system", "system"), _message("user", "hello")],
        settings=enough_budget,
        session_id="s1",
        scoped_instruction_items=scoped_items,
    )
    item_ids = [item.id for item in full_pack.project_context if item.metadata.get("scoped_instruction")]
    assert item_ids == ["scoped-instruction:src/AGENTS.md", "scoped-instruction:src/pkg/AGENTS.md"]


def test_runtime_bridge_scoped_instruction_does_not_reread_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("scoped context integration must not reread scoped instruction sources")

    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    scoped_items = scoped_instruction_records_to_context_items(
        [_scoped_record("src/AGENTS.md", "Already active.", scope_root="src", digest="d1")]
    )
    monkeypatch.setattr(Path, "open", fail)
    monkeypatch.setattr(Path, "read_text", fail)
    monkeypatch.setattr(Path, "read_bytes", fail)

    pack = build_runtime_context_pack(
        state=AgentState(system_prompt="system"),
        messages=[_message("system", "system"), _message("user", "hello")],
        settings=settings,
        session_id="s1",
        scoped_instruction_items=scoped_items,
    )

    assert any(item.id == "scoped-instruction:src/AGENTS.md" for item in pack.project_context)


def test_runtime_bridge_root_and_scoped_instruction_ownership(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    root_sentinel = "ROOT_OWNED_BY_MISSION_05"
    scoped_sentinel = "SCOPED_OWNED_BY_MISSION_06"
    (tmp_path / "AGENTS.md").write_text(root_sentinel, encoding="utf-8")
    scoped_items = scoped_instruction_records_to_context_items(
        [_scoped_record("src/AGENTS.md", scoped_sentinel, scope_root="src", digest="d1")]
    )

    pack = build_runtime_context_pack(
        state=AgentState(system_prompt="system"),
        messages=[_message("system", "system"), _message("user", "hello")],
        settings=settings,
        session_id="s1",
        scoped_instruction_items=scoped_items,
    )
    rendered_text = "\n".join(part.text for message in pack.final_messages for part in message.content if isinstance(part, TextPart))

    assert rendered_text.count(root_sentinel) == 1
    assert rendered_text.count(scoped_sentinel) == 1
    assert rendered_text.index(root_sentinel) < rendered_text.index(scoped_sentinel)


def test_runtime_bridge_different_repository_instruction_does_not_suppress_manifest_excerpt(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".pp-agent"
    manifest_sentinel = "DIFFERENT_MANIFEST_PROJECT_INSTRUCTION_SENTINEL"
    summary_sentinel = "DIFFERENT_SUMMARY_PROJECT_INSTRUCTION_SENTINEL"
    (tmp_path / "AGENTS.md").write_text(manifest_sentinel, encoding="utf-8")
    summary = RepositorySummary(
        workspace_name="demo",
        sections=[
            RepositorySummarySection(
                "project_instruction:AGENTS.md",
                "Project instruction: AGENTS.md",
                "project_instruction",
                summary_sentinel,
                ["agents"],
            )
        ],
        sources=[RepositorySummarySource("agents", "project_instruction", path="AGENTS.md")],
    )

    pack = build_runtime_context_pack(
        state=AgentState(system_prompt="system"),
        messages=[_message("system", "system"), _message("user", "hello")],
        settings=settings,
        session_id="s1",
        repository_summary=summary,
    )
    rendered_text = "\n".join(part.text for message in pack.final_messages for part in message.content if isinstance(part, TextPart))

    assert rendered_text.count(manifest_sentinel) == 1
    assert rendered_text.count(summary_sentinel) == 1


def test_project_context_uses_agents_canonical_claude_fallback(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("agents rules", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("claude rules", encoding="utf-8")

    agents_context = build_project_context(tmp_path)

    assert agents_context.manifest_files == ["AGENTS.md"]
    assert "agents rules" in agents_context.summary_text
    assert "claude rules" not in agents_context.summary_text

    (tmp_path / "AGENTS.md").unlink()
    claude_context = build_project_context(tmp_path)

    assert claude_context.manifest_files == ["CLAUDE.md"]
    assert "claude rules" in claude_context.summary_text
