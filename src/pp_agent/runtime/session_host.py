from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from pp_agent.domain.checkpoints import CheckpointEntry, SafeRewindPreview, SafeRewindResult
from pp_agent.runtime.git_checkpoint import GitCheckpointManager
from pp_agent.runtime.lifecycle import (
    CHECKPOINT_BEFORE_CREATE,
    CHECKPOINT_BEFORE_RESTORE,
    CHECKPOINT_CREATED,
    CHECKPOINT_RESTORE_FAILED,
    CHECKPOINT_RESTORE_PREVIEW,
    CHECKPOINT_RESTORED,
    SESSION_BEFORE_FORK,
    SESSION_BEFORE_SWITCH,
    SESSION_BEFORE_TREE,
    SESSION_FORKED,
    SESSION_RESTORE,
    SESSION_REWOUND,
    SESSION_SAFE_REWIND_COMPLETED,
    SESSION_SAFE_REWIND_STARTED,
    SESSION_START,
    SESSION_SWITCHED,
    SESSION_TREE_NAVIGATED,
    SESSION_TREE_VIEWED,
)
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.runtime.safe_rewind import SafeRewindOrchestrator
from pp_agent.runtime.state import AgentEvent
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.storage.checkpoints import CheckpointStore
from pp_agent.storage.sessions import SessionRecord, SessionStore, SessionTreeEntry

LifecycleSubscriber = Callable[[AgentEvent], None]
RuntimeFactory = Callable[[Path, SessionRecord, Optional[list[LifecycleSubscriber]]], AgentRuntime]
SessionStoreFactory = Callable[[Path], SessionStore]
PendingActionStoreFactory = Callable[[Path], PendingActionStore]
SessionDefaultsFactory = Callable[[Path], dict[str, Any]]
CheckpointStoreFactory = Callable[[Path], CheckpointStore]


class SwitchResult(BaseModel):
    session_id: str
    previous_session_id: str
    active_head_id: Optional[str] = None
    previous_head_id: Optional[str] = None
    target_head_id: Optional[str] = None


class ForkResult(BaseModel):
    source_session_id: str
    session_id: str
    source_head_id: Optional[str] = None
    active_head_id: Optional[str] = None


class NavigateResult(BaseModel):
    session_id: str
    previous_head_id: Optional[str] = None
    active_head_id: Optional[str] = None


class RewindResult(BaseModel):
    source_session_id: str
    session_id: str
    message_count: Optional[int] = None
    turn_count: Optional[int] = None


class SessionTreeView(BaseModel):
    current: Optional[dict[str, object]] = None
    parent: Optional[dict[str, object]] = None
    children: list[dict[str, object]] = Field(default_factory=list)
    turns: list[dict[str, object]] = Field(default_factory=list)
    turn_focus: Optional[dict[str, object]] = None
    entries: list[SessionTreeEntry] = Field(default_factory=list)
    sort_mode: str = "branch"
    session_id: Optional[str] = None


class SessionHost:
    def __init__(
        self,
        *,
        runtime_factory: RuntimeFactory,
        session_store_factory: SessionStoreFactory,
        pending_action_store_factory: PendingActionStoreFactory,
        session_defaults_factory: SessionDefaultsFactory,
        checkpoint_store_factory: CheckpointStoreFactory,
    ) -> None:
        self._runtime_factory = runtime_factory
        self._session_store_factory = session_store_factory
        self._pending_action_store_factory = pending_action_store_factory
        self._session_defaults_factory = session_defaults_factory
        self._checkpoint_store_factory = checkpoint_store_factory

    def create_session(self, workspace: Path, *, lifecycle_subscribers: Optional[list[LifecycleSubscriber]] = None) -> AgentRuntime:
        defaults = self._session_defaults_factory(workspace)
        store = self._session_store(workspace)
        record = store.create(defaults["system_prompt"], defaults["model"])
        store.save(record)
        return self._activate_runtime(
            workspace,
            record,
            lifecycle_subscribers=lifecycle_subscribers,
            event_type=SESSION_START,
            event_details={"new_session": True},
        )

    def restore_session(self, workspace: Path, session_id: str, *, lifecycle_subscribers: Optional[list[LifecycleSubscriber]] = None) -> AgentRuntime:
        record = self._session_store(workspace).load(session_id)
        return self._activate_runtime(
            workspace,
            record,
            lifecycle_subscribers=lifecycle_subscribers,
            event_type=SESSION_RESTORE,
            event_details={"active_head_id": record.active_head_id},
        )

    def switch_session(
        self,
        workspace: Path,
        current_session_id: str,
        target_session_id: str,
        *,
        target_head_id: Optional[str] = None,
        lifecycle_subscribers: Optional[list[LifecycleSubscriber]] = None,
    ) -> AgentRuntime:
        store = self._session_store(workspace)
        current_record = store.load(current_session_id)
        target_record = store.load(target_session_id)
        self._emit(
            SESSION_BEFORE_SWITCH,
            session_id=current_session_id,
            subscribers=lifecycle_subscribers,
            details={"target_session_id": target_session_id, "target_head_id": target_head_id},
        )
        previous_head_id = target_record.active_head_id
        if target_head_id is not None:
            target_record = store.set_active_head(target_session_id, target_head_id)
        runtime = self._activate_runtime(workspace, target_record, lifecycle_subscribers=lifecycle_subscribers)
        self._emit(
            SESSION_SWITCHED,
            session_id=runtime.session_id,
            subscribers=lifecycle_subscribers,
            details={
                "from_session_id": current_record.id,
                "to_session_id": runtime.session_id,
                "from_head_id": current_record.active_head_id,
                "to_head_id": target_record.active_head_id,
            },
        )
        if current_session_id == target_session_id and previous_head_id != target_record.active_head_id:
            self._emit(
                SESSION_TREE_NAVIGATED,
                session_id=runtime.session_id,
                subscribers=lifecycle_subscribers,
                details={"from_head_id": previous_head_id, "to_head_id": target_record.active_head_id},
            )
        return runtime

    def fork_session(
        self,
        workspace: Path,
        session_id: str,
        *,
        head_id: Optional[str] = None,
        lifecycle_subscribers: Optional[list[LifecycleSubscriber]] = None,
    ) -> ForkResult:
        store = self._session_store(workspace)
        manager = self._checkpoint_manager(workspace)
        if manager.is_git_repository():
            self.create_checkpoint(
                workspace,
                session_id=session_id,
                head_id=head_id,
                reason="fork_session",
                snapshot_type="head_snapshot",
                lifecycle_subscribers=lifecycle_subscribers,
            )
        self._emit(SESSION_BEFORE_FORK, session_id=session_id, subscribers=lifecycle_subscribers, details={"source_head_id": head_id})
        forked = store.fork_from_head(session_id, head_id) if head_id is not None else store.fork(session_id)
        store.save(forked)
        self._emit(
            SESSION_FORKED,
            session_id=forked.id,
            subscribers=lifecycle_subscribers,
            details={"source_session_id": session_id, "target_session_id": forked.id, "source_head_id": head_id, "active_head_id": forked.active_head_id},
        )
        return ForkResult(source_session_id=session_id, session_id=forked.id, source_head_id=head_id, active_head_id=forked.active_head_id)

    def navigate_tree(
        self,
        workspace: Path,
        session_id: str,
        target_head_id: str,
        *,
        lifecycle_subscribers: Optional[list[LifecycleSubscriber]] = None,
    ) -> NavigateResult:
        store = self._session_store(workspace)
        self._emit(SESSION_BEFORE_TREE, session_id=session_id, subscribers=lifecycle_subscribers, details={"view": "tree", "target_head_id": target_head_id})
        before = store.load(session_id).active_head_id
        record = store.set_active_head(session_id, target_head_id)
        self._emit(
            SESSION_TREE_NAVIGATED,
            session_id=session_id,
            subscribers=lifecycle_subscribers,
            details={"from_head_id": before, "to_head_id": record.active_head_id},
        )
        return NavigateResult(session_id=session_id, previous_head_id=before, active_head_id=record.active_head_id)

    def rewind_session(
        self,
        workspace: Path,
        session_id: str,
        *,
        turn_count: Optional[int] = None,
        message_count: Optional[int] = None,
        lifecycle_subscribers: Optional[list[LifecycleSubscriber]] = None,
    ) -> RewindResult:
        store = self._session_store(workspace)
        rewound = store.rewind(session_id, message_count) if message_count is not None else store.rewind_turns(session_id, turn_count or 0)
        store.save(rewound)
        self._emit(
            SESSION_REWOUND,
            session_id=rewound.id,
            subscribers=lifecycle_subscribers,
            details={"source_session_id": session_id, "target_session_id": rewound.id, "message_count": message_count, "turn_count": turn_count},
        )
        return RewindResult(source_session_id=session_id, session_id=rewound.id, message_count=message_count, turn_count=turn_count)

    def list_sessions(self, workspace: Path) -> list[SessionTreeEntry]:
        return self._session_store(workspace).tree()

    def get_tree(
        self,
        workspace: Path,
        session_id: Optional[str] = None,
        *,
        sort_mode: str = "branch",
        lifecycle_subscribers: Optional[list[LifecycleSubscriber]] = None,
    ) -> SessionTreeView:
        store = self._session_store(workspace)
        entries = store.tree()
        if sort_mode == "updated":
            entries = sorted(entries, key=lambda item: item.updated_at, reverse=True)
        target_session_id = session_id or (entries[0].id if entries else None)
        self._emit(SESSION_BEFORE_TREE, session_id=target_session_id or "", subscribers=lifecycle_subscribers, details={"view": "tree", "sort_mode": sort_mode})
        description = store.describe(target_session_id) if target_session_id else {"current": None, "parent": None, "children": [], "turns": [], "turn_focus": None}
        self._emit(SESSION_TREE_VIEWED, session_id=target_session_id or "", subscribers=lifecycle_subscribers, details={"view": "tree", "sort_mode": sort_mode})
        return SessionTreeView(
            current=description.get("current"),
            parent=description.get("parent"),
            children=list(description.get("children") or []),
            turns=list(description.get("turns") or []),
            turn_focus=description.get("turn_focus"),
            entries=entries,
            sort_mode=sort_mode,
            session_id=target_session_id,
        )

    def approvals_summary(self, workspace: Path) -> dict:
        items = self._pending_action_store_factory(workspace).list()
        by_type: dict[str, int] = {}
        for item in items:
            action_type = item["action_type"]
            by_type[action_type] = by_type.get(action_type, 0) + 1
        return {"count": len(items), "by_type": by_type, "tokens": [item["token"] for item in items], "items": items}

    def create_checkpoint(
        self,
        workspace: Path,
        *,
        session_id: str,
        head_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        reason: str = "manual",
        snapshot_type: str = "head_snapshot",
        lifecycle_subscribers: Optional[list[LifecycleSubscriber]] = None,
    ) -> CheckpointEntry:
        manager = self._checkpoint_manager(workspace)
        if head_id is None and turn_id is None:
            head_id, turn_id = manager.current_head_context(session_id)
        self._emit(
            CHECKPOINT_BEFORE_CREATE,
            session_id=session_id,
            subscribers=lifecycle_subscribers,
            details={
                "checkpoint_id": None,
                "snapshot_type": snapshot_type,
                "session_id": session_id,
                "head_id": head_id,
                "turn_id": turn_id,
                "reason": reason,
                "has_dirty_workspace": False,
                "affected_file_count": 0,
            },
        )
        entry = manager.create_checkpoint(
            session_id=session_id,
            head_id=head_id,
            turn_id=turn_id,
            reason=reason,
            snapshot_type=snapshot_type,
        )
        self._emit(CHECKPOINT_CREATED, session_id=session_id, subscribers=lifecycle_subscribers, details=self._checkpoint_details(entry))
        return entry

    def list_checkpoints(self, workspace: Path, *, session_id: Optional[str] = None) -> list[CheckpointEntry]:
        return self._checkpoint_manager(workspace).list_checkpoints(session_id=session_id)

    def preview_rewind(
        self,
        workspace: Path,
        session_id: str,
        *,
        checkpoint_id: Optional[str] = None,
        turn_count: Optional[int] = None,
        message_count: Optional[int] = None,
        mode: str = "conversation_and_workspace",
        allow_stash_snapshot: bool = False,
        lifecycle_subscribers: Optional[list[LifecycleSubscriber]] = None,
    ) -> SafeRewindPreview:
        preview = self._safe_rewind(workspace).preview_rewind(
            session_id=session_id,
            checkpoint_id=checkpoint_id,
            turn_count=turn_count,
            message_count=message_count,
            mode=mode,
            allow_stash_snapshot=allow_stash_snapshot,
        )
        details = {
            "checkpoint_id": preview.checkpoint.checkpoint_id if preview.checkpoint else None,
            "snapshot_type": preview.checkpoint.snapshot_type if preview.checkpoint else None,
            "session_id": session_id,
            "head_id": preview.target_head_id,
            "turn_id": preview.target_turn_id,
            "reason": preview.checkpoint.reason if preview.checkpoint else "rewind_preview",
            "mode": mode,
            "has_dirty_workspace": bool(preview.restore_preview and preview.restore_preview.has_dirty_workspace),
            "affected_file_count": len(preview.restore_preview.affected_files) if preview.restore_preview else 0,
        }
        self._emit(CHECKPOINT_RESTORE_PREVIEW, session_id=session_id, subscribers=lifecycle_subscribers, details=details)
        return preview

    def rewind_safe(
        self,
        workspace: Path,
        session_id: str,
        *,
        checkpoint_id: Optional[str] = None,
        turn_count: Optional[int] = None,
        message_count: Optional[int] = None,
        mode: str = "conversation_and_workspace",
        allow_stash_snapshot: bool = False,
        lifecycle_subscribers: Optional[list[LifecycleSubscriber]] = None,
    ) -> SafeRewindResult:
        preview = self.preview_rewind(
            workspace,
            session_id,
            checkpoint_id=checkpoint_id,
            turn_count=turn_count,
            message_count=message_count,
            mode=mode,
            allow_stash_snapshot=allow_stash_snapshot,
            lifecycle_subscribers=lifecycle_subscribers,
        )
        self._emit(
            SESSION_SAFE_REWIND_STARTED,
            session_id=session_id,
            subscribers=lifecycle_subscribers,
            details={
                "checkpoint_id": preview.checkpoint.checkpoint_id if preview.checkpoint else None,
                "snapshot_type": preview.checkpoint.snapshot_type if preview.checkpoint else None,
                "session_id": session_id,
                "head_id": preview.target_head_id,
                "turn_id": preview.target_turn_id,
                "reason": preview.checkpoint.reason if preview.checkpoint else "rewind_safe",
                "mode": mode,
                "has_dirty_workspace": bool(preview.restore_preview and preview.restore_preview.has_dirty_workspace),
                "affected_file_count": len(preview.restore_preview.affected_files) if preview.restore_preview else 0,
            },
        )
        if preview.checkpoint is not None and mode in {"workspace_only", "conversation_and_workspace"}:
            self._emit(
                CHECKPOINT_BEFORE_RESTORE,
                session_id=session_id,
                subscribers=lifecycle_subscribers,
                details={**self._checkpoint_details(preview.checkpoint), "mode": mode},
            )
        try:
            result = self._safe_rewind(workspace).rewind_safe(
                session_id=session_id,
                checkpoint_id=checkpoint_id,
                turn_count=turn_count,
                message_count=message_count,
                mode=mode,
                allow_stash_snapshot=allow_stash_snapshot,
                rewind_callback=lambda **kwargs: self.rewind_session(
                    workspace,
                    kwargs["session_id"],
                    turn_count=kwargs.get("turn_count"),
                    message_count=kwargs.get("message_count"),
                ),
            )
        except Exception as exc:
            if preview.checkpoint is not None:
                self._emit(
                    CHECKPOINT_RESTORE_FAILED,
                    session_id=session_id,
                    subscribers=lifecycle_subscribers,
                    details={**self._checkpoint_details(preview.checkpoint), "mode": mode, "error": str(exc)},
                )
            raise
        if preview.checkpoint is not None and result.restored_workspace:
            self._emit(
                CHECKPOINT_RESTORED,
                session_id=result.session_id or session_id,
                subscribers=lifecycle_subscribers,
                details={**self._checkpoint_details(preview.checkpoint), "mode": mode},
            )
        self._emit(
            SESSION_SAFE_REWIND_COMPLETED,
            session_id=result.session_id or session_id,
            subscribers=lifecycle_subscribers,
            details={
                "checkpoint_id": result.checkpoint_id,
                "snapshot_type": result.snapshot_type,
                "session_id": result.session_id or session_id,
                "head_id": preview.target_head_id,
                "turn_id": preview.target_turn_id,
                "reason": preview.checkpoint.reason if preview.checkpoint else "rewind_safe",
                "mode": mode,
                "has_dirty_workspace": bool(preview.restore_preview and preview.restore_preview.has_dirty_workspace),
                "affected_file_count": len(preview.restore_preview.affected_files) if preview.restore_preview else 0,
            },
        )
        return result

    def _activate_runtime(
        self,
        workspace: Path,
        record: SessionRecord,
        *,
        lifecycle_subscribers: Optional[list[LifecycleSubscriber]],
        event_type: Optional[str] = None,
        event_details: Optional[dict[str, object]] = None,
    ) -> AgentRuntime:
        runtime = self._runtime_factory(workspace, record, lifecycle_subscribers)
        runtime.restore_session_record(record, emit_event=False)
        if event_type is not None:
            runtime._queue_lifecycle_event(runtime._event(event_type, details=event_details or {}))
        return runtime

    def _emit(
        self,
        event_type: str,
        *,
        session_id: str,
        subscribers: Optional[list[LifecycleSubscriber]],
        details: Optional[dict[str, object]] = None,
    ) -> AgentEvent:
        event = AgentEvent(type=event_type, session_id=session_id, details=details or {})
        for subscriber in subscribers or []:
            subscriber(event)
        return event

    def _session_store(self, workspace: Path) -> SessionStore:
        return self._session_store_factory(workspace)

    def _checkpoint_store(self, workspace: Path) -> CheckpointStore:
        return self._checkpoint_store_factory(workspace)

    def _checkpoint_manager(self, workspace: Path) -> GitCheckpointManager:
        return GitCheckpointManager(workspace, self._checkpoint_store(workspace), self._session_store(workspace))

    def _safe_rewind(self, workspace: Path) -> SafeRewindOrchestrator:
        return SafeRewindOrchestrator(self._session_store(workspace), self._checkpoint_manager(workspace))

    @staticmethod
    def _checkpoint_details(entry: CheckpointEntry) -> dict[str, object]:
        return {
            "checkpoint_id": entry.checkpoint_id,
            "snapshot_type": entry.snapshot_type,
            "session_id": entry.session_id,
            "head_id": entry.head_id,
            "turn_id": entry.turn_id,
            "reason": entry.reason,
            "has_dirty_workspace": entry.file_stats.has_dirty_workspace,
            "affected_file_count": entry.file_stats.changed_file_count,
        }
