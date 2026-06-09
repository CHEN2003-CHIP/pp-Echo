from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path

from pp_agent.attachments.schema import AttachmentRecord, AttachmentStatus
from pp_agent.attachments.security import safe_join_under_root, sanitize_filename


class AttachmentStore:
    """管理 .pp-agent/sessions/<session_id>/attachments 下的文件布局和 manifest。"""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.root = self.workspace / ".pp-agent" / "sessions"

    def session_root(self, session_id: str) -> Path:
        """返回指定 session 的附件根目录，并保证目录存在。"""

        root = safe_join_under_root(self.root, session_id, "attachments")
        root.mkdir(parents=True, exist_ok=True)
        return root

    def create_attachment_dir(self, session_id: str) -> tuple[str, Path]:
        """创建以短 UUID 隔离的 attachment 目录，避免同名文件覆盖。"""

        attachment_id = f"att_{uuid.uuid4().hex[:10]}"
        directory = safe_join_under_root(self.session_root(session_id), attachment_id)
        (directory / "original").mkdir(parents=True, exist_ok=False)
        return attachment_id, directory

    def save_original(self, session_id: str, filename: str, data: bytes, *, content_type: str | None, kind) -> AttachmentRecord:
        """保存上传原件并写入初始 manifest，文件不会进入 workspace 根目录。"""

        safe_name = sanitize_filename(filename)
        attachment_id, directory = self.create_attachment_dir(session_id)
        original_path = directory / "original" / safe_name
        original_path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        relative_dir = f".pp-agent/sessions/{session_id}/attachments/{attachment_id}"
        record = AttachmentRecord(
            attachment_id=attachment_id,
            session_id=session_id,
            original_filename=filename,
            stored_filename=safe_name,
            relative_dir=relative_dir,
            original_path=f"{relative_dir}/original/{safe_name}",
            content_type=content_type,
            kind=kind,
            size_bytes=len(data),
            sha256=digest,
            created_at=time.time(),
            status=AttachmentStatus.UPLOADED,
        )
        self.write_manifest(record)
        return record

    def attachment_dir(self, record: AttachmentRecord) -> Path:
        """根据 manifest 中的相对目录定位附件目录，并校验不逃逸存储根。"""

        return safe_join_under_root(self.workspace, *record.relative_dir.split("/"))

    def manifest_path(self, session_id: str, attachment_id: str) -> Path:
        """返回 manifest.json 路径，供读写 record 使用。"""

        return safe_join_under_root(self.session_root(session_id), attachment_id, "manifest.json")

    def write_manifest(self, record: AttachmentRecord) -> None:
        """写入 AttachmentRecord manifest，作为附件状态的单一事实来源。"""

        path = self.manifest_path(record.session_id, record.attachment_id)
        path.write_text(json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, session_id: str, attachment_id: str) -> AttachmentRecord:
        """读取指定附件 manifest；不存在时抛出 FileNotFoundError。"""

        return AttachmentRecord.model_validate_json(self.manifest_path(session_id, attachment_id).read_text(encoding="utf-8"))

    def list(self, session_id: str, *, include_deleted: bool = False) -> list[AttachmentRecord]:
        """列出 session 下所有附件，默认隐藏 deleted 状态。"""

        root = self.session_root(session_id)
        records: list[AttachmentRecord] = []
        for manifest in sorted(root.glob("att_*/manifest.json")):
            record = AttachmentRecord.model_validate_json(manifest.read_text(encoding="utf-8"))
            if not include_deleted and record.status == AttachmentStatus.DELETED:
                continue
            records.append(record)
        return sorted(records, key=lambda item: item.created_at, reverse=True)
