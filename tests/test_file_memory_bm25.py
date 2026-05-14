from __future__ import annotations

from pp_agent.memory.file_memory_bm25 import FileMemoryBM25Index, tokenize_file_memory_text
from pp_agent.memory.file_memory_chunker import FileMemoryChunk


def _chunk(chunk_id: str, path: str, text: str) -> FileMemoryChunk:
    return FileMemoryChunk(
        chunk_id=chunk_id,
        path=path,
        line_start=1,
        line_end=3,
        text=text,
        heading_path=["Test"],
        content_hash=chunk_id,
        file_mtime=1.0,
    )


def test_bm25_hits_exact_errors_symbols_paths_and_chinese() -> None:
    chunks = [
        _chunk("safety", "memory/agent-safety.md", "ToolPolicyEvaluator decides allow ask deny using pending_action tokens."),
        _chunk("bugs", "memory/bugs.md", "Fixed ERR_POLICY_DENIED after protected_path_hint was true."),
        _chunk("zh", "memory/cn.md", "用户喜欢使用 pytest 测试框架。"),
    ]
    index = FileMemoryBM25Index(chunks)

    assert index.search("ToolPolicyEvaluator allow ask deny", limit=1)[0].chunk_id == "safety"
    assert index.search("memory/agent-safety.md pending_action", limit=1)[0].chunk_id == "safety"
    assert index.search("ERR_POLICY_DENIED protected_path_hint", limit=1)[0].chunk_id == "bugs"
    assert index.search("测试框架", limit=1)[0].chunk_id == "zh"


def test_tokenizer_keeps_code_symbols_and_fallback_parts() -> None:
    tokens = tokenize_file_memory_text("ToolPolicyEvaluator memory/agent-safety.md pending_action")

    assert "toolpolicyevaluator" in tokens
    assert "tool" in tokens
    assert "policy" in tokens
    assert "evaluator" in tokens
    assert "memory/agent-safety.md" in tokens
    assert "pending_action" in tokens
