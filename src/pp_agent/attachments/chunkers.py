from __future__ import annotations

import ast
import csv
import io
import json
import re
from typing import Any

from pp_agent.attachments.schema import AttachmentChunk, AttachmentKind
from pp_agent.attachments.text_utils import estimate_tokens, split_with_overlap

TARGET_CHARS = 3200
OVERLAP_CHARS = 400
MAX_CHUNKS_PER_FILE = 500


def _chunk_id(attachment_id: str, index: int) -> str:
    return f"chk_{attachment_id.removeprefix('att_')}_{index:04d}"


def _line_range(text: str, char_start: int, char_end: int) -> tuple[int, int]:
    before = text[:char_start]
    segment = text[char_start:char_end]
    start = before.count("\n") + 1
    return start, start + segment.count("\n")


def source_ref_for_chunk(filename: str, *, page_start: int | None = None, page_end: int | None = None, line_start: int | None = None, line_end: int | None = None, heading_path: list[str] | None = None) -> str:
    """根据 chunk 的页码、行号或 heading path 生成稳定来源引用。"""

    headings = [item for item in (heading_path or []) if item]
    if page_start:
        if page_end and page_end != page_start:
            return f"{filename}#page={page_start}-{page_end}"
        return f"{filename}#page={page_start}"
    if headings:
        return f"{filename} > {' > '.join(headings)}"
    if line_start:
        if line_end and line_end != line_start:
            return f"{filename}:L{line_start}-L{line_end}"
        return f"{filename}:L{line_start}"
    return filename


def chunk_plain_text(
    text: str,
    *,
    attachment_id: str,
    session_id: str,
    filename: str,
    kind: AttachmentKind = AttachmentKind.TEXT,
    target_chars: int = TARGET_CHARS,
    overlap_chars: int = OVERLAP_CHARS,
    max_chunks: int = MAX_CHUNKS_PER_FILE,
) -> list[AttachmentChunk]:
    """将普通文本切成带行号和字符范围的 chunk，避免完整文件进入 prompt。"""

    chunks: list[AttachmentChunk] = []
    for index, (start, end, body) in enumerate(split_with_overlap(text, target_chars, overlap_chars)[:max_chunks], start=1):
        line_start, line_end = _line_range(text, start, end)
        chunks.append(
            (lambda ref: AttachmentChunk(
                chunk_id=_chunk_id(attachment_id, index),
                attachment_id=attachment_id,
                session_id=session_id,
                filename=filename,
                kind=kind,
                text=body,
                token_estimate=estimate_tokens(body),
                char_start=start,
                char_end=end,
                line_start=line_start,
                line_end=line_end,
                source_ref=ref,
            ))(source_ref_for_chunk(filename, line_start=line_start, line_end=line_end))
        )
    return chunks


def chunk_markdown(text: str, *, attachment_id: str, session_id: str, filename: str) -> list[AttachmentChunk]:
    """按 Markdown heading 优先切块，并在 chunk 中保留 heading_path。"""

    heading_path: list[str] = []
    sections: list[tuple[list[str], int, int, str]] = []
    current_start = 0
    current_heading: list[str] = []
    lines = text.splitlines(keepends=True)
    offset = 0
    for line in lines:
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match and offset > current_start:
            sections.append((current_heading, current_start, offset, text[current_start:offset]))
            level = len(match.group(1))
            heading_path = heading_path[: level - 1] + [match.group(2).strip()]
            current_heading = list(heading_path)
            current_start = offset
        elif match:
            level = len(match.group(1))
            heading_path = heading_path[: level - 1] + [match.group(2).strip()]
            current_heading = list(heading_path)
        offset += len(line)
    if current_start < len(text):
        sections.append((current_heading, current_start, len(text), text[current_start:]))
    if not sections:
        return chunk_plain_text(text, attachment_id=attachment_id, session_id=session_id, filename=filename, kind=AttachmentKind.MARKDOWN)
    chunks: list[AttachmentChunk] = []
    index = 1
    for headings, base_start, _base_end, body in sections:
        for start, end, part in split_with_overlap(body, TARGET_CHARS, OVERLAP_CHARS):
            line_start, line_end = _line_range(text, base_start + start, base_start + end)
            chunks.append(
                AttachmentChunk(
                    chunk_id=_chunk_id(attachment_id, index),
                    attachment_id=attachment_id,
                    session_id=session_id,
                    filename=filename,
                    kind=AttachmentKind.MARKDOWN,
                    text=part,
                    token_estimate=estimate_tokens(part),
                    char_start=base_start + start,
                    char_end=base_start + end,
                    line_start=line_start,
                    line_end=line_end,
                    heading_path=list(headings),
                    source_ref=source_ref_for_chunk(filename, line_start=line_start, line_end=line_end, heading_path=list(headings)),
                    section_title=headings[-1] if headings else None,
                )
            )
            index += 1
            if index > MAX_CHUNKS_PER_FILE:
                return chunks
    return chunks


def python_outline(text: str) -> list[dict[str, Any]]:
    """使用 Python ast 提取类、函数和 import outline，失败时返回空列表。"""

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    outline: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            outline.append({"kind": "import", "name": ast.unparse(node) if hasattr(ast, "unparse") else "import", "line": node.lineno})
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            outline.append({"kind": node.__class__.__name__.replace("Def", "").lower(), "name": node.name, "line": node.lineno, "end_line": getattr(node, "end_lineno", None)})
    return sorted(outline, key=lambda item: int(item.get("line") or 0))

#TODO:可以考虑引入其他语言的代码符号识别工具，如 Java、C++、Go 等。"""
def regex_code_outline(text: str) -> list[dict[str, Any]]:
    """用轻量正则识别非 Python 代码中的类和函数符号。"""

    outline: list[dict[str, Any]] = []
    patterns = [
        ("class", re.compile(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)")),
        ("function", re.compile(r"\b(?:function\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*(?:\{|=>)")),
        ("function", re.compile(r"\b(?:def|fn|func)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")),
    ]
    for line_no, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in patterns:
            match = pattern.search(line)
            if match:
                outline.append({"kind": kind, "name": match.group(1), "line": line_no})
                break
    return outline


def chunk_code_file(text: str, *, attachment_id: str, session_id: str, filename: str) -> tuple[list[AttachmentChunk], list[dict[str, Any]]]:
    """按代码符号和行范围切块，并保留 outline 供 inspect_attachment 使用。"""

    outline = python_outline(text) if filename.endswith(".py") else regex_code_outline(text)
    chunks = chunk_plain_text(text, attachment_id=attachment_id, session_id=session_id, filename=filename, kind=AttachmentKind.CODE)
    for chunk in chunks:
        chunk.metadata["outline_hits"] = [
            item for item in outline if chunk.line_start and chunk.line_end and chunk.line_start <= int(item.get("line") or 0) <= chunk.line_end
        ]
    return chunks, outline


def chunk_pdf_pages(pages: list[tuple[int, str]], *, attachment_id: str, session_id: str, filename: str) -> list[AttachmentChunk]:
    """将 PDF 按页文本切块，保留 page_start/page_end 供来源引用。"""

    chunks: list[AttachmentChunk] = []
    for page_no, text in pages:
        for _start, _end, part in split_with_overlap(text, TARGET_CHARS, OVERLAP_CHARS):
            if not part.strip():
                continue
            index = len(chunks) + 1
            chunks.append(
                AttachmentChunk(
                    chunk_id=_chunk_id(attachment_id, index),
                    attachment_id=attachment_id,
                    session_id=session_id,
                    filename=filename,
                    kind=AttachmentKind.PDF,
                    text=part,
                    token_estimate=estimate_tokens(part),
                    page_start=page_no,
                    page_end=page_no,
                    source_ref=source_ref_for_chunk(filename, page_start=page_no, page_end=page_no),
                )
            )
    return chunks[:MAX_CHUNKS_PER_FILE]


def chunk_table_profile(text: str, *, attachment_id: str, session_id: str, filename: str) -> tuple[list[AttachmentChunk], dict[str, Any]]:
    """分析 CSV header、样本和简单列类型，并按行块生成 chunk。"""

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    header = rows[0] if rows else []
    data_rows = rows[1:]
    sample = data_rows[:20]
    column_types: dict[str, str] = {}
    for index, name in enumerate(header):
        values = [row[index] for row in sample if index < len(row) and row[index] != ""]
        if values and all(_is_number(value) for value in values):
            column_types[name] = "number"
        else:
            column_types[name] = "string"
    profile = {"columns": header, "column_count": len(header), "row_count": len(data_rows), "sample": sample, "column_types": column_types}
    chunks: list[AttachmentChunk] = []
    for start in range(0, len(data_rows), 100):
        block = [header, *data_rows[start : start + 100]] if header else data_rows[start : start + 100]
        body = "\n".join(",".join(cell for cell in row) for row in block).strip()
        if not body:
            continue
        index = len(chunks) + 1
        chunks.append(
            AttachmentChunk(
                chunk_id=_chunk_id(attachment_id, index),
                attachment_id=attachment_id,
                session_id=session_id,
                filename=filename,
                kind=AttachmentKind.CSV,
                text=body,
                token_estimate=estimate_tokens(body),
                line_start=start + 1,
                line_end=start + len(block),
                source_ref=source_ref_for_chunk(filename, line_start=start + 1, line_end=start + len(block)),
                metadata={"profile": profile if index == 1 else {}},
            )
        )
    return chunks[:MAX_CHUNKS_PER_FILE], profile


def chunk_structured_json(text: str, *, attachment_id: str, session_id: str, filename: str, kind: AttachmentKind) -> tuple[list[AttachmentChunk], dict[str, Any]]:
    """解析 JSON/YAML 结构摘要，解析失败时降级为普通文本切块。"""

    try:
        data = json.loads(text) if kind == AttachmentKind.JSON else _parse_simple_yaml(text)
    except Exception:
        return chunk_plain_text(text, attachment_id=attachment_id, session_id=session_id, filename=filename, kind=kind), {"parse_failed": True}
    summary = _structure_summary(data)
    pretty = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    chunks = chunk_plain_text(pretty, attachment_id=attachment_id, session_id=session_id, filename=filename, kind=kind)
    for chunk in chunks:
        chunk.metadata["structure"] = summary if chunk.chunk_id.endswith("0001") else {}
    return chunks, summary


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def _parse_simple_yaml(text: str) -> Any:
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text)
    except ImportError:
        result: dict[str, str] = {}
        for line in text.splitlines():
            if ":" in line and not line.startswith(" "):
                key, value = line.split(":", 1)
                result[key.strip()] = value.strip()
        return result


def _structure_summary(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return {"type": "object", "top_level_keys": list(data.keys())[:100], "key_count": len(data)}
    if isinstance(data, list):
        return {"type": "array", "length": len(data), "sample_types": [type(item).__name__ for item in data[:10]]}
    return {"type": type(data).__name__}
