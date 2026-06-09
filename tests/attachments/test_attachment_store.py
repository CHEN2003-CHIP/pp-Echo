from pathlib import Path

from pp_agent.attachments.schema import AttachmentKind, AttachmentStatus
from pp_agent.attachments.store import AttachmentStore


def test_store_saves_manifest_under_session(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path)
    record = store.save_original("sess1", "note.txt", b"hello", content_type="text/plain", kind=AttachmentKind.TEXT)

    assert record.status == AttachmentStatus.UPLOADED
    assert record.original_path.startswith(".pp-agent/sessions/sess1/attachments/")
    assert (tmp_path / record.original_path).exists()
    assert store.load("sess1", record.attachment_id).sha256 == record.sha256
