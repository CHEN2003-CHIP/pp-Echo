from __future__ import annotations

import hashlib
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from pp_agent.attachments.schema import AttachmentRecord
from pp_agent.attachments.service import AttachmentService
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.tools.effects import content_digest, payload_digest, stable_path_label


class AttachmentWorkspaceImporter:
    """
    负责将 session-scoped attachment 安全导入 workspace。

    上传附件默认只保存在 .pp-agent/sessions/<session_id>/attachments/
    目录下，不会直接污染用户项目。该类负责校验目标路径、生成导入预览、
    计算 effect digest，并把真正的写文件动作交给 Approval Gate。

    只有审批通过后，附件才会被复制到 workspace。这样可以保证文件导入
    不会绕过 pp-Echo 的安全审批、TraceInspect 审计和回退设计。
    """

    def __init__(self, workspace: Path, *, observability: Any | None = None) -> None:
        self.workspace = workspace.resolve()
        self.service = AttachmentService(self.workspace, observability=observability)
        self.observability = observability

    def preview_import(self, session_id: str, attachment_id: str, *, target_path: str, overwrite: bool = False) -> dict[str, Any]:
        """生成附件导入预览，只返回路径、hash 和 effect 摘要，不写 workspace。"""

        started = time.time()
        record = self.service._require_active(session_id, attachment_id)
        target = self.validate_target_path(target_path)
        would_overwrite = target.exists()
        if would_overwrite and not overwrite:
            self._record_span("attachment.import_preview", started, record, target, overwrite, would_overwrite, status="rejected")
            raise ValueError("Target file already exists. Set overwrite=true to stage an import.")
        effect = self.build_import_effect(record, target, overwrite=overwrite)
        payload = self._preview_payload(record, target, overwrite, would_overwrite, effect)
        self._record_span("attachment.import_preview", started, record, target, overwrite, would_overwrite, effect_digest=effect["payload_digest"])
        return payload

    def request_import(self, session_id: str, attachment_id: str, *, target_path: str, overwrite: bool = False) -> dict[str, Any]:
        """创建待审批导入动作；该方法不会复制附件原文，只写 pending action。"""

        started = time.time()
        record = self.service._require_active(session_id, attachment_id)
        target = self.validate_target_path(target_path)
        would_overwrite = target.exists()
        if would_overwrite and not overwrite:
            self._record_span("attachment.import_requested", started, record, target, overwrite, would_overwrite, status="rejected")
            raise ValueError("Target file already exists. Set overwrite=true to stage an import.")
        original = self.original_path(record)
        before = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
        effect = self.build_import_effect(record, target, overwrite=overwrite)
        store = PendingActionStore(self.workspace / ".pp-agent" / "pending-edits")
        payload = store.stage(
            action_type="attachment_import",
            target_path=target,
            before=before,
            after="",
            details={
                "session_id": session_id,
                "attachment_id": record.attachment_id,
                "filename": record.stored_filename,
                "source_path": str(original),
                "target_path": str(target),
                "overwrite": overwrite,
                "would_overwrite": would_overwrite,
                "size_bytes": record.size_bytes,
                "sha256": record.sha256,
            },
            effect=effect,
            session_id=session_id,
            origin={"source": "attachment", "kind": "workspace_import"},
        )
        result = {**self._preview_payload(record, target, overwrite, would_overwrite, effect), "token": payload["token"], "approval_id": payload["token"], "staged": True}
        self._record_span(
            "attachment.import_requested",
            started,
            record,
            target,
            overwrite,
            would_overwrite,
            effect_digest=effect["payload_digest"],
            approval_id=payload["token"],
        )
        return result

    def validate_target_path(self, target_path: str) -> Path:
        """校验目标路径必须位于 workspace 内，并拒绝绝对路径和路径穿越。"""

        raw = str(target_path or "").strip().replace("\\", "/")
        if not raw:
            raise ValueError("target_path is required")
        path = Path(raw)
        if path.is_absolute() or any(part == ".." for part in path.parts):
            raise ValueError("Attachment import target must be a relative path inside the workspace.")
        resolved = (self.workspace / path).resolve()
        if resolved != self.workspace and self.workspace not in resolved.parents:
            raise ValueError("Attachment import target escapes the workspace.")
        if ".pp-agent" in resolved.relative_to(self.workspace).parts:
            raise ValueError("Attachment import target may not write inside .pp-agent.")
        return resolved

    def build_import_effect(self, record: AttachmentRecord, target: Path, *, overwrite: bool = False, effect_id: str | None = None, created_at: float | None = None) -> dict[str, Any]:
        """构建 Approval Gate 使用的确定性 effect，摘要中不包含完整文件内容。"""

        baseline = {"kind": "absent"} if not target.exists() else {"kind": "present", "content_digest": content_digest(target.read_text(encoding="utf-8", errors="replace"))}
        normalized_arguments = {
            "path": stable_path_label(self.workspace, target),
            "attachment_id": record.attachment_id,
            "filename": record.stored_filename,
            "sha256": record.sha256,
            "size_bytes": record.size_bytes,
            "overwrite": overwrite,
        }
        analysis = {
            "family": "file",
            "permission_domain": "edit",
            "risk_class": "workspace_mutation",
            "summary": f"Import attachment to {stable_path_label(self.workspace, target)}",
            "confidence_band": "high",
            "confidence_score": 0.98,
            "touches_workspace": True,
            "touches_external": False,
            "requests_network": False,
            "destructive_hint": bool(overwrite),
            "protected_path_hint": False,
            "known_safe_inspect": False,
            "path": stable_path_label(self.workspace, target),
        }
        return {
            "effect_id": effect_id or str(uuid.uuid4()),
            "permission_domain": "edit",
            "tool_name": "attachment_import",
            "normalized_arguments": normalized_arguments,
            "analysis": analysis,
            "summary": analysis["summary"],
            "payload_digest": payload_digest("edit", "attachment_import", normalized_arguments, baseline),
            "created_at": created_at or time.time(),
            "baseline": baseline,
        }

    def complete_import_after_approval(self, details: dict[str, Any]) -> dict[str, Any]:
        """由 Approval 执行器在 grant 有效后调用，真正把原始附件复制到 workspace。"""

        source = Path(str(details.get("source_path") or "")).resolve()
        target = Path(str(details.get("target_path") or "")).resolve()
        if target != self.workspace and self.workspace not in target.parents:
            raise ValueError("Attachment import target escapes the workspace.")
        if not source.exists():
            raise FileNotFoundError("Attachment source file is missing.")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return {"path": str(target), "absolute_path": str(target), "persisted": True}

    def original_path(self, record: AttachmentRecord) -> Path:
        """返回附件原始文件路径，并保证路径仍在 attachment store 内。"""

        return self.service.store.attachment_dir(record) / "original" / record.stored_filename

    def _preview_payload(self, record: AttachmentRecord, target: Path, overwrite: bool, would_overwrite: bool, effect: dict[str, Any]) -> dict[str, Any]:
        return {
            "attachment_id": record.attachment_id,
            "filename": record.stored_filename,
            "target_path": stable_path_label(self.workspace, target),
            "would_overwrite": would_overwrite,
            "overwrite": overwrite,
            "size_bytes": record.size_bytes,
            "sha256": record.sha256,
            "requires_approval": True,
            "effect_preview": {"kind": "write_file", "path": stable_path_label(self.workspace, target), "digest": effect["payload_digest"]},
        }

    def _record_span(self, name: str, started: float, record: AttachmentRecord, target: Path, overwrite: bool, would_overwrite: bool, *, effect_digest: str | None = None, approval_id: str | None = None, status: str = "ok") -> None:
        record_completed_span = getattr(self.observability, "record_completed_span", None)
        if not callable(record_completed_span):
            return
        record_completed_span(
            name,
            "tool",
            status="ok" if status == "ok" else "error",
            started_at=started,
            ended_at=time.time(),
            attributes={
                "attachment_id": record.attachment_id,
                "filename": record.stored_filename,
                "target_path": stable_path_label(self.workspace, target),
                "overwrite": overwrite,
                "would_overwrite": would_overwrite,
                "size_bytes": record.size_bytes,
                "sha256": record.sha256,
                "effect_digest": effect_digest,
                "approval_id": approval_id,
                "status": status,
            },
            output={"status": status, "approval_id": approval_id, "effect_digest": effect_digest},
        )
