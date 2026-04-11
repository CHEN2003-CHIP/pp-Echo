from pp_agent.memory.recall_builder import RecallSnippetBuilder
from pp_agent.memory.retrieval import RetrievedChunk, RetrievedMessage


def _chunk(index: int, text: str, *, source_kind: str = "assistant") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"chunk-{index}",
        message_id=f"message-{index}",
        session_id="session-1",
        turn_id=f"turn-{index}",
        role="assistant",
        source_kind=source_kind,
        text=text,
        created_at=float(index),
        embedding_model="multimodal-embedding-v1",
        semantic_score=0.9,
        keyword_score=0.2,
        recency_score=0.8,
        same_session_bonus=1.0,
        source_kind_weight=0.8,
        final_score=0.87,
        retrieval_sources=("hybrid",),
        message=RetrievedMessage(
            message_id=f"message-{index}",
            session_id="session-1",
            turn_id=f"turn-{index}",
            role="assistant",
            text=text,
            created_at=float(index),
        ),
    )


def test_recall_builder_outputs_categorized_sections() -> None:
    builder = RecallSnippetBuilder(categorize=True)

    snippet = builder.build(
        query_text="summarize history",
        retrieved_chunks=[
            _chunk(1, "Prefer concise replies and avoid adding extra frameworks.", source_kind="user"),
            _chunk(2, "We decided to keep pytest as the main test runner."),
            _chunk(3, "The build failed because src/pp_agent/runtime/runtime.py was missing and then it was fixed."),
            _chunk(4, "Run pytest tests/test_memory_retrieval.py after the change."),
        ],
        max_items=4,
        max_chars=800,
    )

    assert snippet.startswith("[History Recall]")
    assert "偏好 / 约束:" in snippet
    assert "决策 / 结论:" in snippet
    assert "错误 / 修复:" in snippet
    assert "路径 / 文件 / 命令:" in snippet


def test_recall_builder_respects_length_budget() -> None:
    builder = RecallSnippetBuilder(categorize=True)
    long_text = "This is a very long historical detail about pytest and runtime constraints. " * 20

    snippet = builder.build(
        query_text="summarize history",
        retrieved_chunks=[
            _chunk(1, long_text, source_kind="user"),
            _chunk(2, long_text, source_kind="assistant"),
            _chunk(3, long_text, source_kind="assistant"),
        ],
        max_items=4,
        max_chars=260,
    )

    assert snippet.startswith("[History Recall]")
    assert len(snippet) <= 260
