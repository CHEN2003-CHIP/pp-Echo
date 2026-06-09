from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from pp_agent.attachments.schema import AttachmentRecord, AttachmentStatus
from pp_agent.attachments.text_utils import preview_text, read_text_lossy


class CodeSymbol(BaseModel):
    """
    表示代码附件中的一个可检索符号。

    一个符号通常对应 class、function、method、async function、import
    或 top-level constant。它保留名称、类型、签名、父级符号和行号范围，
    让 Agent 可以先理解代码结构，再按 symbol 或行号读取局部内容。
    """

    symbol_id: str
    attachment_id: str
    name: str
    kind: str
    signature: Optional[str] = None
    parent: Optional[str] = None
    line_start: int
    line_end: int
    docstring_preview: Optional[str] = None


def build_symbol_index(text: str, *, attachment_id: str, filename: str) -> list[CodeSymbol]:
    """
    为代码附件构建 symbol-level 索引。

    Python 文件优先使用 ast 获得准确行号、父级 class 和 docstring；
    JS/TS 等文件使用轻量 regex heuristic。该函数只返回符号元数据，
    不把完整代码内容写入模型上下文或 TraceInspect。
    """

    if filename.endswith(".py"):
        return _python_symbols(text, attachment_id=attachment_id)
    return _regex_symbols(text, attachment_id=attachment_id)


def search_symbols(symbols: list[CodeSymbol], query: str, *, top_k: int = 10) -> list[dict[str, Any]]:
    """按名称、签名、类型和 docstring preview 搜索代码符号。"""

    terms = [term.lower() for term in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", query)]
    if not terms:
        return []
    scored: list[tuple[float, CodeSymbol]] = []
    for symbol in symbols:
        haystack = " ".join(
            [
                symbol.name,
                symbol.kind,
                symbol.signature or "",
                symbol.parent or "",
                symbol.docstring_preview or "",
            ]
        ).lower()
        score = 0.0
        for term in terms:
            if term == symbol.name.lower():
                score += 5.0
            elif term in symbol.name.lower():
                score += 3.0
            elif term in haystack:
                score += 1.0
        if score > 0:
            scored.append((score, symbol))
    return [
        {**symbol.model_dump(mode="json"), "score": score}
        for score, symbol in sorted(scored, key=lambda item: item[0], reverse=True)[: max(1, min(50, top_k))]
    ]


def read_symbol_text(record: AttachmentRecord, symbol: CodeSymbol, *, attachment_dir: Path, max_chars: int = 12000) -> dict[str, Any]:
    """读取指定 symbol 的局部代码文本，并按上限截断避免泄露完整大文件。"""

    if record.status == AttachmentStatus.DELETED:
        raise FileNotFoundError(f"Attachment is deleted: {record.attachment_id}")
    original_path = attachment_dir / "original" / record.stored_filename
    lines = read_text_lossy(original_path).splitlines()
    text = "\n".join(lines[symbol.line_start - 1 : symbol.line_end])
    truncated = len(text) > max_chars
    return {
        "symbol": symbol.model_dump(mode="json"),
        "attachment_id": record.attachment_id,
        "filename": record.stored_filename,
        "source_ref": f"{record.stored_filename}:L{symbol.line_start}-L{symbol.line_end}",
        "text": text[:max_chars],
        "truncated": truncated,
    }


def _python_symbols(text: str, *, attachment_id: str) -> list[CodeSymbol]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    symbols: list[CodeSymbol] = []
    for node in tree.body:
        _collect_python_node(node, attachment_id=attachment_id, symbols=symbols, parent=None)
    return symbols


def _collect_python_node(node: ast.AST, *, attachment_id: str, symbols: list[CodeSymbol], parent: str | None) -> None:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        name = ast.unparse(node) if hasattr(ast, "unparse") else "import"
        symbols.append(_symbol(attachment_id, name=name, kind="import", line_start=node.lineno, line_end=getattr(node, "end_lineno", node.lineno), signature=name, parent=parent))
        return
    if isinstance(node, ast.Assign) and parent is None:
        name = ", ".join(ast.unparse(target) for target in node.targets if hasattr(ast, "unparse")) or "assignment"
        symbols.append(_symbol(attachment_id, name=name, kind="constant", line_start=node.lineno, line_end=getattr(node, "end_lineno", node.lineno), signature=name))
        return
    if isinstance(node, ast.ClassDef):
        signature = f"class {node.name}"
        symbols.append(_symbol(attachment_id, name=node.name, kind="class", line_start=node.lineno, line_end=getattr(node, "end_lineno", node.lineno), signature=signature, docstring=ast.get_docstring(node)))
        for child in node.body:
            _collect_python_node(child, attachment_id=attachment_id, symbols=symbols, parent=node.name)
        return
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        args = ast.unparse(node.args) if hasattr(ast, "unparse") else ""
        kind = "method" if parent else ("async_function" if isinstance(node, ast.AsyncFunctionDef) else "function")
        symbols.append(
            _symbol(
                attachment_id,
                name=node.name,
                kind=kind,
                line_start=node.lineno,
                line_end=getattr(node, "end_lineno", node.lineno),
                signature=f"{prefix} {node.name}({args})",
                parent=parent,
                docstring=ast.get_docstring(node),
            )
        )


def _regex_symbols(text: str, *, attachment_id: str) -> list[CodeSymbol]:
    patterns = [
        ("class", re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)")),
        ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)")),
        ("function", re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>")),
    ]
    symbols: list[CodeSymbol] = []
    lines = text.splitlines()
    for index, line in enumerate(lines, start=1):
        for kind, pattern in patterns:
            match = pattern.search(line)
            if match:
                name = match.group(1)
                symbols.append(_symbol(attachment_id, name=name, kind=kind, line_start=index, line_end=_heuristic_end_line(lines, index), signature=line.strip()))
                break
    return symbols


def _heuristic_end_line(lines: list[str], start_line: int) -> int:
    depth = 0
    saw_open = False
    for index in range(start_line - 1, len(lines)):
        line = lines[index]
        depth += line.count("{")
        if "{" in line:
            saw_open = True
        depth -= line.count("}")
        if saw_open and depth <= 0:
            return index + 1
    return start_line


def _symbol(attachment_id: str, *, name: str, kind: str, line_start: int, line_end: int, signature: str | None = None, parent: str | None = None, docstring: str | None = None) -> CodeSymbol:
    symbol_key = f"{attachment_id}:{kind}:{parent or ''}:{name}:{line_start}"
    return CodeSymbol(
        symbol_id="sym_" + hashlib.sha1(symbol_key.encode("utf-8")).hexdigest()[:16],
        attachment_id=attachment_id,
        name=name,
        kind=kind,
        signature=signature,
        parent=parent,
        line_start=line_start,
        line_end=max(line_start, line_end),
        docstring_preview=preview_text(docstring or "", limit=160) or None,
    )
