from __future__ import annotations

import re
from pathlib import Path


def read_text_lossy(path: Path, limit_chars: int | None = None) -> str:
    """用常见编码读取文本附件，失败时以替换字符降级，避免解析流程崩溃。"""

    data = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("utf-8", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text[:limit_chars] if limit_chars is not None else text


def estimate_tokens(text: str) -> int:
    """用轻量字符估算 token 数，避免引入 tokenizer 依赖。"""

    return max(1, len(text) // 4) if text.strip() else 0


def preview_text(text: str, limit: int = 600) -> str:
    """生成 UI、manifest 和 Trace 使用的短预览，不保存完整大文本。"""

    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:limit]


def split_with_overlap(text: str, target_chars: int, overlap_chars: int) -> list[tuple[int, int, str]]:
    """按字符窗口切分长文本，并保留少量重叠以减少检索上下文断裂。"""

    clean = text.strip()
    if not clean:
        return []
    spans: list[tuple[int, int, str]] = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + target_chars)
        if end < len(clean):
            boundary = clean.rfind("\n\n", start, end)
            if boundary > start + target_chars // 2:
                end = boundary
        chunk = clean[start:end].strip()
        if chunk:
            spans.append((start, end, chunk))
        if end >= len(clean):
            break
        start = max(end - overlap_chars, start + 1)
    return spans
