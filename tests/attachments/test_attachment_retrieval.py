from pp_agent.attachments.retrieval import search_chunks
from pp_agent.attachments.schema import AttachmentChunk, AttachmentKind


def test_search_chunks_returns_relevant_snippet() -> None:
    chunk = AttachmentChunk(
        chunk_id="chk_1",
        attachment_id="att_1",
        session_id="s1",
        filename="policy.md",
        kind=AttachmentKind.MARKDOWN,
        text="The approval workflow requires a human gate.",
        token_estimate=10,
    )

    results = search_chunks([chunk], "approval workflow")

    assert results
    assert results[0].chunk_id == "chk_1"
    assert "approval" in results[0].snippet.lower()
