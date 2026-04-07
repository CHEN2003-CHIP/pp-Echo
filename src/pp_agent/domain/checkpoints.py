from __future__ import annotations

import time
import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field


CheckpointSnapshotType = Literal["head_snapshot", "stash_snapshot"]
CheckpointStatus = Literal["active", "restored", "dropped", "failed", "missing"]


class CheckpointFileStats(BaseModel):
    """Statistics about the files in the workspace at the time of checkpoint creation."""
    changed_file_count: int = 0
    has_dirty_workspace: bool = False
    has_untracked_files: bool = False
    files: list[str] = Field(default_factory=list)


class CheckpointEntry(BaseModel):
    """A entry representing a checkpoint in the system."""
    checkpoint_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workspace_root: str
    session_id: str
    head_id: Optional[str] = None
    turn_id: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    reason: str = "manual"
    snapshot_type: CheckpointSnapshotType = "head_snapshot"
    status: CheckpointStatus = "active"
    summary: str = ""
    file_stats: CheckpointFileStats = Field(default_factory=CheckpointFileStats)
    head_commit: str = ""
    branch_name: str = ""
    stash_ref: Optional[str] = None
    stash_message: Optional[str] = None
    test_summary: Optional[str] = None


class CheckpointRestorePreview(BaseModel):
    checkpoint_id: str
    snapshot_type: CheckpointSnapshotType
    session_id: str
    head_id: Optional[str] = None
    turn_id: Optional[str] = None
    reason: str
    summary: str = ""
    current_git_status: str = ""
    target_head_commit: str = ""
    target_branch: str = ""
    affected_files: list[str] = Field(default_factory=list)
    has_dirty_workspace: bool = False
    has_untracked_files: bool = False
    overwrite_risk: bool = False
    warning_messages: list[str] = Field(default_factory=list)


class SafeRewindPreview(BaseModel):
    mode: Literal["conversation_only", "workspace_only", "conversation_and_workspace"]
    checkpoint: Optional[CheckpointEntry] = None
    restore_preview: Optional[CheckpointRestorePreview] = None
    source_session_id: str
    target_session_id: Optional[str] = None
    target_head_id: Optional[str] = None
    target_turn_id: Optional[str] = None
    message_count: Optional[int] = None
    turn_count: Optional[int] = None
    warning_messages: list[str] = Field(default_factory=list)


class SafeRewindResult(BaseModel):
    mode: Literal["conversation_only", "workspace_only", "conversation_and_workspace"]
    checkpoint_id: Optional[str] = None
    snapshot_type: Optional[CheckpointSnapshotType] = None
    source_session_id: str
    session_id: Optional[str] = None
    active_head_id: Optional[str] = None
    restored_workspace: bool = False
    restored_conversation: bool = False
    warning_messages: list[str] = Field(default_factory=list)
