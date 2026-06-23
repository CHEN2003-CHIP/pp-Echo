from __future__ import annotations

from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field, field_validator


SourceType = Literal[
    "core_memory",
    "episodic_memory",
    "attachment",
    "project_map",
    "module_doc",
    "adr",
    "capability",
    "conversation",
]


class SourceRef(BaseModel):
    """Trace-safe provenance for a context item."""

    source_type: SourceType
    source_id: Optional[str] = None
    path: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    page: Optional[int] = None
    heading: Optional[str] = None
    confidence: float = 1.0
    metadata: Dict[str, object] = Field(default_factory=dict)

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, value: float) -> float:
        """Clamp confidence into the display-safe 0..1 range."""

        return max(0.0, min(1.0, float(value)))

    @field_validator("line_start", "line_end", "page")
    @classmethod
    def _positive_positions(cls, value: Optional[int]) -> Optional[int]:
        """Reject non-positive source positions while allowing unknown positions."""

        if value is not None and value < 1:
            raise ValueError("source positions are 1-based")
        return value

    def summary(self) -> dict[str, object]:
        """Return a bounded source summary suitable for trace payloads."""

        return self.model_dump(mode="json", exclude_none=True, exclude={"metadata"})
