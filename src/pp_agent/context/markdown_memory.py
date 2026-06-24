from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pp_agent.context.item import ContextItem
from pp_agent.context.source_ref import SourceRef


MARKER_RE = re.compile(r"pp-memory:id=([A-Za-z0-9_.:-]+)")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class MarkdownMemoryReadResult:
    """Context item plus non-fatal read warnings."""

    item: ContextItem | None
    warnings: list[str] = field(default_factory=list)


def read_global_memory(global_root: Path, settings: Any = None) -> MarkdownMemoryReadResult:
    """Read global MEMORY.md as bootstrap markdown memory."""

    char_limit = _char_limit(settings, default=2400)
    return _read_memory_file(
        path=Path(global_root).resolve() / "MEMORY.md",
        item_id="markdown-memory:global",
        title="Global memory",
        display_path="global/MEMORY.md",
        char_limit=char_limit,
    )


def read_workspace_memory(workspace: Path, settings: Any = None) -> MarkdownMemoryReadResult:
    """Read workspace MEMORY.md as bootstrap markdown memory."""

    char_limit = _char_limit(settings, default=4000)
    return _read_memory_file(
        path=Path(workspace).resolve() / "MEMORY.md",
        item_id="markdown-memory:workspace",
        title="Workspace memory",
        display_path="MEMORY.md",
        char_limit=char_limit,
    )


def markdown_memory_items(
    *,
    workspace: Path | None = None,
    global_root: Path | None = None,
    settings: Any = None,
) -> tuple[list[ContextItem], list[str]]:
    """Read allowed bootstrap memory files and never scan memory/**/*.md."""

    items: list[ContextItem] = []
    warnings: list[str] = []
    if global_root is not None:
        result = read_global_memory(global_root, settings)
        warnings.extend(result.warnings)
        if result.item is not None:
            items.append(result.item)
    if workspace is not None:
        result = read_workspace_memory(workspace, settings)
        warnings.extend(result.warnings)
        if result.item is not None:
            items.append(result.item)
    return items, warnings


def _read_memory_file(
    *,
    path: Path,
    item_id: str,
    title: str,
    display_path: str,
    char_limit: int,
) -> MarkdownMemoryReadResult:
    if not path.exists():
        return MarkdownMemoryReadResult(None)
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return MarkdownMemoryReadResult(None, warnings=[f"markdown_memory_read_error:{display_path}:{exc}"])
    content = raw.strip()
    if not content:
        return MarkdownMemoryReadResult(None)
    visible, truncated = _truncate_from_tail(content, char_limit=char_limit)
    line_start, line_end = _line_range_for_visible(content, visible)
    content_hash = hashlib.sha256(visible.encode("utf-8")).hexdigest()
    metadata = {
        "content_hash": content_hash,
        "truncated": truncated,
        "char_limit": char_limit,
        "marker_ids": MARKER_RE.findall(visible),
    }
    item = ContextItem(
        id=item_id,
        type="markdown_memory",
        title=title,
        content=visible,
        source_ref=SourceRef(
            source_type="markdown_memory",
            source_id=item_id,
            path=display_path,
            line_start=line_start,
            line_end=line_end,
            heading=_first_heading(visible),
            metadata=metadata,
        ),
        priority=88,
        metadata={**metadata, "context_section": "markdown_memory", "source_type": "markdown_memory", "path": display_path},
    )
    warnings = [f"markdown_memory_truncated:{display_path}"] if truncated else []
    return MarkdownMemoryReadResult(item, warnings=warnings)


def _truncate_from_tail(content: str, *, char_limit: int) -> tuple[str, bool]:
    limit = max(int(char_limit), 0)
    if not limit or len(content) <= limit:
        return content, False
    return content[-limit:].lstrip(), True


def _line_range_for_visible(content: str, visible: str) -> tuple[int, int]:
    start_index = content.rfind(visible)
    if start_index < 0:
        start_index = max(len(content) - len(visible), 0)
    line_start = content[:start_index].count("\n") + 1
    line_end = line_start + max(visible.count("\n"), 0)
    return line_start, line_end


def _first_heading(content: str) -> str | None:
    match = HEADING_RE.search(content)
    if match is None:
        return None
    return match.group(1).strip()[:200]


def _char_limit(settings: Any, *, default: int) -> int:
    value = getattr(settings, "project_memory_char_limit", None)
    if value is None:
        return default
    return max(int(value), 0)
