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
    assert payload["bootstrap_path"] == str(tmp_path / "MEMORY.md")
    assert "Run focused tests" in store.read_project_memory()
    assert "Run focused tests" in (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert store.get("learn-1").status == "applied"


def test_apply_learning_candidate_preserves_manual_memory_notes(tmp_path: Path) -> None:
    (tmp_path / "MEMORY.md").write_text("# Manual\n\nKeep this note.\n", encoding="utf-8")
    settings = Settings.load(tmp_path)
    store = LearningStore(settings.project_dir / "learning")
    candidate = LearningCandidate(id="learn-1", title="Run tests", content="Run focused tests.")
    store.append_candidates([candidate])

    apply_learning_candidate(DummyAgent(), tmp_path, "learn-1", "memory")
    content = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")

    assert "Keep this note." in content
    assert "Run focused tests" in content


def test_apply_learning_candidate_compacts_project_memory_when_over_limit(tmp_path: Path) -> None:
    project_dir = tmp_path / ".pp-agent"
    project_dir.mkdir(parents=True)
    (project_dir / "config.json").write_text(
        '{"learning":{"project_memory_char_limit":600,"llm_extractor_enable":false}}',
        encoding="utf-8",
    )
    settings = Settings.load(tmp_path)
    store = LearningStore(settings.project_dir / "learning")
    store.append_project_memory("\n".join(f"- old note {index} " + ("x" * 50) for index in range(30)))
    candidate = LearningCandidate(id="learn-1", title="Newest", content="Keep newest focused test preference.")
    store.append_candidates([candidate])

    apply_learning_candidate(DummyAgent(), tmp_path, "learn-1", "memory")

    assert len(store.read_project_memory()) <= settings.learning.project_memory_char_limit
    assert "Keep newest focused test preference" in (tmp_path / "MEMORY.md").read_text(encoding="utf-8")


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
