from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.memory.core_store import CoreMemoryStore
from pp_agent.memory.core_types import CoreMemory, CoreMemoryBudgetReport
from pp_agent.runtime.state import AgentState

if TYPE_CHECKING:
    from pp_agent.memory.core_service import CoreMemoryService


SECTION_ORDER = ("user_profile", "project_profile", "agent_notes")
SECTION_TITLES = {
    "user_profile": "User Profile",
    "project_profile": "Project Profile",
    "agent_notes": "Agent Notes",
}
TYPE_WEIGHT = {
    "preference": 5,
    "project_fact": 5,
    "decision": 4,
    "workflow": 4,
    "error_fix": 3,
    "general": 1,
}
CORE_MEMORY_METADATA_KEY = "core_memory_snapshot"


@dataclass(frozen=True)
class CoreMemoryBudget:
    user_profile_chars: int = 1200
    project_profile_chars: int = 2000
    agent_notes_chars: int = 1500
    total_chars: int = 4000

    def section_limit(self, section: str) -> int:
        return int(getattr(self, f"{section}_chars"))


@dataclass
class CoreMemoryRenderer:
    budget: CoreMemoryBudget = field(default_factory=CoreMemoryBudget)

    def render(self, memories: list[CoreMemory]) -> str:
        selected_by_section, _skipped = self._select(memories)
        blocks: list[str] = ["[Core Memory Snapshot]", ""]
        rendered_any = False
        for section in SECTION_ORDER:
            section_memories = selected_by_section.get(section, [])
            if not section_memories:
                continue
            rendered_any = True
            blocks.append(f"<{SECTION_TITLES[section]}>")
            blocks.extend(f"- {memory.content}" for memory in section_memories)
            blocks.append("")
        if not rendered_any:
            return ""
        blocks.append("[/Core Memory Snapshot]")
        return "\n".join(blocks).strip()

    def render_with_report(self, memories: list[CoreMemory]) -> tuple[str, CoreMemoryBudgetReport]:
        selected_by_section, skipped_reasons = self._select(memories)
        selected = [memory for section in SECTION_ORDER for memory in selected_by_section.get(section, [])]
        snapshot = self.render(selected)
        active_ids = {memory.id for memory in memories if memory.status == "active"}
        included_ids = [memory.id for memory in selected]
        skipped_ids = [memory_id for memory_id in active_ids if memory_id not in set(included_ids)]
        for memory_id in skipped_ids:
            skipped_reasons.setdefault(memory_id, "budget")
        report = CoreMemoryBudgetReport(
            budget_status="over_budget" if skipped_ids else "ok",
            current_chars=len(snapshot),
            projected_chars=len(snapshot),
            included_ids=included_ids,
            skipped_ids=skipped_ids,
            skipped_reasons=skipped_reasons,
            needs_compaction=bool(skipped_ids),
        )
        return snapshot, report

    def would_exceed(self, memories: list[CoreMemory], candidate: CoreMemory) -> bool:
        rendered = self.render([*memories, candidate])
        return bool(rendered) and len(rendered) > self.budget.total_chars

    def _select(self, memories: list[CoreMemory]) -> tuple[dict[str, list[CoreMemory]], dict[str, str]]:
        active = [memory for memory in memories if memory.status == "active"]
        selected: dict[str, list[CoreMemory]] = {}
        skipped: dict[str, str] = {}
        total_used = len("[Core Memory Snapshot]\n\n[/Core Memory Snapshot]")
        for section in SECTION_ORDER:
            candidates = [memory for memory in active if memory.section == section]
            section_items: list[CoreMemory] = []
            section_used = 0
            for memory in sorted(candidates, key=self._rank, reverse=True):
                line_len = len(f"- {memory.content}\n")
                if section_used + line_len > self.budget.section_limit(section):
                    skipped[memory.id] = "section_budget"
                    continue
                if total_used + line_len > self.budget.total_chars:
                    skipped[memory.id] = "total_budget"
                    continue
                section_items.append(memory)
                section_used += line_len
                total_used += line_len
            if section_items:
                selected[section] = sorted(section_items, key=lambda item: (item.section, item.created_at, item.id))
        return selected, skipped

    @staticmethod
    def _rank(memory: CoreMemory) -> tuple[float, float, int]:
        return (memory.confidence, memory.updated_at, TYPE_WEIGHT.get(memory.type, 0))


@dataclass
class CoreMemoryContextHook:
    store: CoreMemoryStore
    workspace_id: str
    renderer: CoreMemoryRenderer = field(default_factory=CoreMemoryRenderer)
    enabled: bool = True
    service: "CoreMemoryService | None" = None
    _frozen_snapshot: str | None = field(default=None, init=False, repr=False)
    _frozen_result: object | None = field(default=None, init=False, repr=False)

    def transform_context(self, state: AgentState | None, messages: list[ChatMessage]) -> list[ChatMessage]:
        if not self.enabled:
            return messages
        snapshot = self.snapshot()
        if not snapshot:
            return messages
        if state is not None:
            result = self.snapshot_result()
            state.memory_context[CORE_MEMORY_METADATA_KEY] = {
                "workspace_id": self.workspace_id,
                "chars": len(snapshot),
                "frozen": True,
                "included_ids": getattr(result, "included_ids", []),
                "skipped_ids": getattr(result, "skipped_ids", []),
                "snapshot_hash": getattr(result, "snapshot_hash", ""),
            }
        message = ChatMessage(
            role="system",
            content=[TextPart(text=snapshot)],
            metadata={CORE_MEMORY_METADATA_KEY: {"workspace_id": self.workspace_id, "frozen": True}},
            timestamp=0.0,
        )
        return [*messages[:1], message, *messages[1:]] if messages and messages[0].role == "system" else [message, *messages]

    def snapshot(self) -> str:
        if self._frozen_snapshot is None:
            self._frozen_snapshot = self.snapshot_result().snapshot
        return self._frozen_snapshot

    def snapshot_result(self):
        if self._frozen_result is None:
            if self.service is not None:
                self._frozen_result = self.service.snapshot(workspace_id=self.workspace_id)
            else:
                memories = self.store.list_active(workspace_id=self.workspace_id)
                snapshot, budget = self.renderer.render_with_report(memories)
                from pp_agent.memory.core_types import CoreMemorySnapshotResult

                self._frozen_result = CoreMemorySnapshotResult(
                    snapshot=snapshot,
                    workspace_id=self.workspace_id,
                    included_ids=budget.included_ids,
                    skipped_ids=budget.skipped_ids,
                    skipped_reasons=budget.skipped_reasons,
                    chars=len(snapshot),
                    budget=budget,
                )
        return self._frozen_result


def workspace_id_for_path(path) -> str:
    return str(path.resolve()).lower()
