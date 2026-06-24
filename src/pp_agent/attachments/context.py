from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from pp_agent.attachments.schema import AttachmentRecord
from pp_agent.attachments.service import AttachmentService
from pp_agent.context.item import ContextItem
from pp_agent.context.source_ref import SourceRef
from pp_agent.domain import ChatMessage, TextPart


MAX_ATTACHMENT_CONTEXT_ITEMS = 8


class AttachmentContextProvider:
    """Turns attachment records into ContextItems without parsing legacy prompt text."""

    def __init__(self, workspace: Path, session_id: str, *, limit: int = MAX_ATTACHMENT_CONTEXT_ITEMS) -> None:
        self.workspace = workspace.resolve()
        self.session_id = session_id
        self.limit = limit

    def list_items(self) -> list[ContextItem]:
        records = AttachmentService(self.workspace).list(self.session_id)[: self.limit]
        return [_record_to_context_item(record) for record in records]

    def __call__(self, **_: object) -> list[ContextItem]:
        return self.list_items()


class AttachmentContextHook:
    """Legacy hook that injects attachment previews while tagging them for ContextPipeline."""

    def __init__(self, workspace: Path, session_id: str) -> None:
        self.workspace = workspace.resolve()
        self.session_id = session_id

    def transform_context(self, state: Any, messages: list[ChatMessage]) -> list[ChatMessage]:
        service = AttachmentService(self.workspace)
        records = service.list(self.session_id)[:MAX_ATTACHMENT_CONTEXT_ITEMS]
        summary = service.context_summary(self.session_id, limit=MAX_ATTACHMENT_CONTEXT_ITEMS)
        if not summary:
            return messages
        context = ChatMessage(
            role="system",
            content=[TextPart(text=summary)],
            timestamp=time.time(),
            metadata={
                "context_section": "attachments",
                "context_type": "attachment_preview",
                "source_type": "attachment",
                "source_id": "session_attachments",
                "attachment_ids": [record.attachment_id for record in records],
                "filenames": [record.stored_filename for record in records],
                "original_filenames": [record.original_filename for record in records],
                "kinds": [record.kind.value for record in records],
                "chunk_counts": [int(record.metadata.get("chunk_count") or 0) for record in records],
                "truncated": False,
                "preview_only": True,
            },
        )
        return [messages[0], context, *messages[1:]] if messages and messages[0].role == "system" else [context, *messages]


def _record_to_context_item(record: AttachmentRecord) -> ContextItem:
    chunk_count = int(record.metadata.get("chunk_count") or 0)
    text_length = int(record.metadata.get("text_length") or 0)
    preview = record.text_preview[:240]
    content = (
        f"filename={record.stored_filename}; original_name={record.original_filename}; "
        f"kind={record.kind.value}; status={record.status.value}; chunks={chunk_count}; "
        f"text_length={text_length}; preview_only=true; preview={preview}"
    )
    return ContextItem(
        id=f"attachment:{record.attachment_id}",
        type="attachment_preview",
        title=record.stored_filename,
        content=content,
        source_ref=SourceRef(
            source_type="attachment",
            source_id=record.attachment_id,
            path=record.relative_dir,
            metadata={
                "filename": record.stored_filename,
                "original_filename": record.original_filename,
                "kind": record.kind.value,
                "mime": record.content_type,
                "chunk_count": chunk_count,
                "text_length": text_length,
                "truncated": False,
                "preview_only": True,
            },
        ),
        priority=65,
        metadata={
            "context_section": "attachments",
            "attachment_id": record.attachment_id,
            "filename": record.stored_filename,
            "original_filename": record.original_filename,
            "kind": record.kind.value,
            "mime": record.content_type,
            "chunk_count": chunk_count,
            "text_length": text_length,
            "truncated": False,
            "preview_only": True,
        },
    )
