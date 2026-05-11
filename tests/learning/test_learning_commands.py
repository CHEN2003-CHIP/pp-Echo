from pathlib import Path

from pp_agent.cli.commands.learning import apply_learning_candidate, learning_review_payload, reject_learning_candidate
from pp_agent.learning import LearningStore
from pp_agent.learning.models import LearningCandidate
from pp_agent.storage.settings import Settings


class DummyAgent:
    pass


def test_learning_review_and_reject_command_helpers(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    store = LearningStore(settings.project_dir / "learning")
    candidate = LearningCandidate(id="learn-1", title="Run tests", content="Run focused tests.")
    store.append_candidates([candidate])

    assert learning_review_payload(tmp_path)[0]["id"] == "learn-1"

    assert reject_learning_candidate(tmp_path, "learn-1") is True
    assert learning_review_payload(tmp_path) == []


def test_apply_learning_candidate_to_memory(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    store = LearningStore(settings.project_dir / "learning")
    candidate = LearningCandidate(id="learn-1", title="Run tests", content="Run focused tests.")
    store.append_candidates([candidate])

    payload = apply_learning_candidate(DummyAgent(), tmp_path, "learn-1", "memory")

    assert payload["ok"] is True
    assert "Run focused tests" in store.read_project_memory()
    assert store.get("learn-1").status == "applied"


def test_apply_learning_candidate_to_skill(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    store = LearningStore(settings.project_dir / "learning")
    candidate = LearningCandidate(id="learn-1", title="Focused test skill", content="Run focused tests.")
    store.append_candidates([candidate])

    payload = apply_learning_candidate(DummyAgent(), tmp_path, "learn-1", "skill")

    assert payload["ok"] is True
    skill_path = Path(payload["path"])
    assert skill_path.exists()
    assert "name: focused-test-skill" in skill_path.read_text(encoding="utf-8")
