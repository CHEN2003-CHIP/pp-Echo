from __future__ import annotations

from pathlib import Path

from pp_agent.context import build_project_context
from pp_agent.context.project import ProjectManifest
from pp_agent.observability import manifest_to_block, manifest_to_timeline_step, project_context_to_block, project_context_to_timeline_step, timeline_to_jsonable


def test_project_context_detects_python_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    context = build_project_context(tmp_path)

    assert "Python" in context.detected_languages


def test_project_context_detects_web_project(tmp_path: Path) -> None:
    web = tmp_path / "web"
    web.mkdir()
    (web / "package.json").write_text('{"name":"web"}', encoding="utf-8")

    context = build_project_context(tmp_path)

    assert "Web frontend" in context.detected_frameworks


def test_project_context_detects_docs_and_readme(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")

    context = build_project_context(tmp_path)

    assert "docs" in context.important_paths
    assert "README.md" in context.important_paths


def test_project_context_loads_pp_echo_manifest_first(tmp_path: Path) -> None:
    (tmp_path / "PP_ECHO.md").write_text("first\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("second\n", encoding="utf-8")

    context = build_project_context(tmp_path)

    assert context.manifest_files[0] == "PP_ECHO.md"
    assert "truncated=false" in context.summary_text


def test_project_context_manifest_precedence(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("agent rules\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("claude rules\n", encoding="utf-8")

    context = build_project_context(tmp_path)

    assert context.manifest_files == ["AGENTS.md", "CLAUDE.md"]


def test_project_context_truncates_large_manifest(tmp_path: Path) -> None:
    (tmp_path / "PP_ECHO.md").write_text("x" * 40000, encoding="utf-8")

    context = build_project_context(tmp_path)

    assert "truncated=true" in context.summary_text
    assert len(context.summary_text) < 5000


def test_project_context_skips_protected_paths(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    context = build_project_context(tmp_path)

    assert all("SECRET" not in warning for warning in context.warnings)


def test_project_context_does_not_read_env(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    context = build_project_context(tmp_path)

    assert context.manifest_files == []


def test_project_context_summary_is_stable(tmp_path: Path) -> None:
    (tmp_path / "PP_ECHO.md").write_text("alpha\n", encoding="utf-8")

    first = build_project_context(tmp_path)
    second = build_project_context(tmp_path)

    assert first.summary_text == second.summary_text


def test_project_context_to_timeline_step(tmp_path: Path) -> None:
    context = build_project_context(tmp_path)

    step = project_context_to_timeline_step(context)

    payload = timeline_to_jsonable(step)
    assert payload["type"] == "project_context"
    assert payload["status"] == "succeeded"


def test_project_context_to_timeline_block(tmp_path: Path) -> None:
    context = build_project_context(tmp_path)

    block = project_context_to_block(context)

    payload = timeline_to_jsonable(block)
    assert payload["type"] == "project_context"
    assert payload["status"] == "succeeded"


def test_manifest_to_timeline_step(tmp_path: Path) -> None:
    manifest = ProjectManifest(path=str(tmp_path / "AGENTS.md"), kind="agents", content_excerpt="hello", bytes_loaded=5, truncated=False)

    step = manifest_to_timeline_step(manifest)

    payload = timeline_to_jsonable(step)
    assert payload["type"] == "manifest_loaded"
    assert payload["title"] == "Manifest loaded: AGENTS.md"


def test_manifest_to_timeline_block(tmp_path: Path) -> None:
    manifest = ProjectManifest(path=str(tmp_path / "AGENTS.md"), kind="agents", content_excerpt="hello", bytes_loaded=5, truncated=False)

    block = manifest_to_block(manifest)

    payload = timeline_to_jsonable(block)
    assert payload["type"] == "manifest_loaded"
    assert payload["title"] == "Manifest loaded: AGENTS.md"


def test_project_context_public_models_have_docstrings() -> None:
    assert build_project_context.__doc__
    assert ProjectManifest.__doc__


def test_project_context_public_helpers_have_docstrings() -> None:
    assert project_context_to_timeline_step.__doc__
    assert project_context_to_block.__doc__
    assert manifest_to_timeline_step.__doc__
    assert manifest_to_block.__doc__
