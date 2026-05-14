from __future__ import annotations

from pp_agent.memory.file_memory_chunker import MarkdownFileChunker


def test_markdown_chunker_tracks_heading_path_and_lines() -> None:
    text = "\n".join(
        [
            "# Agent Safety",
            "",
            "Intro paragraph.",
            "",
            "## Ask Flow",
            "The ask flow stores a pending action stage before execution.",
            "After user approval, the staged payload is executed by token.",
        ]
    )
    chunks = MarkdownFileChunker(target_chars=1600, overlap_lines=2).chunk_text(
        path="memory/agent-safety.md",
        text=text,
        file_mtime=1.0,
    )

    assert chunks
    assert chunks[-1].heading_path == ["Agent Safety", "Ask Flow"]
    assert chunks[-1].line_start <= 5
    assert chunks[-1].line_end == 7


def test_markdown_chunker_splits_near_target_and_overlaps_lines() -> None:
    text = "# Notes\n" + "\n\n".join(f"Paragraph {index} " + ("x" * 120) for index in range(12))
    chunks = MarkdownFileChunker(target_chars=450, overlap_lines=3).chunk_text(
        path="MEMORY.md",
        text=text,
        file_mtime=1.0,
    )

    assert len(chunks) > 1
    assert all(len(chunk.text) <= 700 for chunk in chunks)
    assert chunks[1].line_start <= chunks[0].line_end
