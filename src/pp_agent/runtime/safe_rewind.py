from __future__ import annotations

from typing import Optional

from pp_agent.domain.checkpoints import CheckpointEntry, SafeRewindPreview, SafeRewindResult
from pp_agent.runtime.git_checkpoint import GitCheckpointManager
from pp_agent.storage.sessions import SessionStore


SafeRewindMode = str


class SafeRewindOrchestrator:
    """
    【核心服务】安全回滚编排器
    【业务定位】AI 对话 + 代码工作区 统一安全回滚中心
    【设计模式】编排模式 + 策略模式
    【核心能力】
        1. 支持三种回滚模式：仅对话 / 仅代码 / 全部回滚
        2. 回滚前自动风险预览（文件覆盖、脏工作区、未跟踪文件）
        3. 自动匹配最佳检查点，无需手动指定
        4. 原子化执行：先预览 → 再回滚 → 状态统一
    【安全保障】所有危险操作必须预览，支持脏工作区检测
    """
    def __init__(self, session_store: SessionStore, checkpoint_manager: GitCheckpointManager) -> None:
        self.session_store = session_store
        self.checkpoint_manager = checkpoint_manager

    def preview_rewind(
        self,
        *,
        session_id: str,
        mode: SafeRewindMode,
        checkpoint_id: Optional[str] = None,
        message_count: Optional[int] = None,
        turn_count: Optional[int] = None,
        allow_stash_snapshot: bool = False,
    ) -> SafeRewindPreview:
        """
        【公共方法】回滚预览（执行前必须调用）
        【业务功能】
            1. 自动寻找最佳检查点
            2. 生成风险警告
            3. 返回目标节点信息（head/turn）
            4. 根据模式过滤无关警告
        :param session_id: 会话ID
        :param mode: 回滚模式
        :param checkpoint_id: 手动指定检查点（可选）
        :param message_count: 按消息数回滚（可选）
        :param turn_count: 按回合数回滚（可选）
        :param allow_stash_snapshot: 是否允许使用保护快照
        :return: 完整回滚预览信息
        """

        # 自动解析最佳检查点
        checkpoint = self._resolve_checkpoint(
            session_id=session_id,
            checkpoint_id=checkpoint_id,
            message_count=message_count,
            turn_count=turn_count,
            allow_stash_snapshot=allow_stash_snapshot,
        )
        restore_preview = None
        warnings: list[str] = []
        target_head_id = None
        target_turn_id = None
        if checkpoint is not None:
            restore_preview = self.checkpoint_manager.preview_restore(checkpoint.checkpoint_id)
            warnings.extend(restore_preview.warning_messages)
            target_head_id = checkpoint.head_id
            target_turn_id = checkpoint.turn_id
        if mode == "conversation_only":
            warnings = [item for item in warnings if "workspace" not in item.lower()]
        return SafeRewindPreview(
            mode=mode,
            checkpoint=checkpoint,
            restore_preview=restore_preview,
            source_session_id=session_id,
            target_head_id=target_head_id,
            target_turn_id=target_turn_id,
            message_count=message_count,
            turn_count=turn_count,
            warning_messages=warnings,
        )

    def rewind_safe(
        self,
        *,
        session_id: str,
        mode: SafeRewindMode,
        rewind_callback,
        checkpoint_id: Optional[str] = None,
        message_count: Optional[int] = None,
        turn_count: Optional[int] = None,
        allow_stash_snapshot: bool = False,
    ) -> SafeRewindResult:
        """
        【核心方法】执行安全回滚
        【执行流程】预览 → 恢复工作区 → 回滚对话 → 返回结果
        【模式策略】
            - conversation_only: 仅执行回调回滚对话
            - workspace_only: 仅恢复Git检查点
            - conversation_and_workspace: 全部执行
        :param session_id: 会话ID
        :param mode: 回滚模式
        :param rewind_callback: 对话回滚回调（外部实现）
        :param checkpoint_id: 指定检查点（可选）
        :param message_count: 按消息数回滚
        :param turn_count: 按回合数回滚
        :param allow_stash_snapshot: 是否允许保护快照
        :return: 回滚执行结果
        """
        preview = self.preview_rewind(
            session_id=session_id,
            mode=mode,
            checkpoint_id=checkpoint_id,
            message_count=message_count,
            turn_count=turn_count,
            allow_stash_snapshot=allow_stash_snapshot,
        )
        checkpoint = preview.checkpoint
        rewound = None
        restored_workspace = False
        restored_conversation = False
        if mode in {"workspace_only", "conversation_and_workspace"} and checkpoint is not None:
            self.checkpoint_manager.restore_checkpoint(checkpoint.checkpoint_id)
            restored_workspace = True
        if mode in {"conversation_only", "conversation_and_workspace"}:
            rewound = rewind_callback(session_id=session_id, turn_count=turn_count, message_count=message_count)
            restored_conversation = True
        return SafeRewindResult(
            mode=mode,
            checkpoint_id=checkpoint.checkpoint_id if checkpoint is not None else None,
            snapshot_type=checkpoint.snapshot_type if checkpoint is not None else None,
            source_session_id=session_id,
            session_id=rewound.session_id if rewound is not None else session_id,
            active_head_id=checkpoint.head_id if checkpoint is not None else None,
            restored_workspace=restored_workspace,
            restored_conversation=restored_conversation,
            warning_messages=preview.warning_messages,
        )

    def _resolve_checkpoint(
        self,
        *,
        session_id: str,
        checkpoint_id: Optional[str],
        message_count: Optional[int],
        turn_count: Optional[int],
        allow_stash_snapshot: bool,
    ) -> Optional[CheckpointEntry]:
        
        if checkpoint_id is not None:
            return self.checkpoint_manager.checkpoint_store.load(checkpoint_id)
        if message_count is not None or turn_count is not None:
            target_head_id, target_turn_id = self._resolve_target_head_for_rewind(session_id, message_count=message_count, turn_count=turn_count)
            return self.checkpoint_manager.resolve_checkpoint_for_rewind(
                session_id=session_id,
                head_id=target_head_id,
                turn_id=target_turn_id,
                allow_stash_snapshot=allow_stash_snapshot,
            )
        return self.checkpoint_manager.resolve_checkpoint_for_rewind(session_id=session_id, allow_stash_snapshot=allow_stash_snapshot)

    def _resolve_target_head_for_rewind(
        self,
        session_id: str,
        *,
        message_count: Optional[int],
        turn_count: Optional[int],
    ) -> tuple[Optional[str], Optional[str]]:
        """
        【私有方法】根据消息数/回合数计算目标回滚节点
        【业务功能】将“回滚N条消息/回合”转换为可匹配的head/turn节点
        :return: (target_head_id, target_turn_id)
        """
        record = self.session_store.load(session_id)
        branch_messages = self.session_store.branch_messages(record, record.active_head_id)
        if message_count is not None:
            if message_count < 0 or message_count > len(branch_messages):
                raise ValueError(f"message_count must be between 0 and {len(branch_messages)}")
            if message_count == 0:
                return None, None
            total = 0
            for entry in self.session_store.turn_entries(session_id, head_id=record.active_head_id):
                if entry.entry_type != "turn":
                    continue
                total = entry.total_message_count
                if total >= message_count:
                    return entry.id, entry.id
            return record.active_head_id, record.active_head_id
        if turn_count is not None:
            entries = [entry for entry in self.session_store.turn_entries(session_id, head_id=record.active_head_id) if entry.entry_type == "turn"]
            if turn_count < 0 or turn_count > len(entries):
                raise ValueError(f"turn_count must be between 0 and {len(entries)}")
            if turn_count == 0:
                return None, None
            selected = entries[turn_count - 1]
            return selected.id, selected.id
        return record.active_head_id, record.active_head_id
