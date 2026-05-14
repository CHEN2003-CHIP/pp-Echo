from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pp_agent.learning.models import LearningSettings


MANAGED_BEGIN = "<!-- pp-echo-memory:begin -->"
MANAGED_END = "<!-- pp-echo-memory:end -->"


@dataclass(frozen=True)
class BootstrapMemorySyncResult:
    path: Path
    chars: int
    managed_chars: int


class BootstrapMemoryManager:
    """Maintains pp-Echo's managed section inside workspace MEMORY.md."""

    def __init__(self, *, workspace: Path, settings: LearningSettings) -> None:
        self.workspace = workspace.resolve()
        self.settings = settings
        self.path = self.workspace / "MEMORY.md"

    def read(self) -> str:
        if not self.path.exists():
            return ""
        try:
            return self.path.read_text(encoding="utf-8-sig")
        except OSError:
            return ""

    def sync(self, project_memory: str) -> BootstrapMemorySyncResult:
        managed = self._managed_section(project_memory)
        existing = self.read()
        content = self._replace_managed_section(existing, managed)
        self.path.write_text(content, encoding="utf-8")
        return BootstrapMemorySyncResult(path=self.path, chars=len(content), managed_chars=len(managed))

    def _managed_section(self, project_memory: str) -> str:
        notes = _compact_bullets(project_memory, limit=max(400, self.settings.project_memory_char_limit - 900))
        navigation = self._memory_navigation(limit=1200)
        parts = [
            MANAGED_BEGIN,
            "## pp-Echo Bootstrap Memory",
            "",
            "Short-lived prompt memory for durable preferences, project decisions, and navigation.",
            "Use `memory_search` and `memory_get` for detailed notes in `memory/**/*.md`.",
            "",
            "### Learned Notes",
            notes or "- No applied project memory yet.",
            "",
            "### Detailed Memory Index",
            navigation or "- No detailed memory markdown files found.",
            MANAGED_END,
        ]
        managed = "\n".join(parts).strip() + "\n"
        if len(managed) <= self.settings.project_memory_char_limit:
            return managed
        notes_budget = max(200, self.settings.project_memory_char_limit - len(management_shell(navigation)))
        compact_notes = _compact_bullets(project_memory, limit=notes_budget)
        return "\n".join(
            [
                MANAGED_BEGIN,
                "## pp-Echo Bootstrap Memory",
                "",
                "Short-lived prompt memory for durable preferences, project decisions, and navigation.",
                "Use `memory_search` and `memory_get` for detailed notes in `memory/**/*.md`.",
                "",
                "### Learned Notes",
                compact_notes or "- No applied project memory yet.",
                "",
                "### Detailed Memory Index",
                navigation or "- No detailed memory markdown files found.",
                MANAGED_END,
            ]
        ).strip() + "\n"

    def _memory_navigation(self, *, limit: int) -> str:
        memory_dir = self.workspace / "memory"
        if not memory_dir.exists():
            return ""
        lines: list[str] = []
        for path in sorted(memory_dir.rglob("*.md")):
            if not path.is_file():
                continue
            try:
                resolved = path.resolve()
                resolved.relative_to(self.workspace)
            except (OSError, ValueError):
                continue
            rel = path.relative_to(self.workspace).as_posix()
            heading = _first_heading(path) or path.stem.replace("-", " ").replace("_", " ").title()
            lines.append(f"- `{rel}` - {heading}")
            if len("\n".join(lines)) >= limit:
                lines.append("- More detailed memory files exist; use `memory_search` for discovery.")
                break
        return "\n".join(lines)[:limit].rstrip()

    @staticmethod
    def _replace_managed_section(existing: str, managed: str) -> str:
        if not existing.strip():
            return "# Project Memory\n\n" + managed
        start = existing.find(MANAGED_BEGIN)
        end = existing.find(MANAGED_END)
        if start != -1 and end != -1 and end >= start:
            end += len(MANAGED_END)
            return (existing[:start].rstrip() + "\n\n" + managed + existing[end:].lstrip()).strip() + "\n"
        return existing.rstrip() + "\n\n" + managed


def management_shell(navigation: str) -> str:
    return "\n".join(
        [
            MANAGED_BEGIN,
            "## pp-Echo Bootstrap Memory",
            "Short-lived prompt memory for durable preferences, project decisions, and navigation.",
            "Use `memory_search` and `memory_get` for detailed notes in `memory/**/*.md`.",
            "### Learned Notes",
            "### Detailed Memory Index",
            navigation,
            MANAGED_END,
        ]
    )


def _compact_bullets(text: str, *, limit: int) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        key = " ".join(line.lower().split())
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
    compact = "\n".join(lines).strip()
    if len(compact) <= limit:
        return compact
    kept: list[str] = []
    total = 0
    for line in reversed(lines):
        needed = len(line) + (1 if kept else 0)
        if total + needed > limit:
            continue
        kept.append(line)
        total += needed
    kept.reverse()
    return "\n".join(kept).strip()


def _first_heading(path: Path) -> str:
    try:
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if line.startswith("#"):
                return line.lstrip("#").strip()
    except OSError:
        return ""
    return ""


__all__ = ["BootstrapMemoryManager", "BootstrapMemorySyncResult", "MANAGED_BEGIN", "MANAGED_END"]
