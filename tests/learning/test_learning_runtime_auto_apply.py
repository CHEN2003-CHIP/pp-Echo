from pathlib import Path

from pp_agent.domain import ChatMessage
from pp_agent.learning.models import LearningCandidate, LearningSettings
from pp_agent.learning.runtime import LearningRuntime
from pp_agent.learning.store import LearningStore


class FakeExtractor:
    def __init__(self, candidates: list[LearningCandidate]) -> None:
        self.candidates = candidates

    def extract(self, *, session_id: str, turn_id: str, messages: list[ChatMessage]) -> list[LearningCandidate]:
        return self.candidates


class FailingWriter:
    def auto_apply(self, _candidates):
        raise RuntimeError("write failed")


def test_learning_runtime_auto_applies_extracted_workspace_bootstrap_memory(tmp_path: Path) -> None:
    store = LearningStore(tmp_path / ".pp-agent" / "learning")
    candidate = LearningCandidate(
        id="learn-1",
        kind="project_convention",
        title="Use pytest",
        content="Repo prefers pytest.",
        suggested_target="workspace_bootstrap",
    )
    runtime = LearningRuntime(
        workspace=tmp_path,
        llm_client=None,
        settings=LearningSettings(detailed_memory_sync_index_after_write=False),
        store=store,
        extractor=FakeExtractor([candidate]),
    )

    runtime.on_turn_persisted(session_id="s", turn_id="t", new_messages=[])

    assert store.get("learn-1").status == "applied"
    assert "Repo prefers pytest." in (tmp_path / "MEMORY.md").read_text(encoding="utf-8")


def test_learning_runtime_auto_applies_extracted_detailed_memory(tmp_path: Path) -> None:
    store = LearningStore(tmp_path / ".pp-agent" / "learning")
    candidate = LearningCandidate(
        id="learn-1",
        kind="lesson",
        title="Protected path bug",
        content="Fixed bug where protected path reads were denied.",
        suggested_target="detailed",
    )
    runtime = LearningRuntime(
        workspace=tmp_path,
        llm_client=None,
        settings=LearningSettings(detailed_memory_sync_index_after_write=False),
        store=store,
        extractor=FakeExtractor([candidate]),
    )

    runtime.on_turn_persisted(session_id="s", turn_id="t", new_messages=[])

    assert store.get("learn-1").status == "applied"
    assert "Protected path bug" in (tmp_path / "memory" / "bugs.md").read_text(encoding="utf-8")


def test_learning_runtime_auto_applies_extracted_journal(tmp_path: Path) -> None:
    store = LearningStore(tmp_path / ".pp-agent" / "learning")
    candidate = LearningCandidate(
        id="learn-1",
        kind="lesson",
        title="Smoke passed",
        content="2026-05-16 web smoke verification passed.",
        suggested_target="journal",
    )
    runtime = LearningRuntime(
        workspace=tmp_path,
        llm_client=None,
        settings=LearningSettings(detailed_memory_sync_index_after_write=False),
        store=store,
        extractor=FakeExtractor([candidate]),
    )

    runtime.on_turn_persisted(session_id="s", turn_id="t", new_messages=[])

    assert store.get("learn-1").status == "applied"
    daily_files = list((tmp_path / "memory" / "daily").glob("*.md"))
    assert len(daily_files) == 1
    assert "web smoke verification passed" in daily_files[0].read_text(encoding="utf-8")


def test_learning_runtime_auto_write_failure_does_not_abort(tmp_path: Path) -> None:
    store = LearningStore(tmp_path / ".pp-agent" / "learning")
    candidate = LearningCandidate(id="learn-1", title="Remember", content="Remember this.")
    runtime = LearningRuntime(
        workspace=tmp_path,
        llm_client=None,
        settings=LearningSettings(),
        store=store,
        extractor=FakeExtractor([candidate]),
    )
    runtime.file_memory_writer = FailingWriter()

    result = runtime.on_turn_persisted(session_id="s", turn_id="t", new_messages=[])

    assert result == [candidate]
    assert store.get("learn-1").status == "pending"
