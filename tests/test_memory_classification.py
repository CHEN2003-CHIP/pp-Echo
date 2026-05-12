from pp_agent.memory import HistoryIndexer
from pp_agent.memory.classification import classify_memory_text


def test_classify_memory_text_recognizes_core_categories() -> None:
    assert classify_memory_text("我偏好 pytest，不要引入新框架", role="user", source_kind="user") == "preference"
    assert classify_memory_text("We decided to keep the SQLite backend.") == "decision"
    assert classify_memory_text("Traceback ValueError was fixed in src/pp_agent/runtime/runtime.py") == "error_fix"
    assert classify_memory_text("Run pytest tests/test_memory_retrieval.py") == "path_command"


def test_indexer_writes_memory_category_metadata() -> None:
    indexer = HistoryIndexer(chunk_target_tokens=30, chunk_max_tokens=40)

    chunks = indexer.chunk_message(
        text="我偏好 pytest，不要引入新框架",
        role="user",
        metadata={"source": "test"},
    )

    assert chunks
    assert chunks[0].metadata["memory_category"] == "preference"
