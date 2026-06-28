from __future__ import annotations

from pathlib import Path

import pytest

from pp_agent.context.item import ContextItem
from pp_agent.context.pipeline import ContextPipeline
from pp_agent.context.runtime_bridge import build_runtime_context_pack
from pp_agent.context.runtime_bridge import context_pipeline_config_from_settings
from pp_agent.context.source_ref import SourceRef
from pp_agent.domain import ChatMessage, TextPart
from pp_agent.memory.embedding import NoopEmbeddingProvider
from pp_agent.memory.file_memory_chunker import MarkdownFileChunker
from pp_agent.memory.core_service import CoreMemoryService
from pp_agent.memory.core_store import CoreMemoryStore
from pp_agent.memory.core_types import CoreMemoryCandidate
from pp_agent.memory.file_memory_tools import build_file_memory_store
from pp_agent.memory.file_memory_search import FileMemorySearchEngine, FileMemorySearchRequest
from pp_agent.memory.file_memory_tools import memory_search_executor
from pp_agent.memory.file_memory_vector import NoopFileMemoryVectorIndex
from pp_agent.runtime.state import AgentState
from pp_agent.storage.settings import Settings


def _settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch | None = None) -> Settings:
    if monkeypatch is not None:
        monkeypatch.setenv("PP_AGENT_HOME", str(tmp_path / ".global"))
    settings = Settings.load(tmp_path)
    settings.global_dir = tmp_path / ".global"
    settings.global_dir.mkdir(parents=True, exist_ok=True)
    settings.context_pipeline.context_pipeline_mode = "on"
    return settings


def _service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CoreMemoryService:
    settings = _settings(tmp_path, monkeypatch)
    return CoreMemoryService(
        store=CoreMemoryStore(settings.core_memory_db_path()),
        settings=settings,
        workspace=tmp_path.resolve(),
    )


def _messages(user_text: str = "what should I remember?") -> list[ChatMessage]:
    return [
        ChatMessage(role="system", content=[TextPart(text="system")], timestamp=0.0),
        ChatMessage(role="user", content=[TextPart(text=user_text)], timestamp=1.0),
    ]


def _text(message: ChatMessage) -> str:
    return "\n".join(part.text for part in message.content if isinstance(part, TextPart))


def _provider_text(pack) -> str:
    return "\n".join(_text(message) for message in pack.final_messages)


def _pack(tmp_path: Path, settings: Settings, *, state: AgentState | None = None):
    return build_runtime_context_pack(
        state=state or AgentState(system_prompt="system"),
        messages=_messages(),
        settings=settings,
        session_id="session-1",
    )


def test_pending_rejected_and_unsafe_core_memory_do_not_enter_provider_messages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path, monkeypatch)
    pending = service.propose(
        CoreMemoryCandidate(
            scope="workspace",
            workspace_id=service.workspace_id,
            section="project_profile",
            type="workflow",
            content="PENDING MEMORY MUST NOT LEAK",
        ),
        actor="test",
    ).memory
    rejected_candidate = service.propose(
        CoreMemoryCandidate(
            scope="workspace",
            workspace_id=service.workspace_id,
            section="project_profile",
            type="workflow",
            content="REJECTED MEMORY MUST NOT LEAK",
        ),
        actor="test",
    ).memory
    rejected = service.reject(rejected_candidate.id, actor="test", reason="not useful").memory
    unsafe = service.propose(
        CoreMemoryCandidate(
            scope="workspace",
            workspace_id=service.workspace_id,
            section="agent_notes",
            type="general",
            content="api_key = sk-testsecret1234567890",
        ),
        actor="test",
    ).memory

    pack = _pack(tmp_path, service.settings)
    provider_text = _provider_text(pack)

    assert pending.status == "pending"
    assert rejected.status == "rejected"
    assert unsafe.status == "rejected"
    assert "PENDING MEMORY MUST NOT LEAK" not in provider_text
    assert "REJECTED MEMORY MUST NOT LEAK" not in provider_text
    assert "sk-testsecret" not in provider_text
    assert not pack.markdown_memory


def test_approved_core_memory_reaches_provider_via_markdown_once_with_source_ref(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path, monkeypatch)
    result = service.propose(
        CoreMemoryCandidate(
            scope="workspace",
            workspace_id=service.workspace_id,
            section="project_profile",
            type="workflow",
            content="Approved workflow enters markdown memory exactly once.",
        ),
        actor="test",
    )
    approved = service.approve(result.memory.id, actor="reviewer", reason="verified")

    pack = _pack(tmp_path, service.settings)
    provider_text = _provider_text(pack)
    markdown_messages = [message for message in pack.final_messages if message.metadata.get("context_section") == "markdown_memory"]

    assert approved.memory.status == "active"
    assert approved.immediate_effect is True
    assert provider_text.count("Approved workflow enters markdown memory exactly once.") == 1
    assert len(markdown_messages) == 1
    source_ref = markdown_messages[0].metadata["source_ref"]
    assert source_ref["path"] == "MEMORY.md"
    assert result.memory.id in source_ref["metadata"]["marker_ids"]
    assert any(ref.path == "MEMORY.md" for ref in pack.source_refs)


def test_duplicate_core_memory_is_not_written_twice_to_markdown_or_final_messages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path, monkeypatch)
    first = service.propose(
        CoreMemoryCandidate(
            scope="workspace",
            workspace_id=service.workspace_id,
            section="project_profile",
            type="workflow",
            content="Use focused pytest before runtime edits.",
        )
    )
    service.approve(first.memory.id)
    duplicate = service.propose(
        CoreMemoryCandidate(
            scope="workspace",
            workspace_id=service.workspace_id,
            section="project_profile",
            type="workflow",
            content=" use focused pytest before runtime edits ",
        )
    )

    provider_text = _provider_text(_pack(tmp_path, service.settings))
    markdown_text = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")

    assert duplicate.duplicate_of == first.memory.id
    assert markdown_text.count("Use focused pytest before runtime edits.") == 1
    assert provider_text.count("Use focused pytest before runtime edits.") == 1


def test_conflicting_core_memory_is_auditable_before_markdown_injection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path, monkeypatch)
    old = service.propose(
        CoreMemoryCandidate(
            scope="workspace",
            workspace_id=service.workspace_id,
            section="project_profile",
            type="workflow",
            content="Run npm test before release.",
        )
    )
    service.approve(old.memory.id)

    conflict = service.propose(
        CoreMemoryCandidate(
            scope="workspace",
            workspace_id=service.workspace_id,
            section="project_profile",
            type="workflow",
            content="Run pnpm test before release.",
        ),
        reason="new project manager preference",
    )
    provider_text = _provider_text(_pack(tmp_path, service.settings))

    assert conflict.memory.status == "pending"
    assert conflict.conflicts_with == [old.memory.id]
    assert conflict.audit[0]["metadata"]["conflicts_with"] == [old.memory.id]
    assert "Run npm test before release." in provider_text
    assert "Run pnpm test before release." not in provider_text


def test_memory_layers_keep_stable_order_and_budget_drops_are_explained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    (tmp_path / "MEMORY.md").write_text("# Project Memory\n\nCore markdown memory wins budget.\n", encoding="utf-8")
    settings.context_pipeline.total_budget = 180
    settings.context_pipeline.section_budgets = {
        "markdown_memory": 120,
        "episodic_recall": 60,
        "file_memory_preview": 60,
        "conversation": 1000,
    }
    state = AgentState(system_prompt="system")
    state.messages = [
        ChatMessage(role="system", content=[TextPart(text="system")], timestamp=0.0),
        ChatMessage(
            role="system",
            content=[TextPart(text="Episodic memory " + "E" * 80)],
            metadata={"context_section": "episodic_recall", "source_type": "episodic_memory", "source_id": "episode-1"},
            timestamp=0.0,
        ),
        ChatMessage(
            role="system",
            content=[TextPart(text="File memory preview " + "F" * 80)],
            metadata={"context_section": "file_memory_preview", "source_type": "file_memory", "source_id": "file-1", "path": "memory/notes.md"},
            timestamp=0.0,
        ),
        ChatMessage(role="user", content=[TextPart(text="hello")], timestamp=1.0),
    ]

    pack = build_runtime_context_pack(state=state, messages=state.messages, settings=settings, session_id="session-1")
    sections = [message.metadata.get("context_section") for message in pack.final_messages]
    dropped = {item.id: item.reason for item in pack.budget_report.dropped_items}

    assert sections.index("markdown_memory") < sections.index("conversation")
    assert any(item.section in {"episodic_recall", "file_memory_preview"} for item in pack.budget_report.dropped_items)
    assert all(reason for reason in dropped.values())
    assert any(reason in {"total_budget_exceeded", "section_budget_exceeded"} for reason in dropped.values())


def test_file_memory_search_recalls_chunks_with_source_metadata_and_not_whole_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    settings.memory.file_memory_snippet_chars = 90
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "retrieval.md").write_text("# Retrieval\n\n" + ("alpha searchable memory chunk. " * 80), encoding="utf-8")

    result = memory_search_executor(tmp_path, {"query": "searchable memory", "top_k": 1, "include_debug": True}, settings=settings)
    hit = result.details["results"][0]

    assert result.is_error is False
    assert hit["path"] == "memory/retrieval.md"
    assert hit["line_start"] >= 1
    assert hit["line_end"] >= hit["line_start"]
    assert "score" in hit
    assert len(hit["snippet"]) <= 90
    assert len(hit["snippet"]) < len((memory_dir / "retrieval.md").read_text(encoding="utf-8"))


def test_file_memory_deleted_file_no_longer_high_confidence_recalls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    target = memory_dir / "stale.md"
    target.write_text("# Stale\noldmarker unique memory", encoding="utf-8")
    engine = FileMemorySearchEngine(
        store=build_file_memory_store(tmp_path, settings=settings),
        chunker=MarkdownFileChunker(target_chars=500),
        embedding_provider=NoopEmbeddingProvider(),
        vector_index=NoopFileMemoryVectorIndex(),
    )

    assert engine.search(FileMemorySearchRequest(query="oldmarker", mode="bm25")).results
    target.unlink()
    assert engine.search(FileMemorySearchRequest(query="oldmarker", mode="bm25")).results == []


def test_learning_and_episodic_memory_do_not_override_explicit_core_markdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    (tmp_path / "MEMORY.md").write_text("# Project Memory\n\nExplicit user preference: use pytest.\n", encoding="utf-8")
    state = AgentState(system_prompt="system")
    episodic = ContextItem(
        id="episode-conflict",
        type="episodic_memory",
        title="Old episode",
        content="Old episode says use unittest.",
        source_ref=SourceRef(source_type="episodic_memory", source_id="episode-conflict"),
        priority=70,
    )

    pack = build_runtime_context_pack(
        state=state,
        messages=_messages(),
        settings=settings,
        session_id="session-1",
    )
    with_episodic = ContextPipeline(context_pipeline_config_from_settings(settings)).build(
        user_message="test preference",
        memory_providers={"episodic_recall": [episodic]},
        workspace=tmp_path,
        global_root=settings.global_dir,
        settings=settings.learning,
    )

    assert "Explicit user preference: use pytest." in _provider_text(pack)
    assert _provider_text(with_episodic).index("Explicit user preference: use pytest.") < _provider_text(with_episodic).index("Old episode says use unittest.")
