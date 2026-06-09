from pathlib import Path

import pytest

from pp_agent.attachments.importer import AttachmentWorkspaceImporter
from pp_agent.attachments.service import AttachmentService
from pp_agent.observability import TraceRecorder, TraceStore
from pp_agent.tools.registry import ToolRegistry


def test_attachment_import_preview_and_approval_flow(tmp_path: Path) -> None:
    recorder = TraceRecorder(TraceStore(tmp_path / ".pp-agent" / "traces"), workspace=tmp_path)
    run_id = recorder.start_run(session_id="s1")
    record = AttachmentService(tmp_path, observability=recorder).upload_bytes(
        "s1",
        "spec.md",
        b"# Spec\n\napproval import body\nFULL_IMPORT_CONTENT_SHOULD_NOT_APPEAR",
    )
    importer = AttachmentWorkspaceImporter(tmp_path, observability=recorder)

    preview = importer.preview_import("s1", record.attachment_id, target_path="docs/spec.md")
    assert preview["requires_approval"] is True
    assert preview["would_overwrite"] is False
    assert not (tmp_path / "docs" / "spec.md").exists()

    staged = importer.request_import("s1", record.attachment_id, target_path="docs/spec.md")
    assert staged["staged"] is True
    assert not (tmp_path / "docs" / "spec.md").exists()

    ToolRegistry(tmp_path).host_execute("approve_pending_action", {"token": staged["token"]})
    assert (tmp_path / "docs" / "spec.md").read_text(encoding="utf-8").startswith("# Spec")
    recorder.end_run()

    serialized = "\n".join(span.model_dump_json() for span in TraceStore(tmp_path / ".pp-agent" / "traces").read_run(run_id).spans)
    assert "attachment.import_preview" in serialized
    assert "attachment.import_requested" in serialized
    assert "FULL_IMPORT_CONTENT_SHOULD_NOT_APPEAR" not in serialized


@pytest.mark.parametrize("target_path", ["../outside.md", "../../x", str(Path("/tmp/outside.md"))])
def test_attachment_import_rejects_unsafe_paths(tmp_path: Path, target_path: str) -> None:
    record = AttachmentService(tmp_path).upload_bytes("s1", "spec.md", b"body")
    importer = AttachmentWorkspaceImporter(tmp_path)

    with pytest.raises(ValueError):
        importer.preview_import("s1", record.attachment_id, target_path=target_path)


def test_attachment_import_rejects_existing_target_without_overwrite(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "spec.md").write_text("existing", encoding="utf-8")
    record = AttachmentService(tmp_path).upload_bytes("s1", "spec.md", b"body")

    with pytest.raises(ValueError):
        AttachmentWorkspaceImporter(tmp_path).request_import("s1", record.attachment_id, target_path="docs/spec.md")


def test_deleted_attachment_cannot_be_imported(tmp_path: Path) -> None:
    service = AttachmentService(tmp_path)
    record = service.upload_bytes("s1", "spec.md", b"body")
    service.delete("s1", record.attachment_id)

    with pytest.raises(FileNotFoundError):
        AttachmentWorkspaceImporter(tmp_path).request_import("s1", record.attachment_id, target_path="docs/spec.md")
