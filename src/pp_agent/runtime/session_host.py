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
from pp_agent.storage.approvals import PendingActionStore, is_active_pending_action, pending_action_state
from pp_agent.storage.checkpoints import CheckpointStore
from pp_agent.storage.sessions import SessionRecord, SessionStore, SessionTreeEntry

LifecycleSubscriber = Callable[[AgentEvent], None]
RuntimeFactory = Callable[[Path, SessionRecord, Optional[list[LifecycleSubscriber]]], AgentRuntime]
SessionStoreFactory = Callable[[Path], SessionStore]
PendingActionStoreFactory = Callable[[Path], PendingActionStore]
SessionDefaultsFactory = Callable[[Path], dict[str, Any]]
CheckpointStoreFactory = Callable[[Path], CheckpointStore]


class SwitchResult(BaseModel):
    """完整记录切换前后的会话和节点状态，支撑对话的版本回退、分支管理功能"""
    session_id: str
    previous_session_id: str
    active_head_id: Optional[str] = None
    previous_head_id: Optional[str] = None
    target_head_id: Optional[str] = None


class ForkResult(BaseModel):
    """记录分叉操作的来源和结果状态，支撑对话的版本回退、分支管理功能"""
    source_session_id: str
    session_id: str
    source_head_id: Optional[str] = None
    active_head_id: Optional[str] = None


class NavigateResult(BaseModel):
    """
    导航操作的返回结果模型
    用于统一接口/函数返回的导航数据格式
    """
    session_id: str
    previous_head_id: Optional[str] = None
    active_head_id: Optional[str] = None


class RewindResult(BaseModel):
    """记录回退操作的来源和结果状态，支撑对话的版本回退、分支管理功能"""
    source_session_id: str
    session_id: str
    message_count: Optional[int] = None
    turn_count: Optional[int] = None


class SessionTreeView(BaseModel):
    """ 会话树视图模型，包含当前节点、父节点、子节点、对话轮次等信息，用于支持会话树的展示和交互功能 """
    current: Optional[dict[str, object]] = None
    parent: Optional[dict[str, object]] = None
    children: list[dict[str, object]] = Field(default_factory=list)
    turns: list[dict[str, object]] = Field(default_factory=list)
    turn_focus: Optional[dict[str, object]] = None
    entries: list[SessionTreeEntry] = Field(default_factory=list)
    sort_mode: str = "branch"
    view_mode: str = "default"
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
        """创建一个新的会话，并激活对应的 AgentRuntime 实例"""
        # 1. 通过【会话默认配置工厂】获取当前工作区的默认配置（系统提示词、模型名称）
        defaults = self._session_defaults_factory(workspace)
        # 2. 通过【会话存储工厂】创建会话存储实例，并通过【会话存储】创建会话记录
        store = self._session_store(workspace)
        record = store.create(defaults["system_prompt"], defaults["model"])
        store.save(record)
        # 3. 激活会话对应的 AgentRuntime 实例，并通过生命周期事件通知订阅者
        return self._activate_runtime(
            workspace,
            record,
            lifecycle_subscribers=lifecycle_subscribers,
            event_type=SESSION_START,
            event_details={"new_session": True},
        )

    def restore_session(self, workspace: Path, session_id: str, *, lifecycle_subscribers: Optional[list[LifecycleSubscriber]] = None) -> AgentRuntime:
        """恢复一个已存在的会话，并激活对应的 AgentRuntime 实例"""
        #1. 通过【会话存储工厂】创建会话存储实例，并通过【会话存储】加载会话记录
        record = self._session_store(workspace).load(session_id)
        #2. 激活会话对应的 AgentRuntime 实例，并通过生命周期事件通知订阅者
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
        """切换到另一个会话，支持指定目标会话的特定节点（head）进行切换，并激活对应的 AgentRuntime 实例"""
        #1. 通过【会话存储工厂】创建会话存储实例，并通过【会话存储】加载当前会话和目标会话的记录
        store = self._session_store(workspace)
        current_record = store.load(current_session_id)
        target_record = store.load(target_session_id)
        #2. 通过生命周期事件通知订阅者即将进行会话切换的操作
        self._emit(
            SESSION_BEFORE_SWITCH,
            session_id=current_session_id,
            subscribers=lifecycle_subscribers,
            details={"target_session_id": target_session_id, "target_head_id": target_head_id},
        )
        #3. 如果指定了目标节点（head），则将目标会话切换到该节点
        previous_head_id = target_record.active_head_id
        if target_head_id is not None:
            target_record = store.set_active_head(target_session_id, target_head_id)
        #4. 激活目标会话对应的 AgentRuntime 实例，并通过生命周期事件通知订阅者完成会话切换的操作
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
        #5. 如果当前会话和目标会话相同，且目标节点（head）发生变化，则通过生命周期事件通知订阅者完成节点切换的操作
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
        """分叉当前会话，创建一个新的会话记录，新的会话记录以当前会话的指定节点（head）为基础进行分叉，并返回分叉结果"""
        store = self._session_store(workspace)
        manager = self._checkpoint_manager(workspace)
        
        if manager.is_git_repository():
            # 在分叉会话之前，先创建一个 checkpoint 以保存当前节点的状态，确保分叉操作有据可依
            self.create_checkpoint(
                workspace,
                session_id=session_id,
                head_id=head_id,
                reason="fork_session",
                snapshot_type="head_snapshot",
                lifecycle_subscribers=lifecycle_subscribers,
            )
        #发射生命周期事件
        self._emit(SESSION_BEFORE_FORK, session_id=session_id, subscribers=lifecycle_subscribers, details={"source_head_id": head_id})
        #分叉当前会话记录，新的会话记录以当前会话的指定节点（head）为基础进行分叉
        forked = store.fork_from_head(session_id, head_id) if head_id is not None else store.fork(session_id)
        store.save(forked)
        #发送生命周期事件
        self._emit(
            SESSION_FORKED,
            session_id=forked.id,
            subscribers=lifecycle_subscribers,
            details={"source_session_id": session_id, "target_session_id": forked.id, "source_head_id": head_id, "active_head_id": forked.active_head_id},
        )
        #返回分叉结果
        return ForkResult(source_session_id=session_id, session_id=forked.id, source_head_id=head_id, active_head_id=forked.active_head_id)

    def navigate_tree(
        self,
        workspace: Path,
        session_id: str,
        target_head_id: str,
        *,
        lifecycle_subscribers: Optional[list[LifecycleSubscriber]] = None,
    ) -> NavigateResult:
        """在当前会话中导航到另一个节点（head），并返回导航结果"""
        store = self._session_store(workspace)
        self._emit(SESSION_BEFORE_TREE, session_id=session_id, subscribers=lifecycle_subscribers, details={"view": "tree", "target_head_id": target_head_id})
        #获取当前活跃节点
        before = store.load(session_id).active_head_id
        #设置新的活跃节点
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
        """回退当前会话到指定的消息数量或对话轮次，并返回回退结果"""
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
        view_mode: str = "default",
        lifecycle_subscribers: Optional[list[LifecycleSubscriber]] = None,
    ) -> SessionTreeView:
        """获取当前会话树的视图数据，支持指定排序方式，并通过生命周期事件通知订阅者"""
        store = self._session_store(workspace)
        entries = store.tree()
        #按更新时间排序会话树节点，默认按照分支结构排序
        if sort_mode == "updated":
            entries = sorted(entries, key=lambda item: item.updated_at, reverse=True)
        target_session_id = session_id or (entries[0].id if entries else None)
        self._emit(
            SESSION_BEFORE_TREE,
            session_id=target_session_id or "",
            subscribers=lifecycle_subscribers,
            details={"view": "tree", "sort_mode": sort_mode, "view_mode": view_mode},
        )
        description = store.describe(target_session_id) if target_session_id else {"current": None, "parent": None, "children": [], "turns": [], "turn_focus": None}
        self._emit(
            SESSION_TREE_VIEWED,
            session_id=target_session_id or "",
            subscribers=lifecycle_subscribers,
            details={"view": "tree", "sort_mode": sort_mode, "view_mode": view_mode},
        )
        
        
        return SessionTreeView(
            current=description.get("current"),
            parent=description.get("parent"),
            children=list(description.get("children") or []),
            turns=list(description.get("turns") or []),
            turn_focus=description.get("turn_focus"),
            entries=entries,
            sort_mode=sort_mode,
            view_mode=view_mode,
            session_id=target_session_id,
        )

    def approvals_summary(self, workspace: Path) -> dict:
        """获取当前会话的待审批操作的汇总信息，包括待审批操作的数量、类型分布、涉及的消息等，用于支持审批功能的展示和交互"""
        items = self._pending_action_store_factory(workspace).list()
        by_type: dict[str, int] = {}
        active_items = [item for item in items if is_active_pending_action(item)]
        archived_items = [item for item in items if not is_active_pending_action(item)]
        for item in items:
            action_type = item["action_type"]
            by_type[action_type] = by_type.get(action_type, 0) + 1
        state_counts: dict[str, int] = {}
        for item in items:
            state = pending_action_state(item)
            state_counts[state] = state_counts.get(state, 0) + 1
        return {
            "count": len(items),
            "active_count": len(active_items),
            "archived_count": len(archived_items),
            "by_type": by_type,
            "tokens": [item["token"] for item in active_items],
            "items": items,
            "active_items": active_items,
            "archived_items": archived_items,
            "state_counts": state_counts,
        }

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
        """创建一个新的 checkpoint 以保存当前节点的状态，并返回 checkpoint 记录"""
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
        """
        预览回退当前会话到指定的消息数量或对话轮次可能带来的影响，
        包括可能被回退的消息、涉及的对话轮次、可能被回退的工作区文件等，并返回预览结果
        """
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
        """【核心方法】执行安全回滚，预览回滚可能带来的影响，并根据预览结果执行回滚操作，最后返回回滚结果"""
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
        """激活会话对应的 AgentRuntime 实例，并通过生命周期事件通知订阅者"""
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
