from __future__ import annotations

import json
from pathlib import Path

from pp_agent.learning.models import LearningCandidate, LearningStatusSummary


class LearningStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.candidates_path = root / "candidates.jsonl"
        self.memory_path = root / "memory.md"

    def append_candidates(self, candidates: list[LearningCandidate]) -> None:
        if not candidates:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        with self.candidates_path.open("a", encoding="utf-8") as handle:
            for candidate in candidates:
                handle.write(candidate.model_dump_json() + "\n")

    def list_candidates(self, *, status: str | None = None) -> list[LearningCandidate]:
        items = self._read_all()
        if status is None:
            return items
        return [item for item in items if item.status == status]

    def get(self, candidate_id: str) -> LearningCandidate | None:
        for candidate in self._read_all():
            if candidate.id == candidate_id:
                return candidate
        return None

    def update(self, updated: LearningCandidate) -> None:
        items = self._read_all()
        found = False
        next_items: list[LearningCandidate] = []
        for item in items:
            if item.id == updated.id:
                next_items.append(updated)
                found = True
            else:
                next_items.append(item)
        if not found:
            next_items.append(updated)
        self._write_all(next_items)

    def append_project_memory(self, entry: str) -> None:
        text = entry.strip()
        if not text:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        existing = self.read_project_memory().strip()
        content = f"{existing}\n\n{text}\n" if existing else f"{text}\n"
        self.memory_path.write_text(content, encoding="utf-8")

    def has_similar_project_memory(self, entry: str) -> bool:
        normalized = _normalize_memory_text(entry)
        if not normalized:
            return False
        haystack = _normalize_memory_text(self.read_project_memory())
        return normalized in haystack

    def replace_project_memory(self, content: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.memory_path.write_text(content.strip() + "\n", encoding="utf-8")

    def read_project_memory(self) -> str:
        if not self.memory_path.exists():
            return ""
        return self.memory_path.read_text(encoding="utf-8")

    def summary(self, *, project_skill_count: int = 0) -> LearningStatusSummary:
        counts = {"pending": 0, "applied": 0, "rejected": 0}
        for candidate in self._read_all():
            counts[candidate.status] = counts.get(candidate.status, 0) + 1
        return LearningStatusSummary(
            pending_count=counts["pending"],
            applied_count=counts["applied"],
            rejected_count=counts["rejected"],
            project_memory_chars=len(self.read_project_memory()),
            project_skill_count=project_skill_count,
        )

    def _read_all(self) -> list[LearningCandidate]:
        if not self.candidates_path.exists():
            return []
        items: list[LearningCandidate] = []
        for line in self.candidates_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                items.append(LearningCandidate.model_validate(payload))
            except (json.JSONDecodeError, ValueError):
                continue
        return items

    def _write_all(self, items: list[LearningCandidate]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        content = "".join(item.model_dump_json() + "\n" for item in items)
        self.candidates_path.write_text(content, encoding="utf-8")


def _normalize_memory_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip().lower()
