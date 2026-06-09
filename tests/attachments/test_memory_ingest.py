import json
from pathlib import Path

import pytest

from pp_agent.attachments.memory_ingest import AttachmentMemoryIngestor
from pp_agent.attachments.service import AttachmentService
from pp_agent.observability import TraceRecorder, TraceStore


def test_memory_ingest_preview_does_not_write_memory(tmp_path: Path) -> None:
    record = AttachmentService(tmp_path).upload_bytes("s1", "guide.md", b"# Guide\n\napproval memory")
    ingestor = AttachmentMemoryIngestor(tmp_path)

    preview = ingestor.preview("s1", record.attachment_id)

    assert preview["chunk_count"] == 1
    assert not ingestor.memory_path.exists()


def test_memory_ingest_writes_metadata_and_selected_chunks(tmp_path: Path) -> None:
    record = AttachmentService(tmp_path).upload_bytes("s1", "guide.md", b"# Guide\n\napproval memory")
    chunk_id = record.metadata["chunk_count"] and "chk_" + record.attachment_id.removeprefix("att_") + "_0001"
    ingestor = AttachmentMemoryIngestor(tmp_path)

    result = ingestor.ingest("s1", record.attachment_id, mode="selected_chunks", chunk_ids=[chunk_id], tags=["attachment", "guide"], scope="workspace")

    assert result["memory_items_created"] == 1
    item = json.loads(ingestor.memory_path.read_text(encoding="utf-8").splitlines()[0])
    assert item["metadata"]["source_type"] == "attachment"
    assert item["metadata"]["attachment_id"] == record.attachment_id
    assert item["metadata"]["chunk_id"] == chunk_id
    assert item["metadata"]["source_ref"]
    assert item["metadata"]["tags"] == ["attachment", "guide"]


def test_memory_ingest_all_chunks_honors_max_chunks(tmp_path: Path) -> None:
    body = "\n\n".join(f"approval memory {index}" for index in range(400))
    record = AttachmentService(tmp_path).upload_bytes("s1", "long.txt", body.encode("utf-8"))

    result = AttachmentMemoryIngestor(tmp_path).ingest("s1", record.attachment_id, mode="all_chunks", max_chunks=1)

    assert result["memory_items_created"] == 1


def test_deleted_attachment_cannot_ingest(tmp_path: Path) -> None:
    service = AttachmentService(tmp_path)
    record = service.upload_bytes("s1", "guide.md", b"approval memory")
    service.delete("s1", record.attachment_id)

    with pytest.raises(FileNotFoundError):
        AttachmentMemoryIngestor(tmp_path).preview("s1", record.attachment_id)


def test_memory_ingest_trace_does_not_record_full_text(tmp_path: Path) -> None:
    recorder = TraceRecorder(TraceStore(tmp_path / ".pp-agent" / "traces"), workspace=tmp_path)
    run_id = recorder.start_run(session_id="s1")
    record = AttachmentService(tmp_path, observability=recorder).upload_bytes(
        "s1",
        "guide.md",
        b"# Guide\n\napproval memory\nxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\nFULL_MEMORY_CONTENT_SHOULD_NOT_APPEAR",
    )
    AttachmentMemoryIngestor(tmp_path, observability=recorder).ingest("s1", record.attachment_id, mode="all_chunks")
    recorder.end_run()

    serialized = "\n".join(span.model_dump_json() for span in TraceStore(tmp_path / ".pp-agent" / "traces").read_run(run_id).spans)
    assert "attachment.memory_ingest" in serialized
    assert "FULL_MEMORY_CONTENT_SHOULD_NOT_APPEAR" not in serialized
