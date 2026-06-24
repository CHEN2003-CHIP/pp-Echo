from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from pp_agent.context.budget import ContextBudgetReport
from pp_agent.context.item import ContextItem
from pp_agent.context.source_ref import SourceRef
from pp_agent.domain import ChatMessage


class ContextPack(BaseModel):
    """Serializable context assembled for a model call or debug report."""

    system: List[ContextItem] = Field(default_factory=list)
    markdown_memory: List[ContextItem] = Field(default_factory=list)
    core_governance: List[ContextItem] = Field(default_factory=list)
    project_context: List[ContextItem] = Field(default_factory=list)
    episodic_recall: List[ContextItem] = Field(default_factory=list)
    file_memory_preview: List[ContextItem] = Field(default_factory=list)
    attachments: List[ContextItem] = Field(default_factory=list)
    capabilities: List[ContextItem] = Field(default_factory=list)
    mcp: List[ContextItem] = Field(default_factory=list)
    skills: List[ContextItem] = Field(default_factory=list)
    conversation: List[ContextItem] = Field(default_factory=list)
    runtime_notes: List[ContextItem] = Field(default_factory=list)
    model_profile_summary: List[ContextItem] = Field(default_factory=list)
    runtime_profile_summary: List[ContextItem] = Field(default_factory=list)
    source_refs: List[SourceRef] = Field(default_factory=list)
    budget_report: ContextBudgetReport
    warnings: List[str] = Field(default_factory=list)
    final_messages: list[ChatMessage] = Field(default_factory=list)

    @property
    def system_instructions(self) -> List[ContextItem]:
        return self.system

    @system_instructions.setter
    def system_instructions(self, value: List[ContextItem]) -> None:
        self.system = value

    @property
    def core_memory_snapshot(self) -> List[ContextItem]:
        return self.core_governance

    @core_memory_snapshot.setter
    def core_memory_snapshot(self, value: List[ContextItem]) -> None:
        self.core_governance = value

    @property
    def episodic_memory_items(self) -> List[ContextItem]:
        return self.episodic_recall

    @episodic_memory_items.setter
    def episodic_memory_items(self, value: List[ContextItem]) -> None:
        self.episodic_recall = value

    @property
    def attachment_previews(self) -> List[ContextItem]:
        return self.attachments

    @attachment_previews.setter
    def attachment_previews(self, value: List[ContextItem]) -> None:
        self.attachments = value

    @property
    def selected_capabilities(self) -> List[ContextItem]:
        return self.capabilities

    @selected_capabilities.setter
    def selected_capabilities(self, value: List[ContextItem]) -> None:
        self.capabilities = value

    @property
    def recent_turns(self) -> List[ContextItem]:
        return self.conversation

    @recent_turns.setter
    def recent_turns(self, value: List[ContextItem]) -> None:
        self.conversation = value

    def trace_summary(self) -> dict[str, object]:
        """Return the bounded summary used by context_built trace events."""

        return {
            "context_payload_version": 3,
            "context": {
                "included_sources": [item.model_dump(mode="json") for item in self.budget_report.included_items],
                "dropped_sources": [item.model_dump(mode="json") for item in self.budget_report.dropped_items],
                "budget_report": self.budget_report.model_dump(mode="json"),
                "source_refs": [ref.summary() for ref in self.source_refs],
                "warnings": list(self.warnings),
                "markdown_memory": {
                    "paths": [item.source_ref.path for item in self.markdown_memory if item.source_ref.path],
                    "content_hash": [
                        item.source_ref.metadata.get("content_hash")
                        for item in self.markdown_memory
                        if item.source_ref.metadata.get("content_hash")
                    ],
                    "truncated": any(bool(item.source_ref.metadata.get("truncated")) for item in self.markdown_memory),
                },
                "core_governance": {"prompt_injection_disabled": True, "included_count": len(self.core_governance)},
            },
        }
