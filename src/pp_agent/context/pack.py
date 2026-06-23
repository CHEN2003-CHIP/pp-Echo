from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from pp_agent.context.budget import ContextBudgetReport
from pp_agent.context.item import ContextItem
from pp_agent.context.source_ref import SourceRef


class ContextPack(BaseModel):
    """Serializable context assembled for a model call or debug report."""

    system_instructions: List[ContextItem] = Field(default_factory=list)
    model_profile_summary: List[ContextItem] = Field(default_factory=list)
    runtime_profile_summary: List[ContextItem] = Field(default_factory=list)
    core_memory_snapshot: List[ContextItem] = Field(default_factory=list)
    episodic_memory_items: List[ContextItem] = Field(default_factory=list)
    attachment_previews: List[ContextItem] = Field(default_factory=list)
    selected_capabilities: List[ContextItem] = Field(default_factory=list)
    project_context: List[ContextItem] = Field(default_factory=list)
    recent_turns: List[ContextItem] = Field(default_factory=list)
    runtime_notes: List[ContextItem] = Field(default_factory=list)
    source_refs: List[SourceRef] = Field(default_factory=list)
    budget_report: ContextBudgetReport

    def trace_summary(self) -> dict[str, object]:
        """Return the bounded summary used by context_built trace events."""

        return {
            "context_payload_version": 2,
            "context": {
                "included_sources": [item.model_dump(mode="json") for item in self.budget_report.included_items],
                "dropped_sources": [item.model_dump(mode="json") for item in self.budget_report.dropped_items],
                "budget_report": self.budget_report.model_dump(mode="json"),
            },
        }
