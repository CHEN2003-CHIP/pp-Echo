from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from pydantic import BaseModel, Field

from pp_agent.context.item import ContextItem


class ContextItemSummary(BaseModel):
    """Trace-safe accounting entry for an included or dropped context item."""

    id: str
    type: str
    title: str
    section: str
    priority: int
    estimated_chars: int
    source_ref: dict[str, object] = Field(default_factory=dict)
    reason: Optional[str] = None


class ContextBudgetSectionUsage(BaseModel):
    """Budget usage for one ContextPack section."""

    budget: int
    used: int = 0
    included_count: int = 0
    dropped_count: int = 0


class ContextBudgetReport(BaseModel):
    """Explains how the ContextPipeline spent and dropped context budget."""

    total_budget: int
    used: int = 0
    per_section: Dict[str, ContextBudgetSectionUsage] = Field(default_factory=dict)
    included_items: List[ContextItemSummary] = Field(default_factory=list)
    dropped_items: List[ContextItemSummary] = Field(default_factory=list)
    drop_reasons: Dict[str, str] = Field(default_factory=dict)

    def record_included(self, section: str, item: ContextItem) -> None:
        """Append one included item and increment section usage."""

        summary = _summary_for(section, item)
        self.included_items.append(summary)
        usage = self.per_section.setdefault(section, ContextBudgetSectionUsage(budget=0))
        usage.used += summary.estimated_chars
        usage.included_count += 1
        self.used += summary.estimated_chars

    def record_dropped(self, section: str, item: ContextItem, reason: str) -> None:
        """Append one dropped item with an explicit drop reason."""

        summary = _summary_for(section, item, reason=reason)
        self.dropped_items.append(summary)
        self.drop_reasons[item.id] = reason
        usage = self.per_section.setdefault(section, ContextBudgetSectionUsage(budget=0))
        usage.dropped_count += 1


class ContextBudgetExceeded(RuntimeError):
    """Raised when a non-droppable section cannot fit its budget."""

    def __init__(self, message: str, report: ContextBudgetReport) -> None:
        super().__init__(message)
        self.report = report


class ContextBudgeter:
    """Applies deterministic per-section character budgets to ContextItems."""

    def __init__(self, *, total_budget: int, section_budgets: dict[str, int]) -> None:
        self.total_budget = int(total_budget)
        self.section_budgets = dict(section_budgets)
        self.report = ContextBudgetReport(total_budget=self.total_budget)
        for section, budget in self.section_budgets.items():
            self.report.per_section[section] = ContextBudgetSectionUsage(budget=int(budget))

    def select(
        self,
        section: str,
        items: Iterable[ContextItem],
        *,
        droppable: bool = True,
        drop_reason: Optional[str] = None,
    ) -> list[ContextItem]:
        """Include highest-priority whole items until the section budget is exhausted."""

        budget = self.section_budgets.get(section, self.total_budget)
        usage = self.report.per_section.setdefault(section, ContextBudgetSectionUsage(budget=budget))
        usage.budget = budget
        selected: list[ContextItem] = []
        ordered = sorted(enumerate(items), key=lambda pair: (-pair[1].priority, pair[0]))
        for _, item in ordered:
            size = item.budget_chars
            if usage.used + size <= budget:
                selected.append(item)
                self.report.record_included(section, item)
                continue
            reason = drop_reason or _drop_reason_for(item, droppable=bool(droppable))
            self.report.record_dropped(section, item, reason)
            if not droppable:
                raise ContextBudgetExceeded(
                    f"{section} item {item.id} exceeds budget and cannot be silently truncated",
                    self.report,
                )
        return selected


def _summary_for(section: str, item: ContextItem, *, reason: Optional[str] = None) -> ContextItemSummary:
    """Build a bounded item summary from a ContextItem."""

    return ContextItemSummary(
        id=item.id,
        type=item.type,
        title=item.title,
        section=section,
        priority=item.priority,
        estimated_chars=item.budget_chars,
        source_ref=item.source_ref.summary(),
        reason=reason,
    )


def _drop_reason_for(item: ContextItem, *, droppable: bool) -> str:
    """Choose a trace reason for an item dropped by budget."""

    if not droppable:
        return "core_memory_budget_exceeded_not_truncated"
    if item.metadata.get("context_provider") in {"mcp", "skill"}:
        return "context_budget_exceeded"
    return "section_budget_exceeded"

