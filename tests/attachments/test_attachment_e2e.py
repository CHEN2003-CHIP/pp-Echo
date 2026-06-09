from pathlib import Path

import pytest

from pp_agent.attachments.service import AttachmentService
from pp_agent.attachments.tools import (
    InspectAttachmentTool,
    ListAttachmentsTool,
    ReadAttachmentChunkTool,
    ReadAttachmentRangeTool,
    SearchAttachmentTool,
)
from pp_agent.tools.registry import ToolRegistry


def test_attachment_system_end_to_end_across_core_file_types(tmp_path: Path) -> None:
    service = AttachmentService(tmp_path)
    records = [
        service.upload_bytes("s1", "note.txt", b"alpha approval workflow"),
        service.upload_bytes("s1", "guide.md", b"# Guide\n\napproval checklist"),
        service.upload_bytes("s1", "app.py", b"def run():\n    return 'approval code'\n"),
        service.upload_bytes("s1", "data.csv", b"name,count\napproval,2\nother,1\n"),
        service.upload_bytes("s1", "data.json", b'{"topic": "approval", "items": [1, 2]}'),
    ]

    listed = ListAttachmentsTool(tmp_path, current_session_id="s1").execute({})
    assert {item["attachment_id"] for item in listed.details["attachments"]} == {record.attachment_id for record in records}

    for record in records:
        inspected = InspectAttachmentTool(tmp_path, current_session_id="s1").execute({"attachment_id": record.attachment_id})
        assert inspected.details["attachment"]["status"] == "indexed"
        assert inspected.details["attachment"]["text_preview"]

    searched = SearchAttachmentTool(tmp_path, current_session_id="s1").execute({"query": "approval", "top_k": 5})
    assert searched.details["results"]

    chunk_id = searched.details["results"][0]["chunk_id"]
    chunk = ReadAttachmentChunkTool(tmp_path, current_session_id="s1").execute({"chunk_id": chunk_id})
    assert "approval" in chunk.content

    code_record = next(record for record in records if record.stored_filename == "app.py")
    range_result = ReadAttachmentRangeTool(tmp_path, current_session_id="s1").execute(
        {"attachment_id": code_record.attachment_id, "start_line": 1, "end_line": 2}
    )
    assert "def run" in range_result.content

    service.delete("s1", code_record.attachment_id)
    with pytest.raises(FileNotFoundError):
        ReadAttachmentRangeTool(tmp_path, current_session_id="s1").execute(
            {"attachment_id": code_record.attachment_id, "start_line": 1, "end_line": 1}
        )


def test_read_file_falls_back_to_same_named_session_attachment(tmp_path: Path) -> None:
    AttachmentService(tmp_path).upload_bytes("s1", "test.py", b"def run():\n    return 'uploaded attachment'\n")
    registry = ToolRegistry(tmp_path, current_session_id="s1")

    result = registry.execute("read_file", {"path": "test.py"})

    assert result.details["attachment_fallback"] is True
    assert "uploaded attachment" in result.content
