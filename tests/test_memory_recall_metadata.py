from pp_agent.domain import ChatMessage, TextPart
from pp_agent.memory.recall_builder import RecallSnippetBuilder
from pp_agent.memory.retrieval import RetrievedChunk, RetrievedMessage
from pp_agent.memory.retrieval_hook import MemoryRetrievalHook, RECALL_METADATA_KEY
from pp_agent.runtime.state import AgentState


class _RecordingRetriever:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks
        self.calls = []

    def retrieve(self, *, query_text, session_id, recent_chunk_ids=None, limit=6, recent_fallback_keys=None):
        self.calls.append(
            {
                "recent_chunk_ids": set(recent_chunk_ids or set()),
                "recent_fallback_keys": set(recent_fallback_keys or set()),
            }
        )
        return [chunk for chunk in self.chunks if chunk.chunk_id not in (recent_chunk_ids or set())][:limit]


def _chunk(chunk_id: str, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        message_id=f"{chunk_id}-message",
        session_id="session-1",
        turn_id="turn-1",
        role="assistant",
        source_kind="assistant",
        text=text,
        created_at=1.0,
        embedding_model="multimodal-embedding-v1",
        semantic_score=0.9,
        keyword_score=0.0,
        recency_score=0.8,
        same_session_bonus=1.0,
        source_kind_weight=0.8,
        final_score=0.87,
        retrieval_sources=("vector",),
        message=RetrievedMessage(
            message_id=f"{chunk_id}-message",
            session_id="session-1",
            turn_id="turn-1",
            role="assistant",
            text=text,
            created_at=1.0,
        ),
    )


def _state() -> AgentState:
    return AgentState(system_prompt="system")


def test_recall_metadata_carries_chunk_ids() -> None:
    state = _state()
    retriever = _RecordingRetriever([_chunk("chunk-1", "Remember pytest and concise replies.")])
    hook = MemoryRetrievalHook(
        retriever=retriever,
        builder=RecallSnippetBuilder(),
        session_id="session-1",
        enabled=True,
    )
    messages = [ChatMessage(role="user", content=[TextPart(text="what did we decide?")], timestamp=1.0)]

    transformed = hook.transform_context(state, messages)

    recall_message = transformed[0]
    payload = recall_message.metadata[RECALL_METADATA_KEY]
    assert payload["recalled_chunk_ids"] == ["chunk-1"]
    assert payload["source_session_ids"] == ["session-1"]
    assert payload["source_turn_ids"] == ["turn-1"]
    assert payload["retrieval_version"] == "v2_rerank_metadata"


def test_recent_dedup_prefers_explicit_chunk_metadata() -> None:
    state = _state()
    retriever = _RecordingRetriever([_chunk("chunk-1", "Remember pytest and concise replies.")])
    hook = MemoryRetrievalHook(
        retriever=retriever,
        builder=RecallSnippetBuilder(),
        session_id="session-1",
        enabled=True,
    )
    messages = [ChatMessage(role="user", content=[TextPart(text="what did we decide?")], timestamp=1.0)]

    first = hook.transform_context(state, messages)
    hook.transform_context(state, first)

    assert retriever.calls[1]["recent_chunk_ids"] == {"chunk-1"}


def test_recent_dedup_falls_back_to_text_fingerprint() -> None:
    state = _state()
    retriever = _RecordingRetriever([_chunk("chunk-1", "Remember pytest and concise replies.")])
    hook = MemoryRetrievalHook(
        retriever=retriever,
        builder=RecallSnippetBuilder(),
        session_id="session-1",
        enabled=True,
        recent_dedup_use_chunk_metadata=False,
    )
    messages = [ChatMessage(role="user", content=[TextPart(text="what did we decide?")], timestamp=1.0)]

    hook.transform_context(state, messages)
    second = hook.transform_context(state, messages)

    assert retriever.calls[1]["recent_chunk_ids"] == {"chunk-1"}
    assert any(key.startswith("fp:") for key in retriever.calls[1]["recent_fallback_keys"])
    assert second == messages
