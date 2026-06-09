from pp_agent.attachments.rerank import rerank_attachment_results
from pp_agent.attachments.schema import AttachmentChunk, AttachmentKind, AttachmentSearchResult


def test_exact_phrase_rerank_boosts_relevant_chunk() -> None:
    weak = AttachmentChunk(
        chunk_id="c1",
        attachment_id="a",
        session_id="s",
        filename="a.md",
        kind=AttachmentKind.MARKDOWN,
        text="approval unrelated words",
        token_estimate=3,
    )
    strong = AttachmentChunk(
        chunk_id="c2",
        attachment_id="a",
        session_id="s",
        filename="a.md",
        kind=AttachmentKind.MARKDOWN,
        text="approval gate exact phrase",
        token_estimate=4,
        source_ref="a.md > Approval",
    )
    results = [
        AttachmentSearchResult(chunk_id="c1", attachment_id="a", filename="a.md", score=2.0, match_type="keyword", snippet="approval"),
        AttachmentSearchResult(chunk_id="c2", attachment_id="a", filename="a.md", score=1.0, match_type="keyword", snippet="approval gate"),
    ]

    reranked = rerank_attachment_results(results, {"c1": weak, "c2": strong}, "approval gate")

    assert reranked[0].chunk_id == "c2"
