from __future__ import annotations

from pathlib import Path

import pytest

from pp_agent.memory.file_memory_store import FileMemoryAccessError, FileMemoryIndexStore


def _store(tmp_path: Path) -> FileMemoryIndexStore:
    return FileMemoryIndexStore(workspace=tmp_path, index_path=tmp_path / ".pp-agent" / "file-memory.db")


def test_memory_get_allows_only_markdown_memory_files(tmp_path: Path) -> None:
    (tmp_path / "MEMORY.md").write_text("root memory", encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "foo.md").write_text("foo memory", encoding="utf-8")
    nested = tmp_path / "memory" / "a"
    nested.mkdir()
    (nested / "b.md").write_text("nested memory", encoding="utf-8")
    store = _store(tmp_path)

    assert store.read_line_range("MEMORY.md").content == "root memory"
    assert store.read_line_range("memory/foo.md").content == "foo memory"
    assert store.read_line_range("memory/a/b.md").content == "nested memory"


@pytest.mark.parametrize("path", ["../secret.md", ".env", "memory/not-md.txt", "memory/.env", "C:/secret.md"])
def test_memory_get_rejects_unsafe_paths(tmp_path: Path, path: str) -> None:
    store = _store(tmp_path)

    with pytest.raises(FileMemoryAccessError):
        store.read_line_range(path)


def test_memory_get_line_range_and_line_count_cap(tmp_path: Path) -> None:
    (tmp_path / "MEMORY.md").write_text("\n".join(f"line {index}" for index in range(1, 401)), encoding="utf-8")
    store = _store(tmp_path)

    ranged = store.read_line_range("MEMORY.md", start_line=10, line_count=3)
    capped = store.read_line_range("MEMORY.md", start_line=1, line_count=999)

    assert ranged.line_start == 10
    assert ranged.line_end == 12
    assert ranged.content == "line 10\nline 11\nline 12"
    assert capped.line_end == 300


def test_memory_get_rejects_symlink_escape_when_supported(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-memory.md"
    outside.write_text("secret", encoding="utf-8")
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    link = memory_dir / "escape.md"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available")

    with pytest.raises(FileMemoryAccessError):
        _store(tmp_path).read_line_range("memory/escape.md")
