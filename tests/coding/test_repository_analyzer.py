from __future__ import annotations

from pathlib import Path

from pp_agent.coding import RepositoryAnalysis, analyze_repository
from pp_agent.context import build_project_context
from pp_agent.observability import repository_analysis_to_block, repository_analysis_to_timeline_step, timeline_to_jsonable


def test_repository_analysis_detects_workspace_structure(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package.json").write_text('{"name":"web"}', encoding="utf-8")
    (tmp_path / "src" / "pp_agent" / "runtime").mkdir(parents=True)
    (tmp_path / "tests" / "runtime").mkdir(parents=True)
    (tmp_path / "docs").mkdir()

    analysis = analyze_repository(tmp_path, build_project_context(tmp_path))

    assert isinstance(analysis, RepositoryAnalysis)
    assert analysis.project_type == "Python package with Web frontend"
    assert "src/pp_agent/runtime" in analysis.module_map["runtime"]
    assert "tests/runtime" in analysis.test_roots
    assert "docs" in analysis.doc_roots
    assert "web" in analysis.frontend_roots
    assert "src/pp_agent" in analysis.backend_roots
    assert "pyproject.toml" in analysis.config_files
    assert "web/package.json" in analysis.config_files
    assert "Repository Analysis:" in analysis.summary_text


def test_repository_analysis_to_timeline_step_and_block(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    analysis = analyze_repository(tmp_path)
    step = repository_analysis_to_timeline_step(analysis)
    block = repository_analysis_to_block(analysis)

    step_payload = timeline_to_jsonable(step)
    block_payload = timeline_to_jsonable(block)

    assert step_payload["type"] == "repository_analysis"
    assert block_payload["type"] == "repository_analysis"
    assert block_payload["title"] == "Repository analysis"


def test_repository_analysis_summary_is_stable(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    first = analyze_repository(tmp_path)
    second = analyze_repository(tmp_path)

    assert first.summary_text == second.summary_text
