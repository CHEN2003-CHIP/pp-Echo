from __future__ import annotations

from pathlib import Path

from pp_agent.learning.file_memory_writer import DETAIL_BEGIN, FileMemoryWriter
from pp_agent.learning.models import LearningCandidate, LearningSettings
from pp_agent.learning.store import LearningStore


def _writer(tmp_path: Path, *, settings: LearningSettings | None = None) -> tuple[FileMemoryWriter, LearningStore]:
    store = LearningStore(tmp_path / ".pp-agent" / "learning")
    writer = FileMemoryWriter(workspace=tmp_path, settings=settings or LearningSettings(detailed_memory_sync_index_after_write=False), store=store)
    return writer, store


def test_file_memory_writer_auto_applies_workspace_bootstrap_memory(tmp_path: Path) -> None:
    writer, store = _writer(tmp_path)
    candidate = LearningCandidate(
        id="learn-1",
        kind="project_convention",
        title="Run focused tests",
        content="Repo changes should start with focused pytest runs.",
        suggested_target="workspace_bootstrap",
    )
    store.append_candidates([candidate])

    result = writer.auto_apply([candidate])[0]

    assert result.action == "workspace_bootstrap"
    assert store.get("learn-1").status == "applied"
    assert "focused pytest runs" in (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "focused pytest runs" in store.read_project_memory()


def test_file_memory_writer_auto_applies_global_bootstrap_memory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / ".global"))
    writer, store = _writer(tmp_path)
    candidate = LearningCandidate(
        id="learn-1",
        kind="user_preference",
        title="Use pytest",
        content="User prefers focused pytest runs by default.",
        suggested_target="global_bootstrap",
    )
    store.append_candidates([candidate])

    result = writer.auto_apply([candidate])[0]

    assert result.action == "global_bootstrap"
    assert store.get("learn-1").status == "applied"
    assert "focused pytest runs by default" in (tmp_path / ".global" / "MEMORY.md").read_text(encoding="utf-8")


def test_file_memory_writer_auto_applies_detailed_memory_and_updates_navigation(tmp_path: Path) -> None:
    writer, store = _writer(tmp_path)
    candidate = LearningCandidate(
        id="learn-1",
        kind="lesson",
        title="Chroma collection mismatch bug",
        content="Fixed bug where embedding model changes caused a Chroma collection mismatch.",
        suggested_target="detailed",
    )
    store.append_candidates([candidate])

    result = writer.auto_apply([candidate])[0]
    bugs = tmp_path / "memory" / "bugs.md"
    root_memory = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")

    assert result.action == "detailed_memory"
    assert result.path == bugs
    assert DETAIL_BEGIN in bugs.read_text(encoding="utf-8")
    assert "Chroma collection mismatch bug" in bugs.read_text(encoding="utf-8")
    assert "`memory/bugs.md` - Bugs" in root_memory
    assert store.get("learn-1").status == "applied"


def test_file_memory_writer_preserves_manual_detailed_memory_content(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    bugs = memory_dir / "bugs.md"
    bugs.write_text("# Manual Bugs\n\nKeep this manual note.\n", encoding="utf-8")
    writer, store = _writer(tmp_path)
    candidate = LearningCandidate(
        id="learn-1",
        title="Runtime failure",
        content="Fixed runtime failure after tool execution.",
        suggested_target="detailed",
    )
    store.append_candidates([candidate])

    writer.auto_apply([candidate])
    content = bugs.read_text(encoding="utf-8")

    assert "Keep this manual note." in content
    assert "Runtime failure" in content
    assert content.count(DETAIL_BEGIN) == 1


def test_file_memory_writer_keeps_low_confidence_and_skill_pending(tmp_path: Path) -> None:
    writer, store = _writer(tmp_path, settings=LearningSettings(auto_apply_min_confidence="high", detailed_memory_sync_index_after_write=False))
    low = LearningCandidate(id="low", title="Low", content="Maybe remember this.", confidence="medium")
    skill = LearningCandidate(id="skill", kind="skill_candidate", title="Skill", content="Make a skill.", suggested_target="skill", confidence="high")
    store.append_candidates([low, skill])

    results = writer.auto_apply([low, skill])

    assert [result.action for result in results] == ["pending_low_confidence", "pending_skill"]
    assert store.get("low").status == "pending"
    assert store.get("skill").status == "pending"
    assert not (tmp_path / "MEMORY.md").exists()


def test_file_memory_writer_classifies_legacy_memory_target_to_detail(tmp_path: Path) -> None:
    writer, store = _writer(tmp_path)
    candidate = LearningCandidate(
        id="learn-1",
        kind="lesson",
        title="Debug timeout failure",
        content="The timeout failure was fixed by using python -B -m pytest.",
        suggested_target="memory",
    )
    store.append_candidates([candidate])

    writer.auto_apply([candidate])

    assert (tmp_path / "memory" / "bugs.md").exists()


def test_file_memory_writer_auto_writes_journal_without_promotion(tmp_path: Path) -> None:
    writer, store = _writer(tmp_path)
    candidate = LearningCandidate(
        id="learn-1",
        kind="lesson",
        title="Web smoke passed",
        content="2026-05-16 web smoke verification passed for the approval flow.",
        suggested_target="journal",
    )
    store.append_candidates([candidate])

    result = writer.auto_apply([candidate])[0]

    assert result.action == "journal"
    assert result.path == tmp_path / "memory" / "daily" / "2026-05-16.md"
    assert "web smoke verification passed" in result.path.read_text(encoding="utf-8")
    assert store.get("learn-1").status == "applied"


def test_file_memory_writer_keeps_one_off_bootstrap_candidate_pending(tmp_path: Path) -> None:
    writer, store = _writer(tmp_path)
    candidate = LearningCandidate(
        id="learn-1",
        kind="project_convention",
        title="Worktree smoke artifact",
        content="Remember docs/worktree-smoke-web.md from this temporary run.",
        suggested_target="workspace_bootstrap",
    )
    store.append_candidates([candidate])

    result = writer.auto_apply([candidate])[0]

    assert result.action == "pending_promotion"
    assert store.get("learn-1").status == "pending"
    assert not (tmp_path / "MEMORY.md").exists()


def test_file_memory_writer_syncs_file_memory_index_after_write(tmp_path: Path, monkeypatch) -> None:
    calls: list[Path] = []

    class FakeEngine:
        def sync(self):
            calls.append(tmp_path)

    def fake_build_engine(workspace: Path, *, settings):
        calls.append(workspace)
        return FakeEngine()

    monkeypatch.setattr("pp_agent.memory.file_memory_tools.build_file_memory_search_engine", fake_build_engine)
    writer, store = _writer(tmp_path, settings=LearningSettings(detailed_memory_sync_index_after_write=True))
    candidate = LearningCandidate(
        id="learn-1",
        kind="project_convention",
        title="Use pytest",
        content="Repo prefers pytest.",
        suggested_target="workspace_bootstrap",
    )
    store.append_candidates([candidate])

    writer.auto_apply([candidate])

    assert calls
