from __future__ import annotations

from pathlib import Path

from pp_agent.memory.core_types import CoreMemory, CoreMemoryCandidate
from pp_agent.memory.markdown_target import MarkdownMemoryTarget


def route_core_memory_to_markdown(
    memory_or_candidate: CoreMemory | CoreMemoryCandidate,
    *,
    workspace: Path,
    global_root: Path,
    marker_id: str | None = None,
) -> MarkdownMemoryTarget:
    """Map governed Core Memory records onto the Markdown fact source."""

    workspace = _safe_absolute(workspace)
    global_root = _safe_absolute(global_root)
    memory_id = marker_id or getattr(memory_or_candidate, "id", None) or "pending"
    scope = memory_or_candidate.scope
    section = memory_or_candidate.section
    memory_type = memory_or_candidate.type

    if scope == "global":
        heading = "User Preferences" if section == "user_profile" and memory_type == "preference" else "User Notes"
        return _target(
            file_kind="global_memory",
            path="global/MEMORY.md",
            heading=heading,
            marker_id=str(memory_id),
            metadata={"root": str(global_root)},
        )

    path = "MEMORY.md"
    heading = "Notes"
    file_kind = "workspace_memory"
    if section == "project_profile" and memory_type == "project_fact":
        heading = "Project Facts"
    elif section == "project_profile" and memory_type == "decision":
        heading = "Decisions"
    elif section == "project_profile" and memory_type == "workflow":
        heading = "Workflows"
    elif section == "agent_notes" and memory_type == "error_fix":
        path = "memory/bugs.md"
        heading = "Bug Fixes"
        file_kind = "detailed_memory"
    elif section == "agent_notes" and memory_type == "general":
        path = "memory/lessons.md"
        heading = "Lessons"
        file_kind = "detailed_memory"

    return _target(
        file_kind=file_kind,  # type: ignore[arg-type]
        path=path,
        heading=heading,
        marker_id=str(memory_id),
        metadata={"root": str(workspace)},
    )


def resolve_target_path(target: MarkdownMemoryTarget, *, workspace: Path, global_root: Path) -> Path:
    if target.file_kind == "global_memory":
        if target.path != "global/MEMORY.md":
            raise ValueError("global memory must target global/MEMORY.md")
        root = _safe_absolute(global_root)
        candidate = _safe_absolute(root / "MEMORY.md")
        _ensure_under(candidate, root)
        return candidate

    root = _safe_absolute(workspace)
    if target.path == "MEMORY.md":
        candidate = _safe_absolute(root / "MEMORY.md")
    elif target.path.startswith("memory/") and target.path.endswith(".md"):
        candidate = _safe_absolute(root / target.path)
    else:
        raise ValueError("workspace memory must target MEMORY.md or memory/**/*.md")
    _ensure_under(candidate, root)
    return candidate


def _target(**kwargs) -> MarkdownMemoryTarget:
    return MarkdownMemoryTarget(operation="append", **kwargs)


def _ensure_under(path: Path, root: Path) -> None:
    if path != root and root not in path.parents:
        raise ValueError("markdown memory target escapes its root")


def _safe_absolute(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError:
        return path.absolute()


__all__ = ["resolve_target_path", "route_core_memory_to_markdown"]
