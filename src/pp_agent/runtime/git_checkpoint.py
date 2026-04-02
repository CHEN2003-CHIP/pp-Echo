from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from pp_agent.domain.checkpoints import CheckpointEntry, CheckpointFileStats, CheckpointRestorePreview
from pp_agent.storage.checkpoints import CheckpointStore
from pp_agent.storage.sessions import SessionRecord, SessionStore


class GitCheckpointManager:
    def __init__(self, workspace: Path, checkpoint_store: CheckpointStore, session_store: SessionStore) -> None:
        self.workspace = workspace.resolve()
        self.checkpoint_store = checkpoint_store
        self.session_store = session_store

    def create_checkpoint(
        self,
        *,
        session_id: str,
        head_id: Optional[str],
        turn_id: Optional[str],
        reason: str,
        snapshot_type: str = "head_snapshot",
        summary: str = "",
        test_summary: Optional[str] = None,
    ) -> CheckpointEntry:
        if not self.is_git_repository():
            raise RuntimeError("Checkpointing requires a git repository workspace")
        if snapshot_type == "stash_snapshot":
            return self.create_stash_snapshot(
                session_id=session_id,
                head_id=head_id,
                turn_id=turn_id,
                reason=reason,
                summary=summary,
                test_summary=test_summary,
            )
        return self.create_head_snapshot(
            session_id=session_id,
            head_id=head_id,
            turn_id=turn_id,
            reason=reason,
            summary=summary,
            test_summary=test_summary,
        )

    def create_head_snapshot(
        self,
        *,
        session_id: str,
        head_id: Optional[str],
        turn_id: Optional[str],
        reason: str,
        summary: str = "",
        test_summary: Optional[str] = None,
    ) -> CheckpointEntry:
        entry = CheckpointEntry(
            workspace_root=str(self.workspace),
            session_id=session_id,
            head_id=head_id,
            turn_id=turn_id,
            reason=reason,
            snapshot_type="head_snapshot",
            summary=summary or f"HEAD snapshot before {reason}",
            file_stats=self._file_stats(),
            head_commit=self._git(["rev-parse", "HEAD"]).strip(),
            branch_name=self._current_branch(),
            test_summary=test_summary,
        )
        return self.checkpoint_store.create(entry)

    def create_stash_snapshot(
        self,
        *,
        session_id: str,
        head_id: Optional[str],
        turn_id: Optional[str],
        reason: str,
        summary: str = "",
        test_summary: Optional[str] = None,
    ) -> CheckpointEntry:
        message = f"pp-agent:{session_id}:{head_id or 'none'}:{turn_id or 'none'}:{reason}"
        before = self._stash_list()
        self._git(["stash", "push", "--include-untracked", "-m", message])
        after = self._stash_list()
        stash_ref = next((item.split(":", 1)[0] for item in after if item not in before and message in item), None)
        entry = CheckpointEntry(
            workspace_root=str(self.workspace),
            session_id=session_id,
            head_id=head_id,
            turn_id=turn_id,
            reason=reason,
            snapshot_type="stash_snapshot",
            summary=summary or f"Stash snapshot for {reason}",
            file_stats=self._file_stats(),
            head_commit=self._git(["rev-parse", "HEAD"]).strip(),
            branch_name=self._current_branch(),
            stash_ref=stash_ref,
            stash_message=message,
            test_summary=test_summary,
        )
        return self.checkpoint_store.create(entry)

    def list_checkpoints(self, *, session_id: Optional[str] = None) -> list[CheckpointEntry]:
        return self.checkpoint_store.list(workspace=self.workspace, session_id=session_id)

    def preview_restore(self, checkpoint_id: str) -> CheckpointRestorePreview:
        entry = self.checkpoint_store.load(checkpoint_id)
        status_output = self._git_status_output()
        stats = self._file_stats()
        warnings: list[str] = []
        if stats.has_dirty_workspace:
            warnings.append("Current workspace has tracked file changes that may be overwritten.")
        if stats.has_untracked_files:
            warnings.append("Current workspace has untracked files that are not restored by head snapshots.")
        if entry.snapshot_type == "stash_snapshot":
            warnings.append("This restore will use stash apply semantics for a protection snapshot.")
        affected_files = self._affected_files(entry)
        return CheckpointRestorePreview(
            checkpoint_id=entry.checkpoint_id,
            snapshot_type=entry.snapshot_type,
            session_id=entry.session_id,
            head_id=entry.head_id,
            turn_id=entry.turn_id,
            reason=entry.reason,
            summary=entry.summary,
            current_git_status=status_output,
            target_head_commit=entry.head_commit,
            target_branch=entry.branch_name,
            affected_files=affected_files,
            has_dirty_workspace=stats.has_dirty_workspace,
            has_untracked_files=stats.has_untracked_files,
            overwrite_risk=stats.has_dirty_workspace or stats.has_untracked_files,
            warning_messages=warnings,
        )

    def restore_checkpoint(self, checkpoint_id: str) -> CheckpointEntry:
        entry = self.checkpoint_store.load(checkpoint_id)
        try:
            if entry.snapshot_type == "stash_snapshot":
                self._restore_stash_snapshot(entry)
            else:
                self._restore_head_snapshot(entry)
        except FileNotFoundError:
            self.checkpoint_store.mark_missing(checkpoint_id)
            raise
        except Exception:
            self.checkpoint_store.mark_failed(checkpoint_id)
            raise
        return self.checkpoint_store.mark_restored(checkpoint_id)

    def drop_checkpoint(self, checkpoint_id: str) -> CheckpointEntry:
        entry = self.checkpoint_store.load(checkpoint_id)
        if entry.snapshot_type == "stash_snapshot" and entry.stash_ref:
            try:
                self._git(["stash", "drop", entry.stash_ref])
            except RuntimeError:
                self.checkpoint_store.mark_missing(checkpoint_id)
                raise FileNotFoundError(f"Checkpoint stash is missing: {entry.stash_ref}")
        return self.checkpoint_store.mark_dropped(checkpoint_id)

    def resolve_checkpoint_for_rewind(
        self,
        *,
        session_id: str,
        head_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        allow_stash_snapshot: bool = False,
    ) -> Optional[CheckpointEntry]:
        exact = self.checkpoint_store.find_for_session_head(session_id, head_id, turn_id=turn_id, snapshot_type="head_snapshot")
        if exact:
            return exact[0]
        head_matches = self.checkpoint_store.find_for_session_head(session_id, head_id, snapshot_type="head_snapshot")
        if head_matches:
            return head_matches[0]
        recent = self.list_checkpoints(session_id=session_id)
        head_recent = next((item for item in recent if item.snapshot_type == "head_snapshot"), None)
        if head_recent is not None:
            return head_recent
        if allow_stash_snapshot:
            return next((item for item in recent if item.snapshot_type == "stash_snapshot"), None)
        return None

    def current_head_context(self, session_id: str) -> tuple[Optional[str], Optional[str]]:
        record = self.session_store.load(session_id)
        return self._head_and_turn_for_record(record)

    def is_git_repository(self) -> bool:
        try:
            self._git(["rev-parse", "--show-toplevel"])
        except RuntimeError:
            return False
        return True

    def _restore_head_snapshot(self, entry: CheckpointEntry) -> None:
        target_files = set(self._git_lines(["ls-tree", "-r", "--name-only", entry.head_commit]))
        current_tracked = set(self._git_lines(["ls-files"]))
        self._git(["restore", f"--source={entry.head_commit}", "--worktree", "--", "."])
        for relative in sorted(current_tracked - target_files):
            path = self.workspace / relative
            if path.exists():
                path.unlink()

    def _restore_stash_snapshot(self, entry: CheckpointEntry) -> None:
        if not entry.stash_ref:
            raise FileNotFoundError(f"Checkpoint stash ref is missing for {entry.checkpoint_id}")
        stash_refs = {item.split(":", 1)[0] for item in self._stash_list()}
        if entry.stash_ref not in stash_refs:
            raise FileNotFoundError(f"Checkpoint stash ref does not exist: {entry.stash_ref}")
        self._git(["stash", "apply", entry.stash_ref])

    def _affected_files(self, entry: CheckpointEntry) -> list[str]:
        files = set(self._git_lines(["diff", "--name-only", entry.head_commit, "--"]))
        files.update(self._file_stats().files)
        if entry.snapshot_type == "stash_snapshot" and entry.file_stats.files:
            files.update(entry.file_stats.files)
        return sorted(files)

    def _file_stats(self) -> CheckpointFileStats:
        output = self._git(["status", "--porcelain=v1", "--untracked-files=all"])
        files: list[str] = []
        has_dirty_workspace = False
        has_untracked_files = False
        for raw_line in output.splitlines():
            line = raw_line.rstrip()
            if not line:
                continue
            path = line[3:] if len(line) > 3 else ""
            if path:
                files.append(path)
            code = line[:2]
            if code == "??":
                has_untracked_files = True
            else:
                has_dirty_workspace = True
        unique_files = sorted(dict.fromkeys(files))
        return CheckpointFileStats(
            changed_file_count=len(unique_files),
            has_dirty_workspace=has_dirty_workspace,
            has_untracked_files=has_untracked_files,
            files=unique_files,
        )

    def _git_status_output(self) -> str:
        return self._git(["status", "--short", "--branch"]).strip()

    def _current_branch(self) -> str:
        try:
            return self._git(["symbolic-ref", "--short", "HEAD"]).strip()
        except RuntimeError:
            return "(detached)"

    def _stash_list(self) -> list[str]:
        return [line for line in self._git(["stash", "list"]).splitlines() if line.strip()]

    def _head_and_turn_for_record(self, record: SessionRecord) -> tuple[Optional[str], Optional[str]]:
        head_id = record.active_head_id
        turn_id = None
        for node in reversed(self.session_store.turn_path(record, head_id)):
            if node.entry_type == "turn":
                turn_id = node.id
                break
        return head_id, turn_id

    def _git_lines(self, args: list[str]) -> list[str]:
        return [line.strip() for line in self._git(args).splitlines() if line.strip()]

    def _git(self, args: list[str]) -> str:
        completed = subprocess.run(["git", *args], cwd=str(self.workspace), capture_output=True, text=True, check=False)
        output = (completed.stdout or "") + (("\n" + completed.stderr) if completed.stderr else "")
        if completed.returncode != 0:
            raise RuntimeError(output.strip() or f"git {' '.join(args)} failed")
        return output
