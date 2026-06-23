from collections.abc import Iterator
from pathlib import Path

from pp_agent.llm import ModelConfig
from pp_agent.runtime.hooks import RuntimeHooks
from pp_agent.memory.recall_builder import RecallSnippetBuilder
from pp_agent.memory.retrieval import RetrievedChunk, RetrievedMessage
from pp_agent.memory.retrieval_hook import MemoryRetrievalHook
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.storage.sessions import SessionStore
from pp_agent.tools.registry import ToolRegistry


class _RecordingLLMClient:
    def __init__(self) -> None:
        self.model = ModelConfig()
        self.seen_messages = []

    def stream_chat(self, messages, tools=None) -> Iterator[dict]:
        self.seen_messages.append(messages)
        yield {"text": "ok", "tool_calls": [], "finish_reason": "stop", "raw": {}}


class _Retriever:
    def __init__(self, chunks=None, fail: bool = False) -> None:
        self.chunks = chunks or []
        self.fail = fail
        self.calls = []

    def retrieve(self, *, query_text, session_id, recent_chunk_ids=None, limit=6, recent_fallback_keys=None):
        self.calls.append(
            {
                "query_text": query_text,
                "session_id": session_id,
                "recent_chunk_ids": set(recent_chunk_ids or set()),
                "recent_fallback_keys": set(recent_fallback_keys or set()),
                "limit": limit,
            }
        )
        if self.fail:
            raise RuntimeError("retrieval boom")
        return self.chunks[:limit]


def _runtime_with_hook(tmp_path: Path, hook: MemoryRetrievalHook) -> tuple[AgentRuntime, _RecordingLLMClient]:
    llm = _RecordingLLMClient()
    store = SessionStore(tmp_path / "sessions")
    record = store.create("system", ModelConfig())
    agent = AgentRuntime(
        llm_client=llm,
        tool_registry=ToolRegistry(tmp_path),
        session_store=store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=lambda _name, _args: True,
        require_plan_approval=False,
        runtime_hooks=RuntimeHooks(transform_context=[hook.transform_context]),
    )
    agent.restore_session_record(record)
    return agent, llm


def _chunk(text: str, *, chunk_id: str = "chunk-1") -> RetrievedChunk:
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


def test_runtime_retrieval_hook_noop_when_disabled(tmp_path: Path) -> None:
    hook = MemoryRetrievalHook(enabled=False)
    agent, llm = _runtime_with_hook(tmp_path, hook)

    agent.prompt("hello")

    recall_messages = [message for message in llm.seen_messages[0] if message.role == "system" and "[History Recall]" in message.content[0].text]
    assert recall_messages == []


def test_runtime_retrieval_failure_does_not_break_prompt(tmp_path: Path) -> None:
    hook = MemoryRetrievalHook(
        retriever=_Retriever(fail=True),
        builder=RecallSnippetBuilder(),
        session_id="session-1",
        enabled=True,
    )
    agent, llm = _runtime_with_hook(tmp_path, hook)

    events = agent.prompt("hello")

    assert any(event.type == "agent_end" for event in events)
    recall_messages = [message for message in llm.seen_messages[0] if message.role == "system" and "[History Recall]" in message.content[0].text]
    assert recall_messages == []


def test_runtime_retrieval_hook_injects_single_context_block(tmp_path: Path) -> None:
    hook = MemoryRetrievalHook(
        retriever=_Retriever(
            chunks=[
                _chunk("Remember that the repo uses pytest and keep responses concise."),
                _chunk("The key runtime file is src/pp_agent/runtime/runtime.py.", chunk_id="chunk-2"),
            ]
        ),
        builder=RecallSnippetBuilder(),
        session_id="session-1",
        enabled=True,
        retrieval_limit=6,
        retrieval_max_snippets=4,
        retrieval_max_chars=400,
    )
    agent, llm = _runtime_with_hook(tmp_path, hook)

    events = agent.prompt("what did we decide?")

    recall_messages = [message for message in llm.seen_messages[0] if message.role == "system" and "[History Recall]" in message.content[0].text]
    assert len(recall_messages) == 1
    assert "Remember that the repo uses pytest" in recall_messages[0].content[0].text
    context_events = [event for event in events if event.type == "context_built"]
    assert context_events
    assert context_events[0].details["context_payload_version"] == 2
    assert "memory_recall" not in context_events[0].details
    recall = context_events[0].details["context"]["memory_recall"]
    assert recall["recalled_chunk_ids"] == ["chunk-1", "chunk-2"]
    assert recall["snippet_chars"] > 0
