from pathlib import Path

from pp_agent.attachments.embeddings import DeterministicFakeEmbeddingProvider, UnavailableEmbeddingProvider
from pp_agent.attachments.hybrid_retrieval import hybrid_search_chunks
from pp_agent.attachments.retrieval import load_chunks
from pp_agent.attachments.service import AttachmentService
from pp_agent.observability import TraceRecorder, TraceStore


def test_hybrid_search_falls_back_to_keyword_when_embedding_unavailable(tmp_path: Path) -> None:
    service = AttachmentService(tmp_path, embedding_provider=UnavailableEmbeddingProvider())
    record = service.upload_bytes("s1", "guide.md", b"# Approval\n\napproval gate fallback")

    results = service.search("s1", "approval", mode="auto")

    assert results
    assert results[0]["match_type"] == "keyword"


def test_hybrid_merge_dedupes_chunks_with_fake_provider(tmp_path: Path) -> None:
    service = AttachmentService(tmp_path)
    record = service.upload_bytes("s1", "guide.md", b"# Approval\n\napproval gate hybrid merge")
    chunks = load_chunks(tmp_path / record.chunks_path)

    results, metadata = hybrid_search_chunks(chunks, "approval", embedding_provider=DeterministicFakeEmbeddingProvider(), top_k=5)

    assert metadata["index_type"] == "hybrid"
    assert len({result.chunk_id for result in results}) == len(results)


def test_search_trace_records_fallback_reason(tmp_path: Path) -> None:
    recorder = TraceRecorder(TraceStore(tmp_path / ".pp-agent" / "traces"), workspace=tmp_path)
    run_id = recorder.start_run(session_id="s1")
    service = AttachmentService(tmp_path, observability=recorder, embedding_provider=UnavailableEmbeddingProvider())
    service.upload_bytes("s1", "guide.md", b"# Approval\n\napproval fallback trace")
    service.search("s1", "approval", mode="hybrid")
    recorder.end_run()

    detail = TraceStore(tmp_path / ".pp-agent" / "traces").read_run(run_id)
    search_span = next(span for span in detail.spans if span.name == "attachment.search")
    assert search_span.output["fallback_reason"] == "embedding_provider_unavailable"
