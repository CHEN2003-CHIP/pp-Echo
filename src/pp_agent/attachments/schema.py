from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AttachmentStatus(str, Enum):
    """描述会话附件在上传、解析、切块、索引和删除过程中的状态。"""

    UPLOADED = "uploaded"
    EXTRACTED = "extracted"
    CHUNKED = "chunked"
    INDEXED = "indexed"
    FAILED = "failed"
    DELETED = "deleted"


class AttachmentKind(str, Enum):
    """描述附件的内容类型，供解析器、检索器和 Web UI 选择处理策略。"""

    TEXT = "text"
    MARKDOWN = "markdown"
    CODE = "code"
    PDF = "pdf"
    DOCX = "docx"
    CSV = "csv"
    JSON = "json"
    YAML = "yaml"
    LOG = "log"
    IMAGE = "image"
    BINARY = "binary"
    UNKNOWN = "unknown"


class AttachmentRecord(BaseModel):
    """记录一个 session-scoped attachment 的审计元数据，不暴露本机绝对路径。"""

    attachment_id: str
    session_id: str
    original_filename: str
    stored_filename: str
    relative_dir: str
    original_path: str
    content_type: Optional[str] = None
    kind: AttachmentKind
    size_bytes: int
    sha256: str
    created_at: float
    status: AttachmentStatus
    text_preview: str = ""
    extracted_text_path: Optional[str] = None
    chunks_path: Optional[str] = None
    index_path: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class AttachmentChunk(BaseModel):
    """保存从附件抽取出来的一段可按需读取的文本及其来源范围。"""

    chunk_id: str
    attachment_id: str
    session_id: str
    filename: str
    kind: AttachmentKind
    text: str
    token_estimate: int
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    heading_path: List[str] = Field(default_factory=list)
    source_ref: Optional[str] = None
    section_title: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AttachmentSearchResult(BaseModel):
    """表示关键词检索命中的 chunk 摘要，返回给工具和 HTTP API。"""

    chunk_id: str
    attachment_id: str
    filename: str
    score: float
    match_type: str
    snippet: str
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    source_ref: Optional[str] = None
    section_title: Optional[str] = None
