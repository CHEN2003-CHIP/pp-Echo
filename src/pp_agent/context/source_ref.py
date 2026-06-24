from __future__ import annotations

from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field, field_validator


SourceType = Literal[
    "system",
    "markdown_memory",
    "core_governance",
    "core_memory",
    "episodic_memory",
    "file_memory",
    "attachment",
    "mcp",
    "skill",
    "runtime",
    "project_map",
    "module_doc",
    "adr",
    "capability",
    "project_context",
    "conversation",
]

SECRET_METADATA_MARKERS = ("api_key", "token", "secret", "password")


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

        payload = self.model_dump(mode="json", exclude_none=True)
        metadata = _trace_safe_metadata(self.metadata)
        if metadata:
            payload["metadata"] = metadata
        return payload


def _trace_safe_metadata(metadata: Dict[str, object]) -> dict[str, object]:
    """Keep small provenance metadata while dropping secret-like keys."""

    safe: dict[str, object] = {}
    for key, value in metadata.items():
        lowered = str(key).lower()
        if any(marker in lowered for marker in SECRET_METADATA_MARKERS):
            continue
        if isinstance(value, dict):
            nested = _trace_safe_metadata({str(k): v for k, v in value.items()})
            if nested:
                safe[str(key)] = nested
        elif isinstance(value, list):
            safe[str(key)] = [_safe_scalar(item) for item in value[:20]]
        else:
            safe[str(key)] = _safe_scalar(value)
    return safe


def _safe_scalar(value: object) -> object:
    """Return a bounded JSON-safe scalar for trace metadata."""

    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str):
            return value[:500]
        return value
    return str(value)[:500]
