from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def content_digest(content: str) -> str:
    """Return the stable SHA-256 digest used by sandbox and effect payloads."""

    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def is_protected_path(workspace: Path, target_path: Path) -> bool:
    """Return whether a path is protected from sandbox copy, diff, or apply."""

    resolved = target_path.resolve()
    try:
        rel = resolved.relative_to(workspace.resolve()).as_posix().lower()
    except ValueError:
        rel = resolved.name.lower()
    name = resolved.name.lower()
    if rel == ".env" or name == ".env":
        return True
    if name.startswith(".env."):
        return True
    if name.endswith(".pem") or name.endswith(".key"):
        return True
    return rel == ".pp-agent" or rel.startswith(".pp-agent/") or rel == ".git" or rel.startswith(".git/")


@dataclass(frozen=True)
class StructuredFileChange:
    """Describe one workspace-relative file change produced by a sandbox run."""

    path: str
    change_type: str
    old_digest: str | None
    new_digest: str | None
    content_text: str | None = None
    content_encoding: str = "utf-8"
    binary: bool = False
    truncated: bool = False
    size_bytes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-stable dictionary representation."""

        return asdict(self)


def bytes_digest(content: bytes) -> str:
    """Return the sha256 digest for raw file bytes."""

    return hashlib.sha256(content).hexdigest()


def normalize_structured_changes(changes: list[dict[str, Any]] | list[StructuredFileChange] | None) -> list[dict[str, Any]]:
    """Normalize structured changes into canonical JSON-compatible dictionaries."""

    normalized: list[dict[str, Any]] = []
    for item in changes or []:
        raw = item.to_dict() if isinstance(item, StructuredFileChange) else dict(item)
        normalized.append(
            {
                "path": str(raw.get("path") or ""),
                "change_type": str(raw.get("change_type") or ""),
                "old_digest": raw.get("old_digest"),
                "new_digest": raw.get("new_digest"),
                "content_text": raw.get("content_text"),
                "content_encoding": str(raw.get("content_encoding") or "utf-8"),
                "binary": bool(raw.get("binary")),
                "truncated": bool(raw.get("truncated")),
                "size_bytes": raw.get("size_bytes"),
            }
        )
    return normalized


def structured_changes_digest(changes: list[dict[str, Any]] | list[StructuredFileChange] | None) -> str:
    """Hash canonical structured change payloads for exact-effect binding."""

    normalized = normalize_structured_changes(changes)
    rendered = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()

