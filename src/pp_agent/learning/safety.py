from __future__ import annotations

import re


SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
]


def is_safe_learning_text(text: str) -> bool:
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        return False
    return not any(_is_disallowed_control_char(char) for char in text)


def clean_learning_text(text: str, *, limit: int = 2000) -> str:
    cleaned = "".join(char for char in text if not _is_disallowed_control_char(char))
    cleaned = " ".join(cleaned.split())
    return cleaned[:limit].strip()


def _is_disallowed_control_char(char: str) -> bool:
    codepoint = ord(char)
    return codepoint < 32 and char not in {"\n", "\r", "\t"}
