from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from pp_agent.learning.bootstrap_memory import BootstrapMemoryManager, GlobalBootstrapMemoryManager
from pp_agent.learning.curator import LearningCurator
from pp_agent.learning.models import LearningCandidate, LearningSettings
from pp_agent.learning.safety import clean_learning_text
from pp_agent.learning.store import LearningStore
from pp_agent.storage.settings import Settings


logger = logging.getLogger(__name__)

DETAIL_BEGIN = "<!-- pp-echo-detail-memory:begin -->"
DETAIL_END = "<!-- pp-echo-detail-memory:end -->"

CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class FileMemoryWriteResult:
    candidate_id: str          # 候选项 ID
    action: str                # 执行的动作：global_bootstrap, workspace_bootstrap, journal, detailed_memory, ignored, skipped, pending_* 等
    path: Path | None = None   # 写入的文件路径（如果有）
    warnings: list[str] = field(default_factory=list)  # 非致命警告列表


class FileMemoryWriter:
    def __init__(self, *, workspace: Path, settings: LearningSettings, store: LearningStore | None = None) -> None:
        self.workspace = workspace.resolve()
        self.settings = settings
        self.store = store or LearningStore(self.workspace / ".pp-agent" / "learning")
        self.curator = LearningCurator(workspace=self.workspace, settings=settings)
        self.global_root = Settings.load(self.workspace).global_dir

    def auto_apply(self, candidates: list[LearningCandidate]) -> list[FileMemoryWriteResult]:
        """自动应用一批候选项，并触发后续同步。"""
        results: list[FileMemoryWriteResult] = []
        if not self.settings.auto_apply_memory:
            return results
        wrote_bootstrap = False
        wrote_indexed_memory = False
        for candidate in candidates:
            result = self.apply_candidate(candidate, auto=True)
            results.append(result)
            wrote_bootstrap = wrote_bootstrap or result.action in {"workspace_bootstrap", "detailed_memory"}
            wrote_indexed_memory = wrote_indexed_memory or result.action in {
                "global_bootstrap",
                "workspace_bootstrap",
                "journal",
                "detailed_memory",
            }
        if wrote_bootstrap:
            self._sync_bootstrap_memory()
        if wrote_indexed_memory and self.settings.detailed_memory_sync_index_after_write:
            self._sync_file_memory_index(results)
        return results

    def apply_candidate(self, candidate: LearningCandidate, *, auto: bool = False) -> FileMemoryWriteResult:
        """核心决策和路由方法，决定每个候选项被写入何处"""
        if candidate.status != "pending":
            return FileMemoryWriteResult(candidate_id=candidate.id, action="skipped")
        if candidate.suggested_target == "ignore":
            self.store.update(candidate.mark_rejected())
            return FileMemoryWriteResult(candidate_id=candidate.id, action="ignored")
        if candidate.suggested_target == "skill":
            return FileMemoryWriteResult(candidate_id=candidate.id, action="pending_skill")

        target = self._resolve_target(candidate)
        if auto and target != "journal":
            if not self._meets_auto_confidence(candidate):
                return FileMemoryWriteResult(candidate_id=candidate.id, action="pending_low_confidence")
            if not self._should_auto_promote(candidate, target=target):
                return FileMemoryWriteResult(candidate_id=candidate.id, action="pending_promotion")
            candidate = candidate.mark_promoted(target, reason="auto_promotion")
            self.store.update(candidate)
        elif not auto and target != "journal" and candidate.promoted_target is None:
            candidate = candidate.mark_promoted(target, reason="manual_apply")
            self.store.update(candidate)

        if target == "global_bootstrap":
            path = self._apply_global_bootstrap_candidate(candidate)
            self.store.update(candidate.mark_applied())
            return FileMemoryWriteResult(candidate_id=candidate.id, action="global_bootstrap", path=path)
        if target == "workspace_bootstrap":
            path = self._apply_workspace_bootstrap_candidate(candidate)
            self.store.update(candidate.mark_applied())
            return FileMemoryWriteResult(candidate_id=candidate.id, action="workspace_bootstrap", path=path)
        if target == "journal":
            path = self._apply_journal_candidate(candidate)
            self.store.update(candidate.mark_applied())
            return FileMemoryWriteResult(candidate_id=candidate.id, action="journal", path=path)
        if target == "detailed" and self.settings.detailed_memory_enable:
            path = self._append_detailed_memory(candidate)
            self.store.update(candidate.mark_applied())
            return FileMemoryWriteResult(candidate_id=candidate.id, action="detailed_memory", path=path)
        return FileMemoryWriteResult(candidate_id=candidate.id, action="pending_promotion")

    def _resolve_target(self, candidate: LearningCandidate) -> str:
        """根据候选项的建议目标，决定写入何处"""
        if candidate.promoted_target in {"global_bootstrap", "workspace_bootstrap", "journal", "detailed"}:
            return candidate.promoted_target
        if candidate.suggested_target == "bootstrap_memory":
            return "workspace_bootstrap"
        if candidate.suggested_target == "detailed_memory":
            return "detailed"
        if candidate.suggested_target in {"global_bootstrap", "workspace_bootstrap", "journal", "detailed"}:
            return candidate.suggested_target
        if candidate.suggested_target == "memory":
            return self._classify_memory_target(candidate)
        return "journal"

    def _classify_memory_target(self, candidate: LearningCandidate) -> str:
        """模糊分别处理 memory 类型候选项"""
        if candidate.kind == "user_preference":
            return "global_bootstrap"
        if candidate.kind == "project_convention":
            return "workspace_bootstrap"
        text = f"{candidate.kind} {candidate.title} {candidate.content}".lower()
        if any(marker in text for marker in ("today", "recent", "smoke", "temporary")):
            return "journal"
        detailed_markers = (
            "bug",
            "fix",
            "failed",
            "failure",
            "error",
            "traceback",
            "architecture",
            "design",
            "decision",
            "debug",
            "investigate",
            "workflow",
            "procedure",
        )
        if candidate.kind in {"workflow", "lesson"} and any(marker in text for marker in detailed_markers):
            return "detailed"
        if len(candidate.content) > 600:
            return "detailed"
        return "workspace_bootstrap"

    def _should_auto_promote(self, candidate: LearningCandidate, *, target: str) -> bool:
        if self._looks_one_off(candidate):
            #一次性
            return False
        if target == "global_bootstrap":
            #仅用户偏好
            return candidate.kind == "user_preference"
        if target == "workspace_bootstrap":
            #仅项目约定
            return (
                candidate.kind in {"project_convention", "workflow", "lesson"}
                and not self.store.has_similar_project_memory(self.curator.memory_entry(candidate))
            )
        if target == "detailed":
            return True
        return True

    def _looks_one_off(self, candidate: LearningCandidate) -> bool:
        text = f"{candidate.title} {candidate.content} {candidate.evidence}".lower()
        one_off_markers = (
            "tmp",
            "temp",
            "one-off",
            "temporary",
            "artifact",
            "single run",
            "docs/worktree-smoke-web.md",
            "worktree-smoke",
        )
        return any(marker in text for marker in one_off_markers)

    def _apply_global_bootstrap_candidate(self, candidate: LearningCandidate) -> Path:
        manager = GlobalBootstrapMemoryManager(global_root=self.global_root, settings=self.settings)
        entry = self.curator.memory_entry(candidate)
        existing = manager.learned_notes()
        if _normalized(entry) in _normalized(existing):
            return manager.path
        content = "\n\n".join(part for part in [existing.strip(), entry] if part.strip()).strip()
        manager.sync(content)
        return manager.path

    def _apply_workspace_bootstrap_candidate(self, candidate: LearningCandidate) -> Path:
        entry = self.curator.memory_entry(candidate)
        if not self.store.has_similar_project_memory(entry):
            self.store.append_project_memory(entry)
            self._compact_project_memory_if_needed()
        self._sync_bootstrap_memory()
        return self.workspace / "MEMORY.md"

    def _apply_journal_candidate(self, candidate: LearningCandidate) -> Path:
        path = self.workspace / "memory" / "daily" / f"{time.strftime('%Y-%m-%d')}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = self._journal_entry(candidate)
        existing = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        if _normalized(entry) in _normalized(existing):
            return path
        if existing.strip():
            content = existing.rstrip() + "\n\n" + entry + "\n"
        else:
            content = f"# Daily Journal\n\n{entry}\n"
        path.write_text(content, encoding="utf-8")
        return path

    def _journal_entry(self, candidate: LearningCandidate) -> str:
        title = clean_learning_text(candidate.title, limit=120) or "Untitled note"
        content = clean_learning_text(candidate.content, limit=1200)
        evidence = clean_learning_text(candidate.evidence, limit=400)
        lines = [f"## {title}", "", content]
        if evidence:
            lines.extend(["", f"Evidence: {evidence}"])
        lines.extend(["", f"Source: session={candidate.source_session_id} turn={candidate.source_turn_id}"])
        return "\n".join(lines).strip()

    def _append_detailed_memory(self, candidate: LearningCandidate) -> Path:
        path = self._detailed_memory_path(candidate)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = self._detail_entry(candidate)
        existing = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        managed = self._extract_managed(existing)
        next_managed = "\n\n".join(part for part in [managed.strip(), entry] if part).strip()
        if self.settings.detailed_memory_auto_consolidate:
            next_managed = self._compact_detail(next_managed)
        content = self._replace_managed(existing, path=path, managed=next_managed)
        path.write_text(content, encoding="utf-8")
        return path

    def _detail_entry(self, candidate: LearningCandidate) -> str:
        title = clean_learning_text(candidate.title, limit=120) or "Untitled memory"
        content = clean_learning_text(candidate.content, limit=1800)
        evidence = clean_learning_text(candidate.evidence, limit=600)
        lines = [f"### {title}", "", content]
        if evidence:
            lines.extend(["", f"Evidence: {evidence}"])
        lines.extend(["", f"Source: session={candidate.source_session_id} turn={candidate.source_turn_id}"])
        return "\n".join(lines).strip()

    def _detailed_memory_path(self, candidate: LearningCandidate) -> Path:
        text = f"{candidate.kind} {candidate.title} {candidate.content}".lower()
        if candidate.kind == "user_preference":
            name = "preferences.md"
        elif any(marker in text for marker in ("architecture", "design", "decision")):
            name = "architecture.md"
        elif any(marker in text for marker in ("bug", "fix", "failed", "failure", "error", "traceback")):
            name = "bugs.md"
        elif any(marker in text for marker in ("debug", "investigate", "diagnose")):
            name = "debugging.md"
        elif candidate.kind == "workflow" or any(marker in text for marker in ("workflow", "procedure")):
            name = "workflows.md"
        else:
            name = "lessons.md"
        return self.workspace / "memory" / name

    def _compact_project_memory_if_needed(self) -> None:
        current = self.store.read_project_memory()
        if len(current) <= self.settings.project_memory_char_limit:
            return
        compact = self.curator.consolidated_memory(current, [])
        self.store.replace_project_memory(_fit_store_text(compact, self.settings.project_memory_char_limit))

    def _sync_bootstrap_memory(self) -> None:
        BootstrapMemoryManager(workspace=self.workspace, settings=self.settings).sync(self.store.read_project_memory())

    def _sync_file_memory_index(self, results: list[FileMemoryWriteResult]) -> None:
        try:
            from pp_agent.memory.file_memory_tools import build_file_memory_search_engine

            build_file_memory_search_engine(self.workspace, settings=Settings.load(self.workspace)).sync()
        except Exception as exc:  # noqa: BLE001
            logger.warning("File memory sync failed after auto learning write: %s", exc)
            for index, result in enumerate(results):
                if result.action in {"global_bootstrap", "workspace_bootstrap", "journal", "detailed_memory"}:
                    warnings = [*result.warnings, f"File memory sync failed: {exc}"]
                    results[index] = FileMemoryWriteResult(
                        candidate_id=result.candidate_id,
                        action=result.action,
                        path=result.path,
                        warnings=warnings,
                    )
                    break

    def _meets_auto_confidence(self, candidate: LearningCandidate) -> bool:
        return CONFIDENCE_ORDER.get(candidate.confidence, 0) >= CONFIDENCE_ORDER.get(self.settings.auto_apply_min_confidence, 1)

    def _compact_detail(self, managed: str) -> str:
        lines: list[str] = []
        seen: set[str] = set()
        for raw_line in managed.splitlines():
            line = raw_line.rstrip()
            key = " ".join(line.lower().split())
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            lines.append(line)
        text = "\n".join(lines).strip()
        if len(text) <= self.settings.detailed_memory_char_limit:
            return text
        return text[-self.settings.detailed_memory_char_limit :].strip()

    @staticmethod
    def _extract_managed(content: str) -> str:
        start = content.find(DETAIL_BEGIN)
        end = content.find(DETAIL_END)
        if start == -1 or end == -1 or end < start:
            return ""
        start += len(DETAIL_BEGIN)
        return content[start:end].strip()

    @staticmethod
    def _replace_managed(existing: str, *, path: Path, managed: str) -> str:
        section = f"{DETAIL_BEGIN}\n{managed.strip()}\n{DETAIL_END}\n"
        if not existing.strip():
            title = path.stem.replace("-", " ").replace("_", " ").title()
            return f"# {title}\n\n{section}"
        start = existing.find(DETAIL_BEGIN)
        end = existing.find(DETAIL_END)
        if start != -1 and end != -1 and end >= start:
            end += len(DETAIL_END)
            return (existing[:start].rstrip() + "\n\n" + section + existing[end:].lstrip()).strip() + "\n"
        return existing.rstrip() + "\n\n" + section


def _fit_store_text(content: str, limit: int) -> str:
    text = content.strip()
    if len(text) + 1 <= limit:
        return text
    return text[-max(0, limit - 1) :].strip()


def _normalized(value: str) -> str:
    return " ".join(str(value or "").lower().split()).strip()


__all__ = ["DETAIL_BEGIN", "DETAIL_END", "FileMemoryWriteResult", "FileMemoryWriter"]
