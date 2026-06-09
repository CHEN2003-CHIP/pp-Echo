from pathlib import Path

from pp_agent.attachments.service import AttachmentService
from pp_agent.attachments.tools import ListAttachmentsTool, ReadAttachmentChunkTool, ReadAttachmentRangeTool, ReadAttachmentTextTool, SearchAttachmentTool


def test_attachment_tools_read_uploaded_text(tmp_path: Path) -> None:
    service = AttachmentService(tmp_path)
    record = service.upload_bytes("s1", "note.txt", b"hello approval workflow\nsecond line")

    listed = ListAttachmentsTool(tmp_path, current_session_id="s1").execute({})
    searched = SearchAttachmentTool(tmp_path, current_session_id="s1").execute({"query": "approval"})
    chunk_id = searched.details["results"][0]["chunk_id"]
    chunk = ReadAttachmentChunkTool(tmp_path, current_session_id="s1").execute({"chunk_id": chunk_id})
    text_result = ReadAttachmentTextTool(tmp_path, current_session_id="s1").execute({"attachment_id": record.attachment_id})
    range_result = ReadAttachmentRangeTool(tmp_path, current_session_id="s1").execute({"attachment_id": record.attachment_id, "start_line": 2, "end_line": 2})

    assert listed.details["attachments"][0]["attachment_id"] == record.attachment_id
    assert "approval" in chunk.content
    assert "approval workflow" in text_result.content
    assert "second line" in range_result.content


def test_read_attachment_text_can_continue_beyond_preview(tmp_path: Path) -> None:
    service = AttachmentService(tmp_path)
    body = "\n".join(
        [
            "项目经历 1: Pp-Echo",
            "x" * 3000,
            "项目经历 2: Attachment System",
            "项目经历 3: TraceInspect",
        ]
    )
    record = service.upload_bytes("s1", "resume.md", body.encode("utf-8"))

    first = ReadAttachmentTextTool(tmp_path, current_session_id="s1").execute({"attachment_id": record.attachment_id, "max_chars": 2000})
    next_offset = first.details["next_offset"]
    second = ReadAttachmentTextTool(tmp_path, current_session_id="s1").execute({"attachment_id": record.attachment_id, "offset": next_offset, "max_chars": 5000})

    assert "项目经历 1" in first.content
    assert "项目经历 2" in second.content
    assert "项目经历 3" in second.content
