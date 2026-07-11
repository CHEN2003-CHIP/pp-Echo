from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pp_agent.context.item import ContextItem
from pp_agent.context.source_ref import SourceRef

MAX_MANIFEST_BYTES = 32 * 1024
PROJECT_MANIFEST_NAMES = ("AGENTS.md", "CLAUDE.md", "PP_ECHO.md")


@dataclass
class ProjectManifest:
    """A loaded project instruction manifest shown in the bootstrap timeline."""

    path: str
    kind: str
    content_excerpt: str
    bytes_loaded: int
    truncated: bool


@dataclass
class ProjectContext:
    """A compact project bootstrap summary for default coding workspaces."""

    workspace_path: str
    workspace_name: str
    detected_languages: list[str] = field(default_factory=list)
    detected_frameworks: list[str] = field(default_factory=list)
    important_paths: list[str] = field(default_factory=list)
    likely_test_commands: list[str] = field(default_factory=list)
    manifest_files: list[str] = field(default_factory=list)
    summary_text: str = ""
    warnings: list[str] = field(default_factory=list)


def build_project_context(workspace: Path, max_manifest_bytes: int = MAX_MANIFEST_BYTES) -> ProjectContext:
    """Inspect the workspace and build a small bootstrap summary."""

    workspace = workspace.resolve()
    warnings: list[str] = []
    manifests: list[ProjectManifest] = []
    if workspace.exists():
        manifests = _load_manifests(workspace, max_manifest_bytes=max_manifest_bytes, warnings=warnings)
    else:
        warnings.append("workspace_missing")

    detected_languages, detected_frameworks = _detect_workspace_characteristics(workspace)
    important_paths = _important_paths(workspace)
    likely_test_commands = _likely_test_commands(workspace, detected_languages, detected_frameworks)
    manifest_files = [Path(manifest.path).name for manifest in manifests]
    summary_text = _render_summary_text(
        workspace_name=workspace.name or workspace.as_posix(),
        detected_languages=detected_languages,
        detected_frameworks=detected_frameworks,
        important_paths=important_paths,
        likely_test_commands=likely_test_commands,
        manifests=manifests,
    )
    return ProjectContext(
        workspace_path=str(workspace),
        workspace_name=workspace.name or workspace.as_posix(),
        detected_languages=detected_languages,
        detected_frameworks=detected_frameworks,
        important_paths=important_paths,
        likely_test_commands=likely_test_commands,
        manifest_files=manifest_files,
        summary_text=summary_text,
        warnings=warnings,
    )


def project_context_to_timeline_step(context: ProjectContext, *, id: str = "project-context") -> ContextItem:
    """Convert project context into a context-pipeline item for the bootstrap section."""

    return ContextItem(
        id=id,
        type="project_context",
        title="Project context",
        content=context.summary_text,
        source_ref=SourceRef(source_type="project_context", source_id=context.workspace_name, metadata=_safe_context_metadata(context)),
        priority=60,
        metadata={"context_section": "project_context", "project_context": _safe_context_metadata(context)},
    )


def project_context_to_block(context: ProjectContext, *, id: str = "project-context") -> dict[str, Any]:
    """Convert project context into a frontend timeline block."""

    return {
        "id": id,
        "run_id": None,
        "type": "project_context",
        "status": "succeeded",
        "title": "Project context",
        "content": context.summary_text,
        "details": _safe_context_metadata(context),
        "children": [],
        "artifact_ids": list(context.manifest_files),
    }


def manifest_to_timeline_step(manifest: ProjectManifest, *, id: str | None = None, run_id: str | None = None) -> ContextItem:
    """Convert a loaded manifest preview into a context-pipeline item."""

    manifest_name = Path(manifest.path).name
    return ContextItem(
        id=id or f"manifest:{manifest_name}",
        type="project_context",
        title=f"Manifest loaded: {manifest_name}",
        content=manifest.content_excerpt,
        source_ref=SourceRef(source_type="project_map", source_id=manifest.kind, path=manifest.path, metadata={"truncated": manifest.truncated}),
        priority=55,
        metadata={"context_section": "project_context", "manifest": asdict(manifest), "run_id": run_id},
    )


def manifest_to_block(manifest: ProjectManifest, *, id: str | None = None, run_id: str | None = None) -> dict[str, Any]:
    """Convert a loaded manifest preview into a frontend timeline block."""

    manifest_name = Path(manifest.path).name
    return {
        "id": id or f"manifest:{manifest_name}",
        "run_id": run_id,
        "type": "manifest_loaded",
        "status": "succeeded",
        "title": f"Manifest loaded: {manifest_name}",
        "content": manifest.content_excerpt,
        "details": asdict(manifest),
        "children": [],
        "artifact_ids": [manifest.path],
    }


def _load_manifests(workspace: Path, *, max_manifest_bytes: int, warnings: list[str]) -> list[ProjectManifest]:
    manifests: list[ProjectManifest] = []
    for name in PROJECT_MANIFEST_NAMES:
        path = workspace / name
        if not path.exists():
            continue
        if _is_protected_path(path):
            warnings.append(f"protected_manifest_skipped:{name}")
            continue
        try:
            raw = path.read_bytes()
        except OSError as exc:
            warnings.append(f"manifest_read_failed:{name}:{exc.__class__.__name__}")
            continue
        truncated = len(raw) > max_manifest_bytes
        excerpt = raw[:max_manifest_bytes].decode("utf-8", errors="replace")
        manifests.append(
            ProjectManifest(
                path=str(path),
                kind=_manifest_kind(name),
                content_excerpt=excerpt,
                bytes_loaded=min(len(raw), max_manifest_bytes),
                truncated=truncated,
            )
        )
        break
    return manifests


def _detect_workspace_characteristics(workspace: Path) -> tuple[list[str], list[str]]:
    languages: list[str] = []
    frameworks: list[str] = []
    if (workspace / "pyproject.toml").exists() or (workspace / "requirements.txt").exists():
        languages.append("Python")
    if (workspace / "package.json").exists():
        languages.append("JavaScript/TypeScript")
    if (workspace / "web" / "package.json").exists():
        frameworks.append("Web frontend")
    return languages, frameworks


def _important_paths(workspace: Path) -> list[str]:
    paths: list[str] = []
    for name in ("src", "tests", "web", "docs", "README.md"):
        if (workspace / name).exists():
            paths.append(name)
    return paths


def _likely_test_commands(workspace: Path, languages: list[str], frameworks: list[str]) -> list[str]:
    commands: list[str] = []
    if "Python" in languages:
        commands.append("python -m pytest -q")
        if (workspace / "tests").exists():
            commands.append("python -m pytest tests -q")
    if (workspace / "package.json").exists():
        commands.append("npm test")
    if "Web frontend" in frameworks:
        commands.append("cd web && npm test")
    return commands


def _render_summary_text(
    *,
    workspace_name: str,
    detected_languages: list[str],
    detected_frameworks: list[str],
    important_paths: list[str],
    likely_test_commands: list[str],
    manifests: list[ProjectManifest],
) -> str:
    lines = [
        "Project Context:",
        f"- Workspace: {workspace_name}",
        f"- Languages: {', '.join(detected_languages) if detected_languages else 'Unknown'}",
    ]
    if detected_frameworks:
        lines.append(f"- Frameworks: {', '.join(detected_frameworks)}")
    if important_paths:
        lines.append(f"- Important paths: {', '.join(important_paths)}")
    if likely_test_commands:
        lines.append("- Likely test commands:")
        lines.extend(f"  - {command}" for command in likely_test_commands[:4])
    if manifests:
        first = manifests[0]
        lines.append(f"- Manifest: {Path(first.path).name} loaded, truncated={str(first.truncated).lower()}")
        lines.append("")
        lines.append("Project Instructions:")
        lines.append(first.content_excerpt[:1000].strip())
    return "\n".join(line for line in lines if line).strip()


def _manifest_kind(name: str) -> str:
    if name == "PP_ECHO.md":
        return "pp_echo"
    if name == "AGENTS.md":
        return "agents"
    return "claude"


def _safe_context_metadata(context: ProjectContext) -> dict[str, Any]:
    return {
        "workspace_path": context.workspace_path,
        "workspace_name": context.workspace_name,
        "detected_languages": list(context.detected_languages),
        "detected_frameworks": list(context.detected_frameworks),
        "important_paths": list(context.important_paths),
        "likely_test_commands": list(context.likely_test_commands),
        "manifest_files": list(context.manifest_files),
        "warnings": list(context.warnings),
    }


def _is_protected_path(path: Path) -> bool:
    parts = [part.lower() for part in path.parts]
    if any(part in {".git", ".pp-agent", "node_modules", "__pycache__", ".pytest_cache", "dist", "build"} for part in parts):
        return True
    name = path.name.lower()
    return name == ".env" or name.startswith(".env.") or name.endswith(".pem") or name.endswith(".key")
