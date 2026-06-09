from pathlib import Path

import pytest

from pp_agent.attachments.schema import AttachmentKind
from pp_agent.attachments.security import (
    detect_attachment_kind,
    safe_join_under_root,
    sanitize_filename,
    validate_upload_extension,
    validate_upload_size,
)


def test_sanitize_filename_removes_paths() -> None:
    assert sanitize_filename("../../notes.md") == "notes.md"
    with pytest.raises(ValueError):
        sanitize_filename("..")


def test_validate_rejects_dangerous_extension() -> None:
    with pytest.raises(ValueError):
        validate_upload_extension("run.ps1")


def test_detect_attachment_kind() -> None:
    assert detect_attachment_kind("app.py") == AttachmentKind.CODE
    assert detect_attachment_kind("table.csv") == AttachmentKind.CSV


def test_safe_join_under_root_blocks_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        safe_join_under_root(tmp_path, "..", "outside.txt")


def test_validate_upload_size_limit() -> None:
    with pytest.raises(ValueError):
        validate_upload_size(11 * 1024 * 1024)
