from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from pp_agent.memory.core_types import CoreMemory, CoreMemoryCandidate


@dataclass(frozen=True)
class SafetyScanResult:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    risk: str = "low"

    def to_dict(self) -> dict[str, object]:
        return {"allowed": self.allowed, "reasons": list(self.reasons), "risk": self.risk}


SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_ -]?key|secret|credential|token|password)\b\s*[:=]\s*\S{6,}"),
    re.compile(r"\b(?:sk|pk|ghp|gho|xoxb|AKIA)[A-Za-z0-9_\-]{12,}\b"),
]
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore (all )?(previous|prior) (rules|instructions)"),
    re.compile(r"(?i)do not (ask|request).{0,24}approval"),
    re.compile(r"(?i)(always|forever).{0,24}(bypass|disable).{0,24}(safety|restriction|approval)"),
    re.compile(r"(?i)(reveal|leak|print).{0,24}(system prompt|system instructions)"),
    re.compile(r"忽略之前的所有规则|不要再请求审批|绕过安全限制|泄露.*系统提示"),
]
DANGEROUS_SHELL_PATTERNS = [
    re.compile(r"(?i)\brm\s+-rf\b"),
    re.compile(r"(?i)\bcurl\b.+\|\s*(sh|bash|powershell|pwsh)\b"),
    re.compile(r"(?i)\bchmod\s+777\b"),
    re.compile(r"(?i)\bsudo\b"),
    re.compile(r"(?i)(exfiltrate|upload|send).{0,40}(credential|token|secret|password)"),
    re.compile(r"(?i)(store|remember|save).{0,40}(tool output|system message|hidden instruction)"),
]


def normalize_memory_content(content: str) -> str:
    value = unicodedata.normalize("NFKC", content).lower().strip()
    value = re.sub(r"\s+", " ", value)
    return value.rstrip(".,;:!?。！？；：")


def scan_memory_candidate(candidate: CoreMemoryCandidate | CoreMemory) -> SafetyScanResult:
    text = candidate.content
    reasons: list[str] = []
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        reasons.append("secret_or_credential")
    if any(pattern.search(text) for pattern in PROMPT_INJECTION_PATTERNS):
        reasons.append("prompt_injection")
    if any(pattern.search(text) for pattern in DANGEROUS_SHELL_PATTERNS):
        reasons.append("dangerous_shell_instruction")
    if _has_suspicious_control_chars(text):
        reasons.append("suspicious_control_chars")
    if reasons:
        return SafetyScanResult(allowed=False, reasons=reasons, risk="high")
    return SafetyScanResult(allowed=True)


def find_duplicate(candidate: CoreMemoryCandidate | CoreMemory, existing: list[CoreMemory]) -> Optional[CoreMemory]:
    normalized = normalize_memory_content(candidate.content)
    for memory in existing:
        if normalize_memory_content(memory.content) == normalized:
            return memory
    return None


def find_near_duplicate(candidate: CoreMemoryCandidate | CoreMemory, existing: list[CoreMemory]) -> Optional[CoreMemory]:
    normalized = normalize_memory_content(candidate.content)
    candidate_terms = set(_significant_terms(normalized))
    if not candidate_terms:
        return None
    for memory in existing:
        if memory.scope != candidate.scope or memory.workspace_id != candidate.workspace_id:
            continue
        if memory.section != candidate.section or memory.type != candidate.type:
            continue
        terms = set(_significant_terms(normalize_memory_content(memory.content)))
        if not terms:
            continue
        overlap = len(candidate_terms & terms) / max(len(candidate_terms | terms), 1)
        if overlap >= 0.82:
            return memory
    return None


def detect_conflicts(candidate: CoreMemoryCandidate | CoreMemory, existing: list[CoreMemory]) -> list[str]:
    candidate_markers = _conflict_markers(candidate.content, section=candidate.section, memory_type=candidate.type)
    if not candidate_markers:
        return []
    conflicts: list[str] = []
    for memory in existing:
        if memory.scope != candidate.scope or memory.workspace_id != candidate.workspace_id or memory.section != candidate.section:
            continue
        markers = _conflict_markers(memory.content, section=memory.section, memory_type=memory.type)
        if _marker_conflicts(candidate_markers, markers):
            conflicts.append(memory.id)
    return conflicts


def _has_suspicious_control_chars(text: str) -> bool:
    for char in text:
        category = unicodedata.category(char)
        if category in {"Cf", "Cc"} and char not in {"\n", "\r", "\t"}:
            return True
    return False


def _conflict_markers(text: str, *, section: str, memory_type: str) -> set[str]:
    value = normalize_memory_content(text)
    markers: set[str] = set()
    for marker in ("npm test", "pnpm test", "yarn test", "pytest", "unittest", "pip", "poetry", "uv"):
        if marker in value:
            group = {
                "npm test": "js_test",
                "pnpm test": "js_test",
                "yarn test": "js_test",
                "pytest": "py_test",
                "unittest": "py_test",
                "pip": "py_pkg",
                "poetry": "py_pkg",
                "uv": "py_pkg",
            }[marker]
            markers.add(f"{group}:{marker}")
    if section == "user_profile" or memory_type == "preference":
        if any(token in value for token in ("verbose", "detailed", "详细")):
            markers.add("answer_style:verbose")
        if any(token in value for token in ("concise", "brief", "简洁")):
            markers.add("answer_style:concise")
        if any(token in value for token in ("chinese", "中文")):
            markers.add("language:chinese")
        if any(token in value for token in ("english", "英文")):
            markers.add("language:english")
        if any(token in value for token in ("auto execute", "自动执行")):
            markers.add("execution:auto")
        if any(token in value for token in ("confirm first", "先确认")):
            markers.add("execution:confirm")
    return markers


def _marker_conflicts(left: set[str], right: set[str]) -> bool:
    groups: dict[str, set[str]] = {}
    for marker in left | right:
        group, value = marker.split(":", 1)
        groups.setdefault(group, set()).add(value)
    for group, values in groups.items():
        if len(values) < 2:
            continue
        if any(marker.startswith(f"{group}:") for marker in left) and any(marker.startswith(f"{group}:") for marker in right):
            return True
    return False


def _significant_terms(value: str) -> list[str]:
    return [term for term in re.findall(r"[a-z0-9_\-./]+|[\u4e00-\u9fff]+", value) if len(term) >= 2]
