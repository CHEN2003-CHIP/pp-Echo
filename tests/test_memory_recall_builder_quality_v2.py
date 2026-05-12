from pp_agent.memory.recall_builder import RecallSnippetBuilder
from pp_agent.memory.retrieval import RetrievedChunk, RetrievedMessage


def _chunk(index: int, text: str, *, source_kind: str = "assistant", final_score: float = 0.87) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"chunk-{index}",
        message_id=f"message-{index}",
        session_id="session-1",
        turn_id=f"turn-{index}",
        role=source_kind,
        source_kind=source_kind,
        text=text,
        created_at=float(index),
        embedding_model="multimodal-embedding-v1",
        semantic_score=0.9,
        keyword_score=0.2,
        recency_score=0.8,
        same_session_bonus=1.0,
        source_kind_weight=0.8,
        final_score=final_score,
        retrieval_sources=("hybrid",),
        message=RetrievedMessage(
            message_id=f"message-{index}",
            session_id="session-1",
            turn_id=f"turn-{index}",
            role=source_kind,
            text=text,
            created_at=float(index),
        ),
    )


def test_snippet_builder_prioritizes_paths_errors_and_preferences() -> None:
    builder = RecallSnippetBuilder(
        categorize=True,
        prioritize_long_term_preferences=True,
        compress_error_stacks=True,
        path_weight_boost=1.5,
    )

    snippet = builder.build(
        query_text="what should I remember",
        retrieved_chunks=[
            _chunk(1, "Prefer concise replies and avoid adding extra frameworks.", source_kind="user", final_score=0.5),
            _chunk(2, "Traceback (most recent call last): File \"src/pp_agent/runtime/runtime.py\", line 10, ValueError: bad state", final_score=0.4),
            _chunk(3, "Run pytest tests/test_memory_retrieval.py after editing src/pp_agent/runtime/runtime.py.", final_score=0.4),
            _chunk(4, "A generic discussion item without actionable detail.", final_score=0.9),
        ],
        max_items=3,
        max_chars=500,
    )

    assert "Preferences / Constraints:" in snippet
    assert "Errors / Fixes:" in snippet
    assert "Paths / Files / Commands:" in snippet
    assert "generic discussion item" not in snippet.lower()


def test_snippet_builder_compresses_error_stacks() -> None:
    builder = RecallSnippetBuilder(compress_error_stacks=True)
    stack = "\n".join(
        [
            "Traceback (most recent call last):",
            '  File "src/pp_agent/runtime/runtime.py", line 10, in <module>',
            "    run()",
            "ValueError: bad state",
            '  File "src/pp_agent/runtime/turn_loop.py", line 42, in run',
            "    fail()",
        ]
    )

    snippet = builder.build(
        query_text="what failed",
        retrieved_chunks=[_chunk(1, stack, final_score=0.8)],
        max_items=2,
        max_chars=400,
    )

    assert "Traceback (most recent call last):" not in snippet
    assert "ValueError: bad state" in snippet
    assert "src/pp_agent/runtime/runtime.py" in snippet
