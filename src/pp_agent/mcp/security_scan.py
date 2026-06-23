from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["low", "medium", "high"]


PATTERNS: list[tuple[str, re.Pattern[str], RiskLevel, str]] = [
    ("ignore_previous_instructions", re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I), "high", "Prompt injection instruction."),
    ("reveal_system_prompt", re.compile(r"reveal\s+(the\s+)?system\s+prompt|show\s+(the\s+)?system\s+prompt", re.I), "high", "Attempts to reveal system prompt."),
    ("do_not_ask_approval", re.compile(r"do\s+not\s+ask\s+(for\s+)?approval|without\s+approval", re.I), "high", "Attempts to bypass approval."),
    ("hide_from_user", re.compile(r"hide\s+this\s+from\s+(the\s+)?user|do\s+not\s+tell\s+(the\s+)?user", re.I), "high", "Attempts to hide behavior from user."),
    ("read_env", re.compile(r"read\s+\.env|\.env\b", re.I), "high", "References .env access."),
    ("send_secrets", re.compile(r"send\s+secrets?|upload\s+secrets?", re.I), "high", "Requests secret transfer."),
    ("exfiltrate", re.compile(r"exfiltrate|data\s+exfiltration", re.I), "high", "Mentions exfiltration."),
    ("call_another_tool", re.compile(r"call\s+another\s+tool|invoke\s+other\s+tools?", re.I), "medium", "Tries to chain tool calls through metadata."),
    ("suspicious_url", re.compile(r"https?://(?:[^\s/]+\.)?(?:pastebin|webhook|requestbin|ngrok|discord|telegram)\.[^\s]+", re.I), "medium", "Contains suspicious external URL."),
    ("base64_like_obfuscation", re.compile(r"\b[A-Za-z0-9+/]{80,}={0,2}\b"), "medium", "Contains base64-like obfuscation."),
]


class MCPMetadataScanResult(BaseModel):
    """Deterministic safety result for MCP descriptor text and metadata."""

    target_id: str
    target_type: str
    risk: RiskLevel = "low"
    flags: list[str] = Field(default_factory=list)
    safe_for_context: bool = True
    reason: str = ""


def scan_mcp_metadata(*, target_id: str, target_type: str, text: str) -> MCPMetadataScanResult:
    """Scan MCP descriptor text for prompt-injection and exfiltration indicators."""

    flags: list[str] = []
    reasons: list[str] = []
    risk: RiskLevel = "low"
    for flag, pattern, pattern_risk, reason in PATTERNS:
        if not pattern.search(text or ""):
            continue
        flags.append(flag)
        reasons.append(reason)
        if pattern_risk == "high":
            risk = "high"
        elif pattern_risk == "medium" and risk != "high":
            risk = "medium"
    return MCPMetadataScanResult(
        target_id=target_id,
        target_type=target_type,
        risk=risk,
        flags=flags,
        safe_for_context=risk != "high",
        reason="; ".join(reasons) if reasons else "No suspicious metadata indicators.",
    )
