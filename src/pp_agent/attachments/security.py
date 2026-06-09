from __future__ import annotations

import re
from pathlib import Path

from pp_agent.attachments.schema import AttachmentKind

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_CONFIGURED_UPLOAD_BYTES = 50 * 1024 * 1024

ALLOWED_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".go",
    ".rs",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".json",
    ".yaml",
    ".yml",
    ".csv",
    ".log",
    ".pdf",
    ".docx",
}
DANGEROUS_EXTENSIONS = {".exe", ".dll", ".bat", ".ps1", ".sh", ".so", ".dylib", ".msi", ".zip", ".rar", ".7z"}
CODE_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".cpp", ".c", ".h", ".hpp"}


def sanitize_filename(filename: str) -> str:
    """清理上传文件名，移除路径穿越、控制字符和平台保留分隔符。"""

    raw = str(filename or "attachment").replace("\x00", "").strip()
    if raw in {".", ".."}:
        raise ValueError("Invalid attachment filename")
    name = Path(str(filename or "attachment")).name.strip().replace("\x00", "")
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = "attachment"
    if name in {".", ".."} or ".." in Path(name).parts:
        raise ValueError("Invalid attachment filename")
    return name[:180]


def detect_attachment_kind(filename: str, content_type: str | None = None) -> AttachmentKind:
    """根据扩展名和 content type 识别附件类型，供解析器选择低风险处理路径。"""

    suffix = Path(filename).suffix.lower()
    if suffix in {".txt"}:
        return AttachmentKind.TEXT
    if suffix in {".md", ".markdown"}:
        return AttachmentKind.MARKDOWN
    if suffix in CODE_EXTENSIONS:
        return AttachmentKind.CODE
    if suffix == ".csv":
        return AttachmentKind.CSV
    if suffix == ".json":
        return AttachmentKind.JSON
    if suffix in {".yaml", ".yml"}:
        return AttachmentKind.YAML
    if suffix == ".log":
        return AttachmentKind.LOG
    if suffix == ".pdf":
        return AttachmentKind.PDF
    if suffix == ".docx":
        return AttachmentKind.DOCX
    if content_type and content_type.startswith("image/"):
        return AttachmentKind.IMAGE
    return AttachmentKind.BINARY if suffix else AttachmentKind.UNKNOWN


def validate_upload_size(size_bytes: int, limit_bytes: int = MAX_UPLOAD_BYTES) -> None:
    """校验单文件大小，默认 10MB，允许调用方显式放宽但不超过 50MB。"""

    limit = min(max(1, int(limit_bytes)), MAX_CONFIGURED_UPLOAD_BYTES)
    if size_bytes > limit:
        raise ValueError(f"Attachment exceeds {limit} bytes")


def is_executable_or_dangerous(filename: str) -> bool:
    """判断附件是否属于默认拒绝的可执行文件、脚本或压缩包类型。"""

    return Path(filename).suffix.lower() in DANGEROUS_EXTENSIONS


def validate_upload_extension(filename: str) -> None:
    """校验上传扩展名，第一版仅允许文本、文档和常见代码数据文件。"""

    suffix = Path(filename).suffix.lower()
    if is_executable_or_dangerous(filename):
        raise ValueError(f"Attachment type {suffix} is not allowed")
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Attachment extension {suffix or '<none>'} is not supported")


def safe_join_under_root(root: Path, *parts: str) -> Path:
    """在受控根目录下拼接路径，并拒绝任何逃逸到根目录之外的结果。"""

    resolved_root = root.resolve()
    target = resolved_root.joinpath(*parts).resolve()
    if target != resolved_root and resolved_root not in target.parents:
        raise ValueError("Attachment path escapes storage root")
    return target
