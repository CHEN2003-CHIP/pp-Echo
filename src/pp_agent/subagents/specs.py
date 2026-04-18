from __future__ import annotations

import json
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class SubAgentSpec(BaseModel):
    name: str
    description: str
    system_prompt: str
    tool_allowlist: list[str] = Field(default_factory=list)
    model_override: Optional[str] = None
    require_plan_approval: bool = False
    max_turns: int = 2
    return_format: str = "summary"


class SubAgentRunResult(BaseModel):
    spec_name: str
    session_id: str
    active_head_id: Optional[str]
    final_text: str = ""
    summary: str = ""
    findings: list[str] = Field(default_factory=list)
    recommended_next_action: str = ""
    inspected_paths: list[str] = Field(default_factory=list)
    confidence: str = "low"
    tool_calls_used: list[str] = Field(default_factory=list)
    event_count: int
    success: bool
    error_message: Optional[str] = None
    failure_kind: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    duration_ms: Optional[int] = None

    @model_validator(mode="after")
    def _populate_final_text(self) -> "SubAgentRunResult":
        if not self.final_text:
            self.final_text = render_subagent_summary_text(
                summary=self.summary,
                findings=self.findings,
                recommended_next_action=self.recommended_next_action,
                inspected_paths=self.inspected_paths,
                confidence=self.confidence,
            )
        return self


def render_subagent_summary_text(
    *,
    summary: str,
    findings: list[str],
    recommended_next_action: str,
    inspected_paths: list[str],
    confidence: str,
) -> str:
    findings_lines = findings or ([summary] if summary else [])
    findings_block = "\n".join(f"- {line}" for line in findings_lines) or "- None"
    next_action = recommended_next_action.strip() or "Review the request or child tool access and try again."
    inspected_block = "\n".join(f"- {path}" for path in inspected_paths) or "- None"
    confidence_line = confidence.strip() or "low"
    return (
        "Findings\n"
        f"{findings_block}\n\n"
        "Recommended next action\n"
        f"- {next_action}\n\n"
        "Files/paths inspected\n"
        f"{inspected_block}\n\n"
        "Confidence\n"
        f"- {confidence_line}\n"
    )


def parse_subagent_output(text: str) -> dict[str, object]:
    raw = text.strip()
    if not raw:
        return {
            "summary": "",
            "findings": [],
            "recommended_next_action": "",
            "inspected_paths": [],
            "confidence": "low",
        }
    if raw.startswith("{"):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            findings = _coerce_list(payload.get("findings"))
            summary = str(payload.get("summary") or "").strip()
            if not summary and findings:
                summary = findings[0]
            return {
                "summary": summary,
                "findings": findings,
                "recommended_next_action": str(
                    payload.get("recommended_next_action")
                    or payload.get("next_action")
                    or ""
                ).strip(),
                "inspected_paths": _coerce_list(payload.get("inspected_paths") or payload.get("files") or payload.get("paths")),
                "confidence": str(payload.get("confidence") or "low").strip() or "low",
            }

    sections: dict[str, list[str]] = {}
    current: Optional[str] = None
    for line in raw.splitlines():
        stripped = line.strip()
        normalized = _normalize_section_heading(stripped)
        if normalized in {
            "findings",
            "recommended next action",
            "files/paths inspected",
            "confidence",
            "summary",
        }:
            current = normalized
            sections.setdefault(current, [])
            continue
        if current is not None and stripped:
            sections[current].append(stripped)
    findings = _clean_bullets(sections.get("findings", []))
    summary_lines = _clean_bullets(sections.get("summary", []))
    summary = " ".join(summary_lines).strip()
    if not summary and findings:
        summary = findings[0]
    return {
        "summary": summary,
        "findings": findings,
        "recommended_next_action": " ".join(_clean_bullets(sections.get("recommended next action", []))).strip(),
        "inspected_paths": _clean_bullets(sections.get("files/paths inspected", [])),
        "confidence": " ".join(_clean_bullets(sections.get("confidence", []))).strip() or "low",
    }


def failure_result(
    *,
    spec_name: str,
    session_id: str,
    active_head_id: Optional[str],
    message: str,
    failure_kind: str,
    tool_calls_used: Optional[list[str]] = None,
    event_count: int = 0,
    started_at: Optional[float] = None,
    finished_at: Optional[float] = None,
) -> SubAgentRunResult:
    finished = finished_at
    duration_ms = None
    if started_at is not None and finished is not None:
        duration_ms = max(int((finished - started_at) * 1000), 0)
    return SubAgentRunResult(
        spec_name=spec_name,
        session_id=session_id,
        active_head_id=active_head_id,
        summary=message,
        findings=[f"Subagent run failed: {message}"],
        recommended_next_action="Review the request or child tool access and try again.",
        inspected_paths=[],
        confidence="low",
        tool_calls_used=list(tool_calls_used or []),
        event_count=event_count,
        success=False,
        error_message=message,
        failure_kind=failure_kind,
        started_at=started_at,
        finished_at=finished,
        duration_ms=duration_ms,
    )


def _coerce_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def _clean_bullets(lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        while stripped[:2] in {"- ", "* "}:
            stripped = stripped[2:].strip()
        if stripped:
            cleaned.append(stripped)
    return cleaned


def _normalize_section_heading(line: str) -> str:
    normalized = line.rstrip(":").strip().lower()
    normalized = re.sub(r"^\d+[\.)]\s+", "", normalized)
    return normalized


SubAgentFailureKind = Literal[
    "spec_not_found",
    "tool_validation_failed",
    "child_runtime_error",
    "empty_result",
    "turn_limit_reached",
]


def default_subagent_specs() -> dict[str, SubAgentSpec]:
    return {
        "repo-researcher": SubAgentSpec(
            name="repo-researcher",
            description="Analyze repository structure and related implementation, then return a concise summary.",
            system_prompt=(
                "You are repo-researcher, a focused repository analysis subagent. "
                "Inspect the codebase with read-only tools and return a concise working summary. "
                "Do not edit files, do not ask follow-up questions, and do not expand scope."
            ),
            tool_allowlist=["read_file", "list_files", "search_text", "grep_code"],
            require_plan_approval=False,
            max_turns=2,
            return_format="summary",
        ),
        "change-reviewer": SubAgentSpec(
            name="change-reviewer",
            description="Review current workspace changes, identify risks, and recommend the next action.",
            system_prompt=(
                "You are change-reviewer, a focused change review subagent. "
                "Inspect current repository changes with read-only tools and summarize risk and next steps. "
                "Do not edit files, do not ask follow-up questions, and do not expand scope."
            ),
            tool_allowlist=["read_file", "search_text", "grep_code", "git_status", "git_diff_worktree"],
            require_plan_approval=False,
            max_turns=2,
            return_format="summary",
        ),
        "test-investigator": SubAgentSpec(
            name="test-investigator",
            description="Inspect failing tests, error output, and relevant code paths, then explain likely causes.",
            system_prompt=(
                "You are test-investigator, a focused test diagnosis subagent. "
                "Inspect test failures and related code with read-only tools, then explain likely root causes and the next debugging step. "
                "Do not edit files, do not ask follow-up questions, and do not expand scope."
            ),
            tool_allowlist=["read_file", "search_text", "grep_code", "list_files"],
            require_plan_approval=False,
            max_turns=2,
            return_format="summary",
        ),
        "api-scout": SubAgentSpec(
            name="api-scout",
            description="Trace interfaces, types, and call sites across the repository, then summarize the path.",
            system_prompt=(
                "You are api-scout, a focused API tracing subagent. "
                "Inspect interfaces, types, and call sites with read-only tools, then summarize how the relevant API surface is connected. "
                "Do not edit files, do not ask follow-up questions, and do not expand scope."
            ),
            tool_allowlist=["read_file", "list_files", "search_text", "grep_code"],
            require_plan_approval=False,
            max_turns=2,
            return_format="summary",
        ),
    }
