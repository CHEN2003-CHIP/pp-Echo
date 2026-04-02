from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from pp_agent.runtime.lifecycle import (
    SESSION_BEFORE_FORK,
    SESSION_BEFORE_SWITCH,
    SESSION_BEFORE_TREE,
    SESSION_FORKED,
    SESSION_RESTORE,
    SESSION_REWOUND,
    SESSION_START,
    SESSION_SWITCHED,
    SESSION_TREE_NAVIGATED,
    SESSION_TREE_VIEWED,
)
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.runtime.state import AgentEvent
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.storage.sessions import SessionRecord, SessionStore, SessionTreeEntry

LifecycleSubscriber = Callable[[AgentEvent], None]
RuntimeFactory = Callable[[Path, SessionRecord, Optional[list[LifecycleSubscriber]]], AgentRuntime]
SessionStoreFactory = Callable[[Path], SessionStore]
PendingActionStoreFactory = Callable[[Path], PendingActionStore]
SessionDefaultsFactory = Callable[[Path], dict[str, Any]]


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
    ) -> None:
        self._runtime_factory = runtime_factory
        self._session_store_factory = session_store_factory
        self._pending_action_store_factory = pending_action_store_factory
        self._session_defaults_factory = session_defaults_factory

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
