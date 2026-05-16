from __future__ import annotations

from pathlib import Path

from pp_agent.memory.embedding import NoopEmbeddingProvider
from pp_agent.memory.file_memory_chunker import MarkdownFileChunker
from pp_agent.memory.file_memory_search import FileMemorySearchEngine, FileMemorySearchRequest
from pp_agent.memory.file_memory_store import FileMemoryIndexStore
from pp_agent.memory.file_memory_vector import NoopFileMemoryVectorIndex
from pp_agent.memory.types import VectorQueryResult
from pp_agent.learning.bootstrap_memory import BootstrapMemoryManager
from pp_agent.learning.file_memory_writer import FileMemoryWriter
from pp_agent.learning.models import LearningCandidate
from pp_agent.learning.models import LearningSettings
from pp_agent.learning.store import LearningStore


class _EmbeddingProvider:
    def __init__(self, enabled: bool = True, fail: bool = False) -> None:
        self.enabled = enabled
        self.fail = fail
        self.calls: list[list[str]] = []

    def is_enabled(self) -> bool:
        return self.enabled

    def model_name(self) -> str:
        return "test-embedding"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.fail:
            raise RuntimeError("embedding unavailable")
        return [[float(len(text)), 1.0] for text in texts]


class _VectorIndex:
    def __init__(self, enabled: bool = True, fail_query: bool = False) -> None:
        self.enabled = enabled
        self.fail_query = fail_query
        self.upserted: dict[str, object] = {}
        self.deleted: list[str] = []

    def is_enabled(self) -> bool:
        return self.enabled

    def upsert_chunks(self, chunks, *, embeddings, embedding_model):
        for chunk in chunks:
            self.upserted[chunk.chunk_id] = chunk
        return [chunk.chunk_id for chunk in chunks]

    def query(self, *, query_embedding, limit):
        if self.fail_query:
            raise RuntimeError("vector unavailable")
        return [
            VectorQueryResult(chunk_id=chunk_id, score=0.1, text=chunk.text)
            for chunk_id, chunk in list(self.upserted.items())[:limit]
        ]

    def delete_chunk_ids(self, chunk_ids):
        self.deleted.extend(chunk_ids)


def _write_memory(tmp_path: Path) -> None:
    (tmp_path / "MEMORY.md").write_text(
        "# Project Memory\nUser prefers pytest and does not want a new test framework.\n",
        encoding="utf-8",
    )
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(exist_ok=True)
    (memory_dir / "agent-safety.md").write_text(
        "# Agent Safety\n## Ask Flow\n"
        "The ask flow stores a pending action stage before execution.\n"
        "After user approval, the staged payload is executed by token.\n"
        "ToolPolicyEvaluator decides allow/ask/deny using tool effects.\n",
        encoding="utf-8",
    )
    (memory_dir / "rag-notes.md").write_text(
        "# RAG Notes\nFor long-term memory retrieval, use hybrid recall.\n"
        "BM25 catches exact symbols and error strings.\n"
        "Vector retrieval catches semantic paraphrases.\n",
        encoding="utf-8",
    )
    daily_dir = memory_dir / "daily"
    daily_dir.mkdir(exist_ok=True)
    (daily_dir / "2026-05-16.md").write_text(
        "# Daily Journal\n\n## Smoke passed\n\n2026-05-16 web smoke verification passed.\n",
        encoding="utf-8",
    )


def _engine(tmp_path: Path, *, embedding=None, vector=None, global_root: Path | None = None) -> FileMemorySearchEngine:
    return FileMemorySearchEngine(
        store=FileMemoryIndexStore(
            workspace=tmp_path,
            index_path=tmp_path / ".pp-agent" / "file-memory.db",
            global_root=global_root,
        ),
        chunker=MarkdownFileChunker(target_chars=500, overlap_lines=2),
        embedding_provider=embedding or NoopEmbeddingProvider(),
        vector_index=vector or NoopFileMemoryVectorIndex(),
        snippet_chars=120,
        max_per_file=1,
    )


def test_file_memory_search_bm25_fallback_without_embedding(tmp_path: Path) -> None:
    _write_memory(tmp_path)
    engine = _engine(tmp_path)

    result = engine.search(FileMemorySearchRequest(query="ToolPolicyEvaluator allow ask deny", top_k=3, mode="auto"))

    assert result.mode == "bm25"
    assert result.semantic_available is False
    assert result.results[0].path == "memory/agent-safety.md"
    assert result.results[0].sources == ["bm25"]
    assert len(result.results[0].snippet) <= 120


def test_file_memory_search_merges_vector_and_bm25_sources(tmp_path: Path) -> None:
    _write_memory(tmp_path)
    vector = _VectorIndex()
    engine = _engine(tmp_path, embedding=_EmbeddingProvider(), vector=vector)

    result = engine.search(FileMemorySearchRequest(query="ToolPolicyEvaluator allow ask deny", top_k=3, mode="hybrid"))

    assert result.mode == "hybrid"
    assert result.semantic_available is True
    assert result.results[0].path == "memory/agent-safety.md"
    assert set(result.results[0].sources) == {"bm25", "vector"}


def test_file_memory_search_degrades_when_vector_unavailable(tmp_path: Path) -> None:
    _write_memory(tmp_path)
    engine = _engine(tmp_path, embedding=_EmbeddingProvider(), vector=_VectorIndex(fail_query=True))

    result = engine.search(FileMemorySearchRequest(query="pytest test framework", top_k=2, mode="hybrid"))

    assert result.results
    assert any("Vector search failed" in warning for warning in result.warnings)


def test_file_memory_search_degrades_when_embedding_unavailable(tmp_path: Path) -> None:
    _write_memory(tmp_path)
    engine = _engine(tmp_path, embedding=_EmbeddingProvider(fail=True), vector=_VectorIndex())

    result = engine.search(FileMemorySearchRequest(query="pytest test framework", top_k=2, mode="hybrid"))

    assert result.results
    assert any("embedding failed" in warning.lower() or "vector search failed" in warning.lower() for warning in result.warnings)


def test_file_memory_bm25_mode_does_not_call_embedding(tmp_path: Path) -> None:
    _write_memory(tmp_path)
    embedding = _EmbeddingProvider()
    engine = _engine(tmp_path, embedding=embedding, vector=_VectorIndex())

    result = engine.search(FileMemorySearchRequest(query="pytest test framework", top_k=2, mode="bm25"))

    assert result.results
    assert embedding.calls == []


def test_file_memory_search_finds_synced_bootstrap_memory(tmp_path: Path) -> None:
    BootstrapMemoryManager(workspace=tmp_path, settings=LearningSettings()).sync(
        "- **Testing preference**: User prefers pytest for pp-Echo changes."
    )
    engine = _engine(tmp_path)

    result = engine.search(FileMemorySearchRequest(query="pytest preference", top_k=2, mode="bm25"))

    assert result.results
    assert result.results[0].path == "MEMORY.md"


def test_file_memory_search_finds_auto_written_detailed_memory(tmp_path: Path) -> None:
    store = LearningStore(tmp_path / ".pp-agent" / "learning")
    candidate = LearningCandidate(
        id="learn-1",
        kind="lesson",
        title="Embedding collection mismatch",
        content="Fixed issue where embedding model changed collection mismatch broke retrieval.",
        suggested_target="detailed",
    )
    store.append_candidates([candidate])
    FileMemoryWriter(
        workspace=tmp_path,
        settings=LearningSettings(detailed_memory_sync_index_after_write=False),
        store=store,
    ).auto_apply([candidate])
    engine = _engine(tmp_path)

    result = engine.search(FileMemorySearchRequest(query="embedding model changed collection mismatch", top_k=2, mode="bm25"))

    assert result.results
    assert result.results[0].path == "memory/bugs.md"


def test_file_memory_search_scope_and_source_scope(tmp_path: Path) -> None:
    _write_memory(tmp_path)
    global_root = tmp_path / ".global"
    global_root.mkdir()
    (global_root / "MEMORY.md").write_text("# Global Memory\n\nUser always prefers Chinese plans.\n", encoding="utf-8")
    engine = _engine(tmp_path, global_root=global_root)

    workspace_result = engine.search(FileMemorySearchRequest(query="smoke verification", top_k=3, mode="bm25", scope="workspace"))
    global_result = engine.search(FileMemorySearchRequest(query="user always prefers Chinese plans", top_k=3, mode="bm25", scope="global"))
    all_result = engine.search(FileMemorySearchRequest(query="Chinese plans", top_k=5, mode="bm25", scope="all"))

    assert workspace_result.results
    assert all(hit.source_scope != "global_bootstrap" for hit in workspace_result.results)
    assert global_result.results
    assert all(hit.path == "global/MEMORY.md" for hit in global_result.results)
    assert all(hit.source_scope == "global_bootstrap" for hit in global_result.results)
    assert any(hit.source_scope == "global_bootstrap" for hit in all_result.results)


def test_file_memory_search_auto_scope_prefers_workspace_for_non_preference_queries(tmp_path: Path) -> None:
    _write_memory(tmp_path)
    global_root = tmp_path / ".global"
    global_root.mkdir()
    (global_root / "MEMORY.md").write_text("# Global Memory\n\nUser always prefers Chinese plans.\n", encoding="utf-8")
    engine = _engine(tmp_path, global_root=global_root)

    result = engine.search(FileMemorySearchRequest(query="web smoke verification passed", top_k=5, mode="bm25", scope="auto"))

    assert result.results
    assert all(hit.path != "global/MEMORY.md" for hit in result.results)


def test_file_memory_search_max_per_file_and_top_k(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "many.md").write_text(
        "# Many\n\n" + "\n\n".join(f"pytest note {index} " + ("x" * 80) for index in range(8)),
        encoding="utf-8",
    )
    engine = _engine(tmp_path)

    result = engine.search(FileMemorySearchRequest(query="pytest", top_k=5, mode="bm25"))

    assert len(result.results) <= 1
    assert all(hit.path == "memory/many.md" for hit in result.results)


def test_file_memory_incremental_add_modify_delete_and_embedding_dedup(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    target = memory_dir / "notes.md"
    target.write_text("# Notes\noldtoken", encoding="utf-8")
    embedding = _EmbeddingProvider()
    vector = _VectorIndex()
    engine = _engine(tmp_path, embedding=embedding, vector=vector)

    assert engine.search(FileMemorySearchRequest(query="oldtoken", mode="hybrid")).results
    first_chunk_embedding_calls = [batch for batch in embedding.calls if any("# Notes\noldtoken" in text for text in batch)]
    assert len(first_chunk_embedding_calls) == 1
    assert engine.search(FileMemorySearchRequest(query="oldtoken", mode="hybrid")).results
    repeated_chunk_embedding_calls = [batch for batch in embedding.calls if any("# Notes\noldtoken" in text for text in batch)]
    assert len(repeated_chunk_embedding_calls) == 1

    target.write_text("# Notes\nnewmarker", encoding="utf-8")
    modified = engine.search(FileMemorySearchRequest(query="newmarker", mode="bm25"))
    old = engine.search(FileMemorySearchRequest(query="oldtoken", mode="bm25"))
    assert modified.results
    assert not old.results

    target.unlink()
    deleted = engine.search(FileMemorySearchRequest(query="newmarker", mode="bm25"))
    assert not deleted.results
