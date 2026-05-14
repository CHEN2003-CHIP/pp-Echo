from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(frozen=True)
class FileMemoryChunk:
    chunk_id: str
    path: str
    line_start: int
    line_end: int
    text: str
    heading_path: list[str] = field(default_factory=list)
    content_hash: str = ""
    file_mtime: float = 0.0
    embedding_model: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass(frozen=True)
class _Block:
    line_start: int
    line_end: int
    lines: list[str]
    heading_path: list[str]

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip()


class MarkdownFileChunker:
    def __init__(self, *, target_chars: int = 1600, overlap_lines: int = 3) -> None:
        self.target_chars = max(300, int(target_chars))
        self.overlap_lines = max(0, min(10, int(overlap_lines)))

    def chunk_text(self, *, path: str, text: str, file_mtime: float) -> list[FileMemoryChunk]:
        blocks = self._blocks(text)
        if not blocks:
            return []
        chunks: list[FileMemoryChunk] = []
        current: list[_Block] = []
        current_chars = 0
        for block in blocks:
            block_len = len(block.text)
            if current and current_chars + block_len > self.target_chars:
                chunks.append(self._make_chunk(path=path, blocks=current, file_mtime=file_mtime, index=len(chunks)))
                current = self._overlap_blocks(current)
                current_chars = sum(len(item.text) for item in current)
            current.append(block)
            current_chars += block_len
        if current:
            chunks.append(self._make_chunk(path=path, blocks=current, file_mtime=file_mtime, index=len(chunks)))
        return chunks

    def _blocks(self, text: str) -> list[_Block]:
        lines = text.splitlines()
        blocks: list[_Block] = []
        heading_stack: list[tuple[int, str]] = []
        pending_lines: list[str] = []
        pending_start = 1
        pending_heading_path: list[str] = []

        def flush(end_line: int) -> None:
            nonlocal pending_lines, pending_start, pending_heading_path
            rendered = "\n".join(pending_lines).strip()
            if rendered:
                blocks.append(
                    _Block(
                        line_start=pending_start,
                        line_end=end_line,
                        lines=list(pending_lines),
                        heading_path=list(pending_heading_path),
                    )
                )
            pending_lines = []
            pending_start = end_line + 1
            pending_heading_path = [title for _level, title in heading_stack]

        for index, line in enumerate(lines, start=1):
            heading = _HEADING_RE.match(line)
            if heading:
                flush(index - 1)
                level = len(heading.group(1))
                title = heading.group(2).strip()
                heading_stack = [(item_level, item_title) for item_level, item_title in heading_stack if item_level < level]
                heading_stack.append((level, title))
                pending_start = index
                pending_heading_path = [item_title for _item_level, item_title in heading_stack]
                pending_lines = [line]
                continue
            if not line.strip():
                flush(index - 1)
                pending_start = index + 1
                pending_heading_path = [title for _level, title in heading_stack]
                continue
            if not pending_lines:
                pending_start = index
                pending_heading_path = [title for _level, title in heading_stack]
            pending_lines.append(line)
        flush(len(lines))
        return blocks

    def _overlap_blocks(self, blocks: list[_Block]) -> list[_Block]:
        if self.overlap_lines <= 0:
            return []
        selected: list[_Block] = []
        line_count = 0
        for block in reversed(blocks):
            selected.append(block)
            line_count += max(1, block.line_end - block.line_start + 1)
            if line_count >= self.overlap_lines:
                break
        return list(reversed(selected))

    @staticmethod
    def _make_chunk(*, path: str, blocks: list[_Block], file_mtime: float, index: int) -> FileMemoryChunk:
        text = "\n\n".join(block.text for block in blocks if block.text).strip()
        line_start = min(block.line_start for block in blocks)
        line_end = max(block.line_end for block in blocks)
        heading_path = next((block.heading_path for block in reversed(blocks) if block.heading_path), [])
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        chunk_source = f"{path}:{line_start}:{line_end}:{content_hash}:{index}"
        chunk_id = hashlib.sha256(chunk_source.encode("utf-8")).hexdigest()
        now = time.time()
        return FileMemoryChunk(
            chunk_id=chunk_id,
            path=path,
            line_start=line_start,
            line_end=line_end,
            text=text,
            heading_path=list(heading_path),
            content_hash=content_hash,
            file_mtime=file_mtime,
            created_at=now,
            updated_at=now,
        )
