from __future__ import annotations

import time
import uuid
from typing import Optional
from typing import Literal

from pydantic import BaseModel, Field


LearningKind = Literal["project_convention", "lesson", "workflow", "user_preference", "skill_candidate"]
LearningTarget = Literal["memory", "skill", "ignore"]
LearningStatus = Literal["pending", "applied", "rejected"]
LearningConfidence = Literal["low", "medium", "high"]


class LearningSettings(BaseModel):
    enable: bool = True
    auto_extract: bool = True
    project_memory_enable: bool = True
    project_memory_char_limit: int = 4000
    candidate_limit_per_turn: int = 3
    min_confidence_to_suggest: LearningConfidence = "medium"
    llm_extractor_enable: bool = True


class LearningCandidate(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    kind: LearningKind = "lesson"
    title: str
    content: str
    evidence: str = ""
    confidence: LearningConfidence = "medium"
    suggested_target: LearningTarget = "memory"
    status: LearningStatus = "pending"
    source_session_id: str = ""
    source_turn_id: str = ""
    created_at: float = Field(default_factory=time.time)
    applied_at: Optional[float] = None

    def mark_applied(self) -> "LearningCandidate":
        return self.model_copy(update={"status": "applied", "applied_at": time.time()})

    def mark_rejected(self) -> "LearningCandidate":
        return self.model_copy(update={"status": "rejected"})


class LearningStatusSummary(BaseModel):
    pending_count: int = 0
    applied_count: int = 0
    rejected_count: int = 0
    project_memory_chars: int = 0
    project_skill_count: int = 0
