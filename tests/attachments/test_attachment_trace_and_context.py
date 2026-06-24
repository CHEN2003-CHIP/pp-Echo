from pathlib import Path

from pp_agent.attachments.context import AttachmentContextHook, AttachmentContextProvider
from pp_agent.attachments.service import AttachmentService
from pp_agent.domain import ChatMessage, TextPart
from pp_agent.observability import TraceRecorder, TraceStore
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.tools.registry import ToolRegistry


def test_attachment_trace_spans_use_metadata_and_previews(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / ".pp-agent" / "traces")
    recorder = TraceRecorder(store, workspace=tmp_path)
    run_id = recorder.start_run(session_id="s1", user_goal_preview="attachment trace test")
    body = ("approval workflow\n" * 20 + "middle\n") + ("x" * 5000) + "FULL_CONTENT_TAIL_SHOULD_NOT_APPEAR"
    record = AttachmentService(tmp_path, observability=recorder).upload_bytes("s1", "trace.txt", body.encode("utf-8"))
    registry = ToolRegistry(tmp_path, current_session_id="s1", observability=recorder)
    search = registry.execute("search_attachment", {"query": "approval", "top_k": 1})
    chunk_id = search.details["results"][0]["chunk_id"]
    registry.execute("read_attachment_chunk", {"chunk_id": chunk_id})
    registry.execute("read_attachment_text", {"attachment_id": record.attachment_id})
    recorder.end_run()

    detail = store.read_run(run_id)
    names = [span.name for span in detail.spans]
    assert "attachment.upload" in names
    assert "attachment.search" in names
    assert "attachment.read_chunk" in names
    assert "attachment.read_text" in names
    assert any(span.name == "tool.call" and span.attributes.get("tool_name") == "search_attachment" for span in detail.spans)
    assert any(span.name == "tool.call" and span.attributes.get("tool_name") == "read_attachment_chunk" for span in detail.spans)
    assert any(span.name == "tool.call" and span.attributes.get("tool_name") == "read_attachment_text" for span in detail.spans)

    serialized = "\n".join(span.model_dump_json() for span in detail.spans)
    assert record.attachment_id in serialized
    assert "FULL_CONTENT_TAIL_SHOULD_NOT_APPEAR" not in serialized
    assert "text_length" in serialized


def test_attachment_inspect_trace_span_uses_metadata_not_full_content(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / ".pp-agent" / "traces")
    recorder = TraceRecorder(store, workspace=tmp_path)
    run_id = recorder.start_run(session_id="s1", user_goal_preview="attachment inspect trace test")
    body = "inspect preview\n" + ("x" * 3000) + "FULL_INSPECT_CONTENT_SHOULD_NOT_APPEAR"
    record = AttachmentService(tmp_path, observability=recorder).upload_bytes("s1", "inspect.txt", body.encode("utf-8"))

    payload = AttachmentService(tmp_path, observability=recorder).inspect("s1", record.attachment_id)
    recorder.end_run()

    detail = store.read_run(run_id)
    inspect_span = next(span for span in detail.spans if span.name == "attachment.inspect")
    assert inspect_span.attributes["attachment_id"] == record.attachment_id
    assert inspect_span.output["metadata_keys"]
    assert "preview" in inspect_span.output
    serialized = "\n".join(span.model_dump_json() for span in detail.spans)
    assert payload["attachment"]["text_preview"]
    assert "FULL_INSPECT_CONTENT_SHOULD_NOT_APPEAR" not in serialized


def test_attachment_context_injects_summary_not_full_content(tmp_path: Path) -> None:
    long_tail = "FULL_ATTACHMENT_BODY_SHOULD_NOT_BE_IN_PROMPT"
    AttachmentService(tmp_path).upload_bytes("s1", "context.txt", ("short preview\n" + ("x" * 3000) + long_tail).encode("utf-8"))
    messages = [
        ChatMessage(role="system", content=[TextPart(text="system")], timestamp=1.0),
        ChatMessage(role="user", content=[TextPart(text="question")], timestamp=2.0),
    ]

    transformed = AttachmentContextHook(tmp_path, "s1").transform_context(object(), messages)
    system_text = "\n".join(part.text for message in transformed if message.role == "system" for part in message.content)

    assert "Current session attachments:" in system_text
    assert "list_attachments" in system_text
    assert "inspect_attachment" in system_text
    assert "search_attachment" in system_text
    assert "read_attachment_text" in system_text
    assert "read_attachment_chunk" in system_text
    assert "read_attachment_range" in system_text
    assert "preview below is not full content" in system_text
    assert "context.txt" in system_text
    assert long_tail not in system_text


def test_attachment_context_provider_uses_record_metadata(tmp_path: Path) -> None:
    record = AttachmentService(tmp_path).upload_bytes("s1", "provider.txt", b"provider preview")

    item = AttachmentContextProvider(tmp_path, "s1").list_items()[0]

    assert item.id == f"attachment:{record.attachment_id}"
    assert item.metadata["context_section"] == "attachments"
    assert item.metadata["filename"] == "provider.txt"
    assert item.source_ref.source_type == "attachment"
    assert item.source_ref.source_id == record.attachment_id
    assert not item.content.startswith("Current session attachments:")


def test_runtime_attachment_trace_event_output_removes_full_text() -> None:
    output = AgentRuntime._attachment_trace_event_output(
        {
            "text": "short snippet" + ("x" * 1000),
            "chunk": {"chunk_id": "chk_1", "text": "nested full text" + ("y" * 1000)},
        }
    )

    assert "text" not in output
    assert "text" not in output["chunk"]
    assert output["text_length"] > 1000
    assert output["chunk"]["text_length"] > 1000
