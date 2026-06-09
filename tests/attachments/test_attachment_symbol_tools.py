from pathlib import Path

import pytest

from pp_agent.attachments.service import AttachmentService
from pp_agent.attachments.tools import ReadAttachmentSymbolTool, SearchAttachmentSymbolsTool
from pp_agent.observability import TraceRecorder, TraceStore


def test_attachment_symbol_tools_search_and_read(tmp_path: Path) -> None:
    recorder = TraceRecorder(TraceStore(tmp_path / ".pp-agent" / "traces"), workspace=tmp_path)
    run_id = recorder.start_run(session_id="s1")
    record = AttachmentService(tmp_path, observability=recorder).upload_bytes(
        "s1",
        "runtime.py",
        b"class AgentRuntime:\n    def run_turn(self):\n        return 'SYMBOL_BODY_SHOULD_NOT_APPEAR_IN_TRACE'\n",
    )

    searched = SearchAttachmentSymbolsTool(tmp_path, current_session_id="s1", observability=recorder).execute({"query": "run_turn"})
    symbol = searched.details["symbols"][0]
    assert symbol["name"] == "run_turn"

    read = ReadAttachmentSymbolTool(tmp_path, current_session_id="s1", observability=recorder).execute(
        {"attachment_id": record.attachment_id, "symbol_id": symbol["symbol_id"]}
    )
    assert "run_turn" in read.content
    recorder.end_run()

    serialized = "\n".join(span.model_dump_json() for span in TraceStore(tmp_path / ".pp-agent" / "traces").read_run(run_id).spans)
    assert "attachment.symbol_search" in serialized
    assert "attachment.read_symbol" in serialized
    assert "SYMBOL_BODY_SHOULD_NOT_APPEAR_IN_TRACE" not in serialized


def test_deleted_attachment_cannot_read_symbol(tmp_path: Path) -> None:
    service = AttachmentService(tmp_path)
    record = service.upload_bytes("s1", "runtime.py", b"def run_turn():\n    return True\n")
    symbol_id = record.metadata["symbols"][0]["symbol_id"]
    service.delete("s1", record.attachment_id)

    with pytest.raises(FileNotFoundError):
        ReadAttachmentSymbolTool(tmp_path, current_session_id="s1").execute({"attachment_id": record.attachment_id, "symbol_id": symbol_id})
