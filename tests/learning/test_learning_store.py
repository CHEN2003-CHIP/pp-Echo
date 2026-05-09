from pathlib import Path

from pp_agent.learning import LearningCurator, LearningStore
from pp_agent.learning.models import LearningCandidate, LearningSettings


def test_learning_store_appends_lists_and_updates_candidates(tmp_path: Path) -> None:
    store = LearningStore(tmp_path / ".pp-agent" / "learning")
    candidate = LearningCandidate(title="Remember pytest", content="Run focused tests first.")

    store.append_candidates([candidate])

    assert store.get(candidate.id) == candidate
    assert [item.id for item in store.list_candidates(status="pending")] == [candidate.id]

    store.update(candidate.mark_rejected())

    assert store.get(candidate.id).status == "rejected"
    assert store.summary().rejected_count == 1


def test_learning_store_skips_bad_jsonl_lines(tmp_path: Path) -> None:
    store = LearningStore(tmp_path / ".pp-agent" / "learning")
    store.root.mkdir(parents=True)
    store.candidates_path.write_text('{"id":"broken"\n', encoding="utf-8")

    assert store.list_candidates() == []


def test_learning_curator_writes_memory_and_skill_shapes(tmp_path: Path) -> None:
    candidate = LearningCandidate(
        id="abc123",
        kind="workflow",
        title="Focused pytest workflow",
        content="Run focused pytest files after runtime changes.",
        evidence="User asked for low-risk changes.",
        source_session_id="session-1",
        source_turn_id="turn-1",
    )
    curator = LearningCurator(workspace=tmp_path, settings=LearningSettings())

    memory_entry = curator.memory_entry(candidate)
    skill_doc = curator.skill_document(candidate, name="focused-pytest-workflow")

    assert "Focused pytest workflow" in memory_entry
    assert "session=session-1" in memory_entry
    assert "name: focused-pytest-workflow" in skill_doc
    assert "## Procedure" in skill_doc
