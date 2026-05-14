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


def test_learning_runtime_auto_applies_extracted_bootstrap_memory(tmp_path: Path) -> None:
    store = LearningStore(tmp_path / ".pp-agent" / "learning")
    candidate = LearningCandidate(
        id="learn-1",
        kind="user_preference",
        title="Use pytest",
        content="User prefers pytest.",
        suggested_target="bootstrap_memory",
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
    assert "User prefers pytest." in (tmp_path / "MEMORY.md").read_text(encoding="utf-8")


def test_learning_runtime_auto_applies_extracted_detailed_memory(tmp_path: Path) -> None:
    store = LearningStore(tmp_path / ".pp-agent" / "learning")
    candidate = LearningCandidate(
        id="learn-1",
        kind="lesson",
        title="Protected path bug",
        content="Fixed bug where protected path reads were denied.",
        suggested_target="detailed_memory",
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
