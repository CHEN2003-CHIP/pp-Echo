from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pp_agent.context.item import ContextItem
from pp_agent.context.project import ProjectContext, build_project_context
from pp_agent.context.source_ref import SourceRef


@dataclass
class RepositoryAnalysis:
    """A shallow structural map of a repository for the default coding workspace agent."""

    workspace_path: str
    workspace_name: str
    project_type: str
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    source_roots: list[str] = field(default_factory=list)
    test_roots: list[str] = field(default_factory=list)
    doc_roots: list[str] = field(default_factory=list)
    frontend_roots: list[str] = field(default_factory=list)
    backend_roots: list[str] = field(default_factory=list)
    config_files: list[str] = field(default_factory=list)
    ci_files: list[str] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    module_map: dict[str, list[str]] = field(default_factory=dict)
    likely_test_commands: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary_text: str = ""


def analyze_repository(workspace: Path, project_context: ProjectContext | None = None) -> RepositoryAnalysis:
    """Build a shallow repository analysis for the workspace."""

    workspace = workspace.resolve()
    context = project_context or build_project_context(workspace)
    frontend_roots = ["web"] if (workspace / "web").exists() else []
    backend_roots = ["src/pp_agent"] if (workspace / "src" / "pp_agent").exists() else []
    source_roots = [*backend_roots, *frontend_roots]
    test_roots = [path for path in ("tests/runtime", "tests/tools", "tests/observability", "tests") if (workspace / path).exists()]
    doc_roots = ["docs"] if (workspace / "docs").exists() else []
    config_files = [path for path in ("pyproject.toml", "package.json", "web/package.json") if (workspace / path).exists()]
    ci_files = [str(path.relative_to(workspace)).replace("\\", "/") for path in (workspace / ".github" / "workflows").glob("*.yml")] if (workspace / ".github" / "workflows").exists() else []
    entry_points = [path for path in context.important_paths if path in {"src", "web"}]
    module_map = {
        "runtime": ["src/pp_agent/runtime"] if (workspace / "src" / "pp_agent" / "runtime").exists() else [],
        "tools": ["src/pp_agent/tools"] if (workspace / "src" / "pp_agent" / "tools").exists() else [],
        "observability": ["src/pp_agent/observability"] if (workspace / "src" / "pp_agent" / "observability").exists() else [],
        "sandbox": ["src/pp_agent/sandbox"] if (workspace / "src" / "pp_agent" / "sandbox").exists() else [],
        "config": ["src/pp_agent/config"] if (workspace / "src" / "pp_agent" / "config").exists() else [],
        "storage": ["src/pp_agent/storage"] if (workspace / "src" / "pp_agent" / "storage").exists() else [],
        "cli": ["src/pp_agent/cli"] if (workspace / "src" / "pp_agent" / "cli").exists() else [],
        "web": list(frontend_roots),
        "tests": list(test_roots),
        "docs": list(doc_roots),
    }
    project_type = "Python package with Web frontend" if frontend_roots and "Python" in context.detected_languages else "Python package"
    likely_test_commands = list(context.likely_test_commands)
    summary_text = _render_summary_text(project_type, context, source_roots, test_roots, doc_roots, config_files, ci_files, entry_points)
    return RepositoryAnalysis(
        workspace_path=str(workspace),
        workspace_name=workspace.name or workspace.as_posix(),
        project_type=project_type,
        languages=list(context.detected_languages),
        frameworks=list(context.detected_frameworks),
        source_roots=source_roots,
        test_roots=test_roots,
        doc_roots=doc_roots,
        frontend_roots=frontend_roots,
        backend_roots=backend_roots,
        config_files=config_files,
        ci_files=ci_files,
        entry_points=entry_points,
        module_map=module_map,
        likely_test_commands=likely_test_commands,
        warnings=list(context.warnings),
        summary_text=summary_text,
    )


def repository_analysis_to_context_item(analysis: RepositoryAnalysis, *, id: str = "repository-analysis") -> ContextItem:
    """Convert repository analysis into a project-context item for the default workspace pack."""

    return ContextItem(
        id=id,
        type="project_context",
        title="Repository analysis",
        content=analysis.summary_text,
        source_ref=SourceRef(
            source_type="project_context",
            source_id=analysis.workspace_name,
            metadata=_analysis_metadata(analysis),
        ),
        priority=59,
        metadata={
            "context_section": "project_context",
            "repository_analysis": _analysis_metadata(analysis),
        },
    )


def _render_summary_text(
    project_type: str,
    context: ProjectContext,
    source_roots: list[str],
    test_roots: list[str],
    doc_roots: list[str],
    config_files: list[str],
    ci_files: list[str],
    entry_points: list[str],
) -> str:
    lines = [
        "Repository Analysis:",
        f"Type: {project_type}",
        f"Languages: {', '.join(context.detected_languages) if context.detected_languages else 'Unknown'}",
    ]
    if source_roots:
        lines.append(f"Source roots: {', '.join(source_roots)}")
    if test_roots:
        lines.append(f"Tests: {', '.join(test_roots)}")
    if doc_roots:
        lines.append(f"Docs: {', '.join(doc_roots)}")
    if ci_files:
        lines.append(f"CI: {', '.join(ci_files)}")
    if config_files:
        lines.append(f"Config: {', '.join(config_files)}")
    if entry_points:
        lines.append(f"Entry points: {', '.join(entry_points)}")
    if context.likely_test_commands:
        lines.append("Likely validation:")
        lines.extend(f"- {command}" for command in context.likely_test_commands[:4])
    return "\n".join(lines).strip()


def _analysis_metadata(analysis: RepositoryAnalysis) -> dict[str, object]:
    return {
        "workspace_path": analysis.workspace_path,
        "workspace_name": analysis.workspace_name,
        "project_type": analysis.project_type,
        "languages": list(analysis.languages),
        "frameworks": list(analysis.frameworks),
        "source_roots": list(analysis.source_roots),
        "test_roots": list(analysis.test_roots),
        "doc_roots": list(analysis.doc_roots),
        "frontend_roots": list(analysis.frontend_roots),
        "backend_roots": list(analysis.backend_roots),
        "config_files": list(analysis.config_files),
        "ci_files": list(analysis.ci_files),
        "entry_points": list(analysis.entry_points),
        "module_map": {key: list(value) for key, value in analysis.module_map.items()},
        "likely_test_commands": list(analysis.likely_test_commands),
        "warnings": list(analysis.warnings),
    }
