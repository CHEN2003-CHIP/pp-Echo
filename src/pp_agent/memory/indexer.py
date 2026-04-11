from __future__ import annotations

import math
import re
from typing import Any

from pp_agent.memory.types import HistoryChunkInput, SourceKind


_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)

# 句子级边界：中英文常见句末符号
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])|(?<=[.!?])\s+")

# 次级边界：逗号、顿号、冒号、换行
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[，,、：:])|\n+")

# URL / 路径 / 参数分隔符
_URLISH_SPLIT_RE = re.compile(r"(?<=[/?&=#._-])")

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


class HistoryIndexer:
    def __init__(self, *, chunk_target_tokens: int = 350, chunk_max_tokens: int = 420) -> None:
        self.chunk_target_tokens = max(1, chunk_target_tokens)
        self.chunk_max_tokens = max(self.chunk_target_tokens, chunk_max_tokens)

    def chunk_message(
        self,
        *,
        text: str,
        role: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[HistoryChunkInput]:
        clean = text.strip()
        if not clean:
            return []

        source_kind = self._source_kind_for_role(role)
        base_metadata = dict(metadata or {})
        base_metadata.setdefault("role", role)

        paragraphs = [part.strip() for part in clean.split("\n\n") if part.strip()]
        if not paragraphs:
            paragraphs = [clean]

        chunks: list[str] = []
        current_parts: list[str] = []
        current_tokens = 0

        for paragraph in paragraphs:
            pieces = self._split_paragraph(paragraph)
            for piece in pieces:
                piece_tokens = self._estimate_tokens(piece)
                if current_parts and current_tokens + piece_tokens > self.chunk_target_tokens:
                    chunks.append("\n\n".join(current_parts).strip())
                    current_parts = []
                    current_tokens = 0
                current_parts.append(piece)
                current_tokens += piece_tokens

        if current_parts:
            chunks.append("\n\n".join(current_parts).strip())

        return [
            HistoryChunkInput(
                chunk_index=index,
                text=value,
                token_estimate=self._estimate_tokens(value),
                source_kind=source_kind,
                metadata=dict(base_metadata),
            )
            for index, value in enumerate(chunks)
            if value.strip()
        ]

    def _split_paragraph(self, paragraph: str) -> list[str]:
        if self._estimate_tokens(paragraph) <= self.chunk_max_tokens:
            return [paragraph]

        # 1) 先保护代码块，避免把 fenced code block 随便打散
        protected_units = self._split_preserving_code_blocks(paragraph)

        pieces: list[str] = []
        for unit in protected_units:
            if self._estimate_tokens(unit) <= self.chunk_max_tokens:
                pieces.append(unit)
                continue

            if self._looks_like_code(unit):
                pieces.extend(self._split_code_like(unit))
                continue

            if self._looks_like_json(unit):
                pieces.extend(self._split_json_like(unit))
                continue

            # 2) 先按句子边界切（对中文友好）
            sentence_parts = self._split_by_regex(unit, _SENTENCE_SPLIT_RE)
            if len(sentence_parts) > 1:
                pieces.extend(self._pack_parts(sentence_parts))
                continue

            # 3) 再按短语边界切
            clause_parts = self._split_by_regex(unit, _CLAUSE_SPLIT_RE)
            if len(clause_parts) > 1:
                pieces.extend(self._pack_parts(clause_parts))
                continue

            # 4) 对 URL / 路径这类长串做更细切分
            if self._looks_like_urlish(unit):
                url_parts = self._split_by_regex(unit, _URLISH_SPLIT_RE)
                packed = self._pack_parts(url_parts)
                if packed:
                    pieces.extend(packed)
                    continue

            # 5) 中文或无空格长文本：直接按字符窗口硬切
            pieces.extend(self._hard_split(unit))

        return [p for p in pieces if p.strip()] or [paragraph]

    def _split_preserving_code_blocks(self, text: str) -> list[str]:
        units: list[str] = []
        last = 0
        for match in _CODE_BLOCK_RE.finditer(text):
            if match.start() > last:
                prefix = text[last:match.start()].strip()
                if prefix:
                    units.append(prefix)
            block = match.group(0).strip()
            if block:
                units.append(block)
            last = match.end()
        if last < len(text):
            suffix = text[last:].strip()
            if suffix:
                units.append(suffix)
        return units or [text]

    def _pack_parts(self, parts: list[str]) -> list[str]:
        out: list[str] = []
        current: list[str] = []
        current_tokens = 0

        for part in parts:
            part = part.strip()
            if not part:
                continue

            part_tokens = self._estimate_tokens(part)

            if part_tokens > self.chunk_max_tokens:
                if current:
                    out.append("".join(current).strip())
                    current = []
                    current_tokens = 0
                out.extend(self._hard_split(part))
                continue

            if current and current_tokens + part_tokens > self.chunk_max_tokens:
                out.append("".join(current).strip())
                current = [part]
                current_tokens = part_tokens
            else:
                current.append(part)
                current_tokens += part_tokens

        if current:
            out.append("".join(current).strip())

        return out

    def _split_by_regex(self, text: str, pattern: re.Pattern[str]) -> list[str]:
        parts = pattern.split(text)
        return [p for p in parts if p and p.strip()]

    def _split_code_like(self, text: str) -> list[str]:
        # 代码优先按行切，保留可读性
        lines = text.splitlines(keepends=True)
        if len(lines) <= 1:
            return self._hard_split(text)

        out: list[str] = []
        current: list[str] = []
        current_tokens = 0

        for line in lines:
            line_tokens = self._estimate_tokens(line)
            if current and current_tokens + line_tokens > self.chunk_max_tokens:
                out.append("".join(current).strip())
                current = []
                current_tokens = 0

            if line_tokens > self.chunk_max_tokens:
                if current:
                    out.append("".join(current).strip())
                    current = []
                    current_tokens = 0
                out.extend(self._hard_split(line))
            else:
                current.append(line)
                current_tokens += line_tokens

        if current:
            out.append("".join(current).strip())

        return out

    def _split_json_like(self, text: str) -> list[str]:
        # JSON 通常按行切最好；如果是压缩成一行，再按标点回退
        if "\n" in text:
            return self._split_code_like(text)

        jsonish_parts = re.split(r'(?<=[}\],])|(?<=[,:])', text)
        packed = self._pack_parts([p for p in jsonish_parts if p.strip()])
        return packed or self._hard_split(text)

    def _hard_split(self, text: str, *, overlap_chars: int = 32) -> list[str]:
        normalized = text.strip()
        if not normalized:
            return []

        # 因为 _estimate_tokens 大约是 len / 4，这里反推字符窗口
        max_chars = max(40, self.chunk_max_tokens * 4)
        if len(normalized) <= max_chars:
            return [normalized]

        pieces: list[str] = []
        start = 0
        while start < len(normalized):
            end = min(len(normalized), start + max_chars)
            piece = normalized[start:end].strip()
            if piece:
                pieces.append(piece)
            if end >= len(normalized):
                break
            start = max(start + 1, end - overlap_chars)

        return pieces

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        normalized = " ".join(text.split())
        if not normalized:
            return 0

        # 对 CJK 稍微保守一点：中文通常 1 字 ≈ 1 token 的比例比英文高
        cjk_count = len(_CJK_RE.findall(normalized))
        non_cjk_count = len(normalized) - cjk_count

        approx = math.ceil(cjk_count / 1.6) + math.ceil(non_cjk_count / 4)
        return max(1, approx)

    @staticmethod
    def _looks_like_code(text: str) -> bool:
        stripped = text.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            return True
        code_markers = ("def ", "class ", "import ", "{", "}", "=>", "::", "return ", "if ", "for ")
        return sum(marker in stripped for marker in code_markers) >= 2

    @staticmethod
    def _looks_like_json(text: str) -> bool:
        stripped = text.strip()
        return (
            (stripped.startswith("{") and stripped.endswith("}"))
            or (stripped.startswith("[") and stripped.endswith("]"))
        ) and ":" in stripped

    @staticmethod
    def _looks_like_urlish(text: str) -> bool:
        stripped = text.strip()
        return (
            "http://" in stripped
            or "https://" in stripped
            or stripped.count("/") >= 3
            or ("?" in stripped and "=" in stripped)
        )

    @staticmethod
    def _source_kind_for_role(role: str) -> SourceKind:
        if role in {"user", "assistant", "tool", "system", "summary"}:
            return role
        return "assistant"