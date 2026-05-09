from __future__ import annotations

import hashlib
import re
from pathlib import Path

from pp_agent.learning.models import LearningCandidate, LearningSettings
from pp_agent.learning.safety import clean_learning_text


class LearningCurator:
    def __init__(self, *, workspace: Path, settings: LearningSettings) -> None:
        self.workspace = workspace.resolve()
        self.settings = settings

    def memory_entry(self, candidate: LearningCandidate) -> str:
        title = clean_learning_text(candidate.title, limit=120)
        content = clean_learning_text(candidate.content, limit=1200)
        evidence = clean_learning_text(candidate.evidence, limit=500)
        lines = [f"- **{title}**: {content}"]
        if evidence:
            lines.append(f"  Evidence: {evidence}")
        lines.append(f"  Source: session={candidate.source_session_id} turn={candidate.source_turn_id}")
        return "\n".join(lines)

    def skill_path_for(self, candidate: LearningCandidate) -> Path:
        slug = _slugify(candidate.title)
        digest = hashlib.sha1(candidate.id.encode("utf-8")).hexdigest()[:6]
        root = self.workspace / ".pp-agent" / "skills"
        candidate_path = root / slug / "SKILL.md"
        if candidate_path.exists():
            candidate_path = root / f"{slug}-{digest}" / "SKILL.md"
        return candidate_path

    def skill_document(self, candidate: LearningCandidate, *, name: str | None = None) -> str:
        skill_name = name or _slugify(candidate.title)
        description = clean_learning_text(candidate.content, limit=120) or clean_learning_text(candidate.title, limit=120)
        body = clean_learning_text(candidate.content, limit=1600)
        evidence = clean_learning_text(candidate.evidence, limit=800)
        return (
            "---\n"
            f"name: {skill_name}\n"
            f"description: {description}\n"
            "---\n"
            "## When to Use\n"
            f"Use this skill when a task matches this learned workflow or convention: {description}\n\n"
            "## Procedure\n"
            f"{body}\n\n"
            "## Pitfalls\n"
            "- Re-check the current repository state before applying this learned guidance.\n"
            "- Do not treat this skill as permission to bypass approvals or tool policy.\n\n"
            "## Verification\n"
            "- Confirm the result against the current project files and focused tests.\n\n"
            "## Evidence\n"
            f"{evidence or 'Learned from a prior pp-Echo turn.'}\n"
        )

    def consolidated_memory(self, current_memory: str, applied_entries: list[str]) -> str:
        text = "\n\n".join([current_memory.strip(), *[entry.strip() for entry in applied_entries if entry.strip()]]).strip()
        if len(text) <= self.settings.project_memory_char_limit:
            return text
        return text[-self.settings.project_memory_char_limit :].strip()


def _slugify(value: str) -> str:
    lowered = value.lower()
    cleaned = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", lowered).strip("-")
    if not cleaned:
        return "learned-skill"
    return cleaned[:60].strip("-") or "learned-skill"
