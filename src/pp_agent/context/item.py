from __future__ import annotations

from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from pp_agent.context.source_ref import SourceRef


ContextItemType = Literal[
    "system_instruction",
    "model_profile",
    "runtime_profile",
    "core_memory",
    "episodic_memory",
    "attachment_preview",
    "capability",
    "project_context",
    "conversation",
    "runtime_note",
]


class ContextItem(BaseModel):
    """One independently budgeted unit that may enter a model context pack."""

    id: str
    type: ContextItemType
    title: str
    content: str
    source_ref: SourceRef
    priority: int = 0
    estimated_tokens: Optional[int] = None
    estimated_chars: Optional[int] = None
    metadata: Dict[str, object] = Field(default_factory=dict)

    @field_validator("id", "title", "content")
    @classmethod
    def _required_text(cls, value: str) -> str:
        """Keep context item identity and content non-empty."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("context item text fields cannot be empty")
        return normalized

    @field_validator("priority")
    @classmethod
    def _priority_int(cls, value: int) -> int:
        """Normalize priority to an integer for deterministic budget sorting."""

        return int(value)

    @field_validator("estimated_tokens", "estimated_chars")
    @classmethod
    def _non_negative_estimates(cls, value: Optional[int]) -> Optional[int]:
        """Reject negative budget estimates."""

        if value is not None and value < 0:
            raise ValueError("context item estimates cannot be negative")
        return value

    @model_validator(mode="after")
    def _fill_char_estimate(self) -> "ContextItem":
        """Use character count as the default budget unit for the first pipeline pass."""

        if self.estimated_chars is None:
            self.estimated_chars = len(self.content)
        return self

    @property
    def budget_chars(self) -> int:
        """Return the character estimate used by the current budget strategy."""

        return int(self.estimated_chars if self.estimated_chars is not None else len(self.content))

    def summary(self) -> dict[str, object]:
        """Return a trace-safe item summary without full content."""

        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "priority": self.priority,
            "estimated_chars": self.budget_chars,
            "source_ref": self.source_ref.summary(),
        }
