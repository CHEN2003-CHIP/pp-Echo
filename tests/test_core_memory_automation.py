from __future__ import annotations

from pathlib import Path

from pp_agent.memory.core_service import CoreMemoryService, service_for_workspace
from pp_agent.memory.core_store import CoreMemoryStore
from pp_agent.memory.core_types import CoreMemoryCandidate
from pp_agent.storage.settings import Settings


def _service(tmp_path: Path) -> CoreMemoryService:
    settings = Settings.load(tmp_path)
    return CoreMemoryService(store=CoreMemoryStore(settings.core_memory_db_path()), settings=settings, workspace=tmp_path.resolve())


def _candidate(content: str, *, workspace_id: str, confidence: float = 0.8) -> CoreMemoryCandidate:
    return CoreMemoryCandidate(
        scope="workspace",
        workspace_id=workspace_id,
        section="project_profile",
        type="workflow",
        content=content,
        confidence=confidence,
    )


def test_merge_apply_creates_pending_replacement_and_approval_archives_sources(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.settings.memory.core_memory.require_approval = False
    service.settings.memory.core_memory.dedupe.enabled = False
    first = service.propose(_candidate("Use pytest for focused tests.", workspace_id=service.workspace_id)).memory
    second = service.propose(_candidate("Use pytest for focused tests.", workspace_id=service.workspace_id)).memory

    applied = service.merge_apply(actor="test")

    generated = applied["generated"]
    assert len(generated) == 1
    replacement_id = generated[0]["memory"]["id"]
    replacement = service.store.get(replacement_id)
    assert replacement is not None
    assert replacement.status == "pending"
    assert replacement.metadata["auto_archive_on_approve_ids"] == [second.id, first.id]

    service.approve(replacement.id, actor="reviewer")

    assert service.store.get(first.id).status == "archived"  # type: ignore[union-attr]
    assert service.store.get(second.id).status == "archived"  # type: ignore[union-attr]
    assert service.store.get(replacement.id).status == "active"  # type: ignore[union-attr]


def test_compact_apply_creates_pending_candidate_without_llm_by_default(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.settings.memory.core_memory.require_approval = False
    service.settings.memory.core_memory.budgets.project_profile_chars = 55
    service.settings.memory.core_memory.budgets.total_chars = 130
    service.propose(_candidate("Project convention one is intentionally verbose.", workspace_id=service.workspace_id, confidence=0.7))
    service.propose(_candidate("Project convention two is intentionally verbose.", workspace_id=service.workspace_id, confidence=0.7))
    service.propose(_candidate("Project convention three is intentionally verbose.", workspace_id=service.workspace_id, confidence=0.7))

    applied = service.compact_apply(actor="test")

    assert applied["applied"] is True
    assert applied["generated"]
    generated_memory = applied["generated"][0]["memory"]
    assert generated_memory["status"] == "pending"
    assert generated_memory["metadata"]["summary_method"] == "deterministic"


def test_llm_summary_config_falls_back_when_no_summarizer_is_registered(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.settings.memory.core_memory.require_approval = False
    service.settings.memory.core_memory.automation.use_llm_summary = True
    service.settings.memory.core_memory.budgets.project_profile_chars = 55
    service.propose(_candidate("Project convention one is intentionally verbose.", workspace_id=service.workspace_id, confidence=0.7))
    service.propose(_candidate("Project convention two is intentionally verbose.", workspace_id=service.workspace_id, confidence=0.7))

    applied = service.compact_apply(actor="test")

    assert applied["generated"][0]["memory"]["metadata"]["summary_method"] == "llm_unavailable_deterministic_fallback"


def test_local_provider_mirrors_writes_and_reports_status(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    service = service_for_workspace(tmp_path, settings)

    result = service.propose(_candidate("Provider mirrors this candidate.", workspace_id=service.workspace_id), actor="test")
    service.provider.sync_turn(session_id="s1", turn_id="turn-1", messages=[])

    status = service.provider.status()
    assert status["provider"] == "local"
    assert status["additive"] is True
    assert status["mirrored_write_count"] >= 1
    assert status["synced_turn_count"] == 1
    assert result.memory.id
