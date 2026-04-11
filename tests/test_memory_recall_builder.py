from pp_agent.memory.recall_builder import RecallSnippetBuilder
from pp_agent.memory.retrieval import RetrievedChunk, RetrievedMessage


def _retrieved_chunk(index: int, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"chunk-{index}",
        message_id=f"message-{index}",
        session_id="session-1",
        turn_id=f"turn-{index}",
        role="assistant",
        source_kind="assistant",
        text=text,
        created_at=float(index),
        embedding_model="multimodal-embedding-v1",
        semantic_score=0.9,
        keyword_score=0.4,
        recency_score=0.8,
        same_session_bonus=1.0,
        source_kind_weight=0.8,
        final_score=0.87,
        retrieval_sources=("vector",),
        message=RetrievedMessage(
            message_id=f"message-{index}",
            session_id="session-1",
            turn_id=f"turn-{index}",
            role="assistant",
            text=text,
            created_at=float(index),
        ),
    )


def test_recall_builder_compresses_results() -> None:
    builder = RecallSnippetBuilder()

    snippet = builder.build(
        query_text="what did we decide",
        retrieved_chunks=[
            _retrieved_chunk(1, "We decided to keep pytest as the main test runner and avoid adding extra frameworks."),
            _retrieved_chunk(2, "The important file path is src/pp_agent/runtime/runtime.py and we should not break planner flow."),
            _retrieved_chunk(3, "The build failed earlier because a path was missing, then it was fixed."),
            _retrieved_chunk(4, "We decided to keep pytest as the main test runner and avoid adding extra frameworks."),
        ],
        max_items=3,
        max_chars=320,
    )

    assert snippet.startswith("[History Recall]")
    assert "以下是与当前问题相关的历史片段，仅在相关时参考：" in snippet
    assert any(title in snippet for title in ("决策 / 结论:", "路径 / 文件 / 命令:", "错误 / 修复:"))
    assert len(snippet) <= 320
