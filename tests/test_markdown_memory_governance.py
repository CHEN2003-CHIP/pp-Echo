from __future__ import annotations

from pathlib import Path

import pytest

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.learning.context import ProjectMemoryContextHook
from pp_agent.learning.models import LearningSettings
from pp_agent.memory.core_renderer import CoreMemoryContextHook, workspace_id_for_path
from pp_agent.memory.core_service import CoreMemoryService
from pp_agent.memory.core_store import CoreMemoryStore
from pp_agent.memory.core_tools import MemoryApproveTool
from pp_agent.memory.core_types import CoreMemoryCandidate
from pp_agent.memory.file_memory_tools import memory_search_executor
from pp_agent.memory.markdown_router import route_core_memory_to_markdown
from pp_agent.memory.markdown_writer import MarkdownMemoryApplyError, apply_markdown_patch, build_markdown_patch
from pp_agent.storage.settings import Settings


def _settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / ".global"))
    return Settings.load(tmp_path)


def _service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CoreMemoryService:
    settings = _settings(tmp_path, monkeypatch)
    return CoreMemoryService(store=CoreMemoryStore(settings.core_memory_db_path()), settings=settings, workspace=tmp_path.resolve())


def test_core_memory_approve_applies_to_global_memory_md_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path, monkeypatch)
    result = service.propose(
        CoreMemoryCandidate(scope="global", section="user_profile", type="preference", content="Prefer concise engineering answers."),
        actor="test",
    )

    approved = service.approve(result.memory.id, actor="test")

    content = (service.settings.global_dir / "MEMORY.md").read_text(encoding="utf-8")
    assert approved.immediate_effect is True
    assert "Prefer concise engineering answers." in content
    assert f"pp-memory:id={result.memory.id}" in content
    assert approved.markdown["target"]["path"] == "global/MEMORY.md"


def test_core_memory_approve_applies_to_workspace_memory_md_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path, monkeypatch)
    result = service.propose(
        CoreMemoryCandidate(
            scope="workspace",
            workspace_id=service.workspace_id,
            section="project_profile",
            type="workflow",
            content="Run focused pytest before runtime changes.",
        ),
        actor="test",
    )

    approved = service.approve(result.memory.id, actor="test")

    content = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "## Workflows" in content
    assert "Run focused pytest before runtime changes." in content
    assert approved.markdown["target"]["heading"] == "Workflows"


def test_approved_memory_immediate_next_transform_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path, monkeypatch)
    result = service.propose(
        CoreMemoryCandidate(
            scope="workspace",
            workspace_id=service.workspace_id,
            section="project_profile",
            type="project_fact",
            content="Project fact visible on the next turn.",
        )
    )
    service.approve(result.memory.id)
    hook = ProjectMemoryContextHook(workspace=tmp_path, settings=LearningSettings())
    messages = [ChatMessage(role="system", content=[TextPart(text="system")], timestamp=0)]

    transformed = hook.transform_context(None, messages)  # type: ignore[arg-type]

    assert "Project fact visible on the next turn." in transformed[1].content[0].text


def test_core_memory_prompt_injection_disabled_by_default(tmp_path: Path) -> None:
    store = CoreMemoryStore(tmp_path / "core-memory.db")
    memory = store.add_candidate(
        CoreMemoryCandidate(scope="workspace", workspace_id="workspace-a", content="Debug-only memory.", confidence=0.8),
        require_approval=False,
    ).memory
    hook = CoreMemoryContextHook(store=store, workspace_id="workspace-a")
    messages = [ChatMessage(role="system", content=[TextPart(text="system")], timestamp=0)]

    transformed = hook.transform_context(None, messages)  # type: ignore[arg-type]

    assert memory.status == "active"
    assert transformed == messages


def test_markdown_patch_creates_heading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path, monkeypatch)
    memory = service.propose(CoreMemoryCandidate(scope="workspace", workspace_id=service.workspace_id, type="decision", content="Keep Markdown as memory fact source.")).memory

    patch = service.markdown_preview(memory.id)

    assert "## Decisions" in patch.after
    assert "Keep Markdown as memory fact source." in patch.after


def test_markdown_patch_uses_marker_and_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path, monkeypatch)
    memory = service.propose(CoreMemoryCandidate(scope="workspace", workspace_id=service.workspace_id, content="Use stable markers.")).memory
    service.approve(memory.id)
    service.markdown_apply(memory.id, actor="test")

    content = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")

    assert content.count(f"pp-memory:id={memory.id}") == 1


def test_markdown_apply_detects_external_edit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path, monkeypatch)
    memory = service.propose(CoreMemoryCandidate(scope="workspace", workspace_id=service.workspace_id, content="Detect external edits.")).memory
    patch = service.markdown_preview(memory.id)
    (tmp_path / "MEMORY.md").write_text("# Project Memory\n\nManual edit.\n", encoding="utf-8")

    with pytest.raises(MarkdownMemoryApplyError) as exc:
        apply_markdown_patch(patch, workspace=tmp_path, global_root=service.settings.global_dir, settings=service.settings)

    assert exc.value.code == "external_edit_detected"


def test_memory_search_finds_approved_markdown_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path, monkeypatch)
    memory = service.propose(
        CoreMemoryCandidate(scope="workspace", workspace_id=service.workspace_id, section="project_profile", type="workflow", content="Searchable approved markdown workflow.")
    ).memory
    service.approve(memory.id)

    result = memory_search_executor(tmp_path, {"query": "Searchable approved markdown workflow", "top_k": 3}, settings=service.settings)

    assert result.details["results"][0]["path"] == "MEMORY.md"


def test_memory_approve_tool_returns_immediate_effect_true(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path, monkeypatch)
    memory = service.propose(CoreMemoryCandidate(scope="workspace", workspace_id=service.workspace_id, content="Tool approved memory.")).memory
    tool = MemoryApproveTool(tmp_path, settings=service.settings)

    result = tool.execute({"memory_id": memory.id})

    assert result.details["immediate_effect"] is True
    assert "next model turn" in result.details["message"]


def test_memory_audit_records_markdown_apply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path, monkeypatch)
    memory = service.propose(CoreMemoryCandidate(scope="workspace", workspace_id=service.workspace_id, content="Audit markdown apply.")).memory

    service.approve(memory.id)
    actions = [record.action for record in service.audit(memory_id=memory.id)]

    assert "markdown_apply" in actions

