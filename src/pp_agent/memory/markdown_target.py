from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field, field_validator


MarkdownMemoryFileKind = Literal["global_memory", "workspace_memory", "detailed_memory"]
MarkdownMemoryOperation = Literal["append", "replace", "merge"]

SECRET_METADATA_KEYS = re.compile(r"(api[_-]?key|secret|token|password)", re.IGNORECASE)


class MarkdownMemoryTarget(BaseModel):
    file_kind: MarkdownMemoryFileKind
    path: str
    heading: str
    operation: MarkdownMemoryOperation = "append"
    marker_id: str
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    metadata: Dict[str, object] = Field(default_factory=dict)

    @field_validator("path")
    @classmethod
    def _path_is_relative_markdown(cls, value: str) -> str:
        raw = str(value or "").replace("\\", "/").strip()
        if not raw or raw.startswith("/") or Path(raw).is_absolute():
            raise ValueError("markdown memory path must be relative")
        parts = [part for part in raw.split("/") if part not in {"", "."}]
        if any(part == ".." for part in parts):
            raise ValueError("markdown memory path cannot escape memory roots")
        if not raw.endswith(".md"):
            raise ValueError("markdown memory path must be a Markdown file")
        return "/".join(parts)

    @field_validator("heading", "marker_id")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("markdown memory target text cannot be empty")
        return text

    @field_validator("metadata")
    @classmethod
    def _metadata_has_no_secret_keys(cls, value: Dict[str, object]) -> Dict[str, object]:
        for key in value:
            if SECRET_METADATA_KEYS.search(str(key)):
                raise ValueError("markdown memory metadata cannot contain secret-like keys")
        return value


class MarkdownMemoryPatch(BaseModel):
    target: MarkdownMemoryTarget
    before: str
    after: str
    diff: str
    content_hash_before: str
    content_hash_after: str
    applied: bool = False
    metadata: Dict[str, object] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _metadata_has_no_secret_keys(cls, value: Dict[str, object]) -> Dict[str, object]:
        for key in value:
            if SECRET_METADATA_KEYS.search(str(key)):
                raise ValueError("markdown memory patch metadata cannot contain secret-like keys")
        return value


def content_hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = [
    "MarkdownMemoryFileKind",
    "MarkdownMemoryOperation",
    "MarkdownMemoryPatch",
    "MarkdownMemoryTarget",
    "content_hash",
]
