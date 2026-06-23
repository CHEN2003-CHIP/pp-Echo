from __future__ import annotations

import difflib
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from pp_agent.memory.core_governance import normalize_memory_content, scan_memory_candidate
from pp_agent.memory.core_types import CoreMemory
from pp_agent.memory.markdown_router import resolve_target_path
from pp_agent.memory.markdown_target import MarkdownMemoryPatch, MarkdownMemoryTarget, content_hash


logger = logging.getLogger(__name__)


class MarkdownMemoryApplyError(RuntimeError):
    def __init__(self, code: str, message: str, *, patch: MarkdownMemoryPatch | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.patch = patch


@dataclass(frozen=True)
class MarkdownApplyResult:
    patch: MarkdownMemoryPatch
    warnings: list[str] = field(default_factory=list)


def build_markdown_patch(
    memory: CoreMemory,
    target: MarkdownMemoryTarget,
    *,
    workspace: Path,
    global_root: Path,
) -> MarkdownMemoryPatch:
    path = resolve_target_path(target, workspace=workspace, global_root=global_root)
    before = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    bullet = _bullet_for_memory(memory, marker_id=target.marker_id)
    normalized_before = normalize_memory_content(_strip_markers(before))
    duplicate_without_marker = normalize_memory_content(memory.content) in normalized_before and _marker(target.marker_id) not in before
    after = replace_marker_block(before, target.marker_id, bullet)
    operation = "replace"
    if after == before:
        after = insert_under_heading(before, target.heading, bullet, target.marker_id, title=_default_title(path, target))
        operation = "append"
    target = target.model_copy(update={"operation": operation}, deep=True)
    metadata = {
        "absolute_path": str(path),
        "duplicate_without_marker": duplicate_without_marker,
        "built_at": time.time(),
    }
    return MarkdownMemoryPatch(
        target=target,
        before=before,
        after=after,
        diff=_diff(before, after, fromfile=f"a/{target.path}", tofile=f"b/{target.path}"),
        content_hash_before=content_hash(before),
        content_hash_after=content_hash(after),
        applied=False,
        metadata=metadata,
    )


def apply_markdown_patch(
    patch: MarkdownMemoryPatch,
    *,
    workspace: Path,
    global_root: Path,
    refresh_index: bool = True,
    settings=None,
) -> MarkdownApplyResult:
    if patch.metadata.get("duplicate_without_marker"):
        raise MarkdownMemoryApplyError("duplicate_without_marker", "Similar Markdown memory already exists without a governance marker.", patch=patch)
    path = resolve_target_path(patch.target, workspace=workspace, global_root=global_root)
    before = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    if content_hash(before) != patch.content_hash_before:
        raise MarkdownMemoryApplyError("external_edit_detected", "Markdown memory changed after preview; rebuild the patch before applying.", patch=patch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(patch.after, encoding="utf-8")
    applied = patch.model_copy(update={"applied": True}, deep=True)
    warnings: list[str] = []
    if refresh_index:
        try:
            refresh_file_memory_index_if_available(workspace=workspace, settings=settings)
        except Exception as exc:  # noqa: BLE001
            logger.warning("File memory index refresh failed after Markdown memory apply: %s", exc)
            warnings.append(f"index_refresh_failed: {exc}")
    return MarkdownApplyResult(patch=applied, warnings=warnings)


def insert_under_heading(text: str, heading: str, bullet: str, marker_id: str, *, title: str = "Memory") -> str:
    if _marker(marker_id) in text:
        return replace_marker_block(text, marker_id, bullet)
    lines = text.splitlines()
    if not lines:
        return f"# {title}\n\n## {heading}\n\n{bullet}\n"
    heading_index = _find_heading(lines, heading)
    if heading_index is None:
        prefix = text.rstrip()
        separator = "\n\n" if prefix else ""
        return f"{prefix}{separator}## {heading}\n\n{bullet}\n"
    insert_at = heading_index + 1
    while insert_at < len(lines) and not lines[insert_at].strip():
        insert_at += 1
    lines.insert(insert_at, bullet)
    if insert_at + 1 >= len(lines) or lines[insert_at + 1].strip():
        lines.insert(insert_at + 1, "")
    return "\n".join(lines).rstrip() + "\n"


def replace_marker_block(text: str, marker_id: str, new_bullet: str) -> str:
    marker = re.escape(_marker(marker_id))
    pattern = re.compile(rf"^.*{marker}.*$", re.MULTILINE)
    if not pattern.search(text):
        return text
    return pattern.sub(new_bullet, text).rstrip() + "\n"


def detect_external_edit(path: Path, expected_hash: str) -> bool:
    current = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    return content_hash(current) != expected_hash


def refresh_file_memory_index_if_available(*, workspace: Path, settings=None) -> None:
    from pp_agent.memory.file_memory_tools import build_file_memory_search_engine
    from pp_agent.storage.settings import Settings

    settings = settings or Settings.load(workspace)
    if not settings.memory.file_memory_enable:
        return
    build_file_memory_search_engine(workspace, settings=settings).sync()


def _bullet_for_memory(memory: CoreMemory, *, marker_id: str) -> str:
    safety = scan_memory_candidate(memory)
    if not safety.allowed:
        raise MarkdownMemoryApplyError("unsafe_content", "Unsafe memory cannot be written to Markdown.")
    content = memory.content.rstrip()
    metadata = f"<!-- pp-memory:id={marker_id} type={memory.type} scope={memory.scope} -->"
    return f"- {content} {metadata}"


def _marker(marker_id: str) -> str:
    return f"pp-memory:id={marker_id}"


def _find_heading(lines: list[str], heading: str) -> int | None:
    needle = heading.strip().lower()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        if stripped.lstrip("#").strip().lower() == needle:
            return index
    return None


def _default_title(path: Path, target: MarkdownMemoryTarget) -> str:
    if target.file_kind == "global_memory":
        return "Global Memory"
    if path.name == "MEMORY.md":
        return "Project Memory"
    return path.stem.replace("-", " ").replace("_", " ").title()


def _strip_markers(text: str) -> str:
    return re.sub(r"<!--\s*pp-memory:[^>]*-->", "", text)


def _diff(before: str, after: str, *, fromfile: str, tofile: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
        )
    )


__all__ = [
    "MarkdownApplyResult",
    "MarkdownMemoryApplyError",
    "apply_markdown_patch",
    "build_markdown_patch",
    "detect_external_edit",
    "insert_under_heading",
    "refresh_file_memory_index_if_available",
    "replace_marker_block",
]
