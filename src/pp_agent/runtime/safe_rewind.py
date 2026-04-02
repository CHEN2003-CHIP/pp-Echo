from __future__ import annotations

from typing import Optional

from pp_agent.domain.checkpoints import CheckpointEntry, SafeRewindPreview, SafeRewindResult
from pp_agent.runtime.git_checkpoint import GitCheckpointManager
from pp_agent.storage.sessions import SessionStore


SafeRewindMode = str


class SafeRewindOrchestrator:
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
