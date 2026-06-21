from __future__ import annotations

import time
import uuid
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


CoreMemoryScope = Literal["global", "workspace"]
CoreMemorySection = Literal["user_profile", "project_profile", "agent_notes"]
CoreMemoryType = Literal["preference", "project_fact", "decision", "workflow", "error_fix", "general"]
CoreMemoryStatus = Literal["pending", "active", "rejected", "archived"]


class CoreMemorySource(BaseModel):
    """Structured provenance is kept even when only part of the source is known."""

    session_id: Optional[str] = None
    turn_id: Optional[str] = None
    message_id: Optional[str] = None
    file_path: Optional[str] = None
    line_range: Optional[str] = None


class CoreMemory(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scope: CoreMemoryScope = "workspace"
    workspace_id: Optional[str] = None
    section: CoreMemorySection = "project_profile"
    type: CoreMemoryType = "general"
    content: str
    source: CoreMemorySource = Field(default_factory=CoreMemorySource)
    confidence: float = 0.5
    status: CoreMemoryStatus = "pending"
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    supersedes: List[str] = Field(default_factory=list)
    expires_at: Optional[float] = None
    metadata: Dict[str, object] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def _content_required(cls, value: str) -> str:
        content = " ".join(value.split()).strip()
        if not content:
            raise ValueError("core memory content cannot be empty")
        return content

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @model_validator(mode="after")
    def _scope_rules(self) -> "CoreMemory":
        if self.scope == "global" and self.section != "user_profile":
            raise ValueError("global core memory is limited to user_profile")
        if self.scope == "global" and self.type in {"project_fact", "workflow", "error_fix"}:
            raise ValueError("global core memory cannot store project-specific facts")
        return self


class CoreMemoryCandidate(BaseModel):
    scope: CoreMemoryScope = "workspace"
    workspace_id: Optional[str] = None
    section: CoreMemorySection = "project_profile"
    type: CoreMemoryType = "general"
    content: str
    source: CoreMemorySource = Field(default_factory=CoreMemorySource)
    confidence: float = 0.5
    expires_at: Optional[float] = None
    metadata: Dict[str, object] = Field(default_factory=dict)

    def to_memory(self, *, status: CoreMemoryStatus = "pending") -> CoreMemory:
        return CoreMemory(
            scope=self.scope,
            workspace_id=self.workspace_id,
            section=self.section,
            type=self.type,
            content=self.content,
            source=self.source,
            confidence=self.confidence,
            status=status,
            expires_at=self.expires_at,
            metadata=dict(self.metadata),
        )


class CoreMemoryWriteResult(BaseModel):
    memory: CoreMemory
    warnings: List[str] = Field(default_factory=list)
    duplicate_of: Optional[str] = None
    safety: Dict[str, object] = Field(default_factory=dict)
    conflicts_with: List[str] = Field(default_factory=list)
    budget: Dict[str, object] = Field(default_factory=dict)
    audit: List[Dict[str, object]] = Field(default_factory=list)


class CoreMemoryAuditRecord(BaseModel):
    audit_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    memory_id: str
    action: str
    actor: str = "system"
    source: CoreMemorySource = Field(default_factory=CoreMemorySource)
    before_status: Optional[str] = None
    after_status: Optional[str] = None
    reason: str = ""
    created_at: float = Field(default_factory=time.time)
    metadata: Dict[str, object] = Field(default_factory=dict)


class CoreMemoryBudgetReport(BaseModel):
    budget_status: str = "ok"
    current_chars: int = 0
    projected_chars: int = 0
    included_ids: List[str] = Field(default_factory=list)
    skipped_ids: List[str] = Field(default_factory=list)
    skipped_reasons: Dict[str, str] = Field(default_factory=dict)
    needs_compaction: bool = False


class CoreMemorySnapshotResult(BaseModel):
    snapshot: str = ""
    workspace_id: str
    session_id: Optional[str] = None
    included_ids: List[str] = Field(default_factory=list)
    skipped_ids: List[str] = Field(default_factory=list)
    skipped_reasons: Dict[str, str] = Field(default_factory=dict)
    chars: int = 0
    snapshot_hash: str = ""
    budget: CoreMemoryBudgetReport = Field(default_factory=CoreMemoryBudgetReport)
