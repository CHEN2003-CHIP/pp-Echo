from __future__ import annotations

import re
from typing import Literal


MemoryCategory = Literal["preference", "decision", "error_fix", "path_command", "general"]

CATEGORY_LABELS: dict[MemoryCategory, str] = {
    "preference": "Preferences / Constraints",
    "decision": "Decisions / Conclusions",
    "error_fix": "Errors / Fixes",
    "path_command": "Paths / Files / Commands",
    "general": "General Context",
}

VALID_MEMORY_CATEGORIES = frozenset(CATEGORY_LABELS)


def classify_memory_text(text: str, *, role: str = "", source_kind: str = "") -> MemoryCategory:
    normalized = text.lower()
    if _is_preference(normalized, role=role, source_kind=source_kind):
        return "preference"
    if is_error_or_fix(normalized):
        return "error_fix"
    if is_decision(normalized):
        return "decision"
    if looks_like_path_or_command(normalized):
        return "path_command"
    return "general"


def is_error_or_fix(text: str) -> bool:
    keywords = (
        "error",
        "failed",
        "failure",
        "traceback",
        "exception",
        "fix",
        "fixed",
        "missing",
        "not found",
        "报错",
        "错误",
        "失败",
        "异常",
        "修复",
    )
    return any(keyword in text for keyword in keywords)


def looks_like_path_or_command(text: str) -> bool:
    return bool(
        re.search(
            r"([a-z]:\\|/|\.py\b|\.ts\b|\.tsx\b|\.js\b|\.json\b|\.md\b|"
            r"src/|tests/|docs/|pp_agent/|\brun pytest\b|\bpytest\b|"
            r"\bgit status\b|\bgit diff\b|\bpython [\w./:-]+\b|\bnpm run\b|\buv run\b)",
            text,
        )
    )


def is_decision(text: str) -> bool:
    keywords = (
        "decide",
        "decided",
        "decision",
        "choose",
        "chosen",
        "agreed",
        "conclusion",
        "结论",
        "决定",
        "采用",
        "选用",
        "保留",
    )
    return any(keyword in text for keyword in keywords)


def _is_preference(text: str, *, role: str, source_kind: str) -> bool:
    keywords = (
        "prefer",
        "preference",
        "avoid",
        "always",
        "must",
        "keep",
        "constraint",
        "do not",
        "don't",
        "偏好",
        "约束",
        "尽量",
        "不要",
        "必须",
        "保持",
    )
    return any(keyword in text for keyword in keywords) and (role == "user" or source_kind == "user")
