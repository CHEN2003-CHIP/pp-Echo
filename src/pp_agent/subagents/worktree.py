from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class PatchArtifact(BaseModel):
    artifact_id: str
    run_id: str
    agent: str
    node_id: str
    attempt: int
    worktree_path: str
    patch_path: str
    source_head: str
    baseline_commit: str
    dirty_context_digest: str
    changed_paths: list[str] = Field(default_factory=list)
    created_at: float
    status: str = "staged"


class WorktreeHandle(BaseModel):
    run_id: str
    agent: str
    node_id: str
    attempt: int
    parent_workspace: str
    worktree_path: str
    source_head: str
    baseline_commit: str
    dirty_context_digest: str


class WorktreeUnavailable(RuntimeError):
    pass

"""
is_available 检查是否在 Git 仓库内：

    git rev-parse --is-inside-work-tree

create 方法中：

    git rev-parse HEAD → 获取当前 HEAD 提交 hash

    git worktree add --detach <path> <commit> → 创建分离 HEAD 的 worktree

复制 dirty context 时：

    git diff --binary HEAD -- → 获取工作区相对于 HEAD 的二进制 diff（用于复制未提交的变更）

    git apply --binary --whitespace=nowarn - （在 worktree 目录）→ 应用上述 diff 到 worktree

    git ls-files --others --exclude-standard -z → 列出未跟踪文件（以 null 分隔）

创建 baseline 提交时（在 worktree 目录）：

    git add -A → 暂存所有变更

    git commit --allow-empty -m "..."（带 -c user.name 等）→ 提交 baseline

    git rev-parse HEAD → 获取 baseline commit hash

finalize 方法中（在 worktree 目录）：

    git add -N -- . → 为所有文件添加 “intent to add”，使新文件出现在 diff 中

    git diff --binary <baseline_commit> -- → 获取从 baseline 开始的二进制 diff

    git diff --name-only <baseline_commit> -- → 获取变更文件列表

apply_check 方法中（在主仓库）：

    git apply --check <patch_path> → 检查补丁是否能干净应用

apply 方法中（在主仓库）：

    git apply <patch_path> → 尝试应用补丁

如果失败，回退到 git apply --3way <patch_path> → 三路合并应用

"""
class WorktreeManager:
    """Create isolated local git worktrees and convert their diff into patch artifacts."""

    def __init__(self, workspace: Path) -> None:
        """Initialize a worktree manager with a workspace directory."""
        self.workspace = workspace.resolve()
        self.root = self.workspace / ".pp-agent" / "worktrees"
        self.artifact_root = self.workspace / ".pp-agent" / "patch-artifacts"

    def is_available(self) -> bool:
        result = self._git(["rev-parse", "--is-inside-work-tree"], check=False)
        return result.returncode == 0 and (result.stdout or "").strip().lower() == "true"

    def create(self, *, run_id: str, agent: str, node_id: str, attempt: int = 1) -> WorktreeHandle:
        if not self.is_available():
            raise WorktreeUnavailable("workspace is not a git repository; isolated worktree mode is unavailable.")
        source_head = self._git_stdout(["rev-parse", "HEAD"])
        worktree_path = (self.root / run_id / agent / node_id / f"attempt-{attempt}").resolve()
        if worktree_path.exists():
            shutil.rmtree(worktree_path)
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        self._git(["worktree", "add", "--detach", str(worktree_path), source_head])
        dirty_digest = self._copy_dirty_context(worktree_path)
        baseline_commit = self._baseline_commit(worktree_path)
        return WorktreeHandle(
            run_id=run_id,
            agent=agent,
            node_id=node_id,
            attempt=attempt,
            parent_workspace=str(self.workspace),
            worktree_path=str(worktree_path),
            source_head=source_head,
            baseline_commit=baseline_commit,
            dirty_context_digest=dirty_digest,
        )

    def finalize(self, handle: WorktreeHandle) -> PatchArtifact | None:
        #提取出子代理所做的所有变更，生成一个标准的 Git 补丁文件，并附带元数据
        """
        git add -N -- . 为所有文件添加“ intent-to-add”标记，确保 git diff 能捕获新文件。

        执行 git diff --binary <baseline_commit> -- 获取变更的二进制 diff。

        执行 git diff --name-only <baseline_commit> -- 获取变更文件列表。
        """
        worktree_path = Path(handle.worktree_path)
        self._git(["add", "-N", "--", "."], cwd=worktree_path, check=False)
        diff = self._git_output(["diff", "--binary", handle.baseline_commit, "--"], cwd=worktree_path)
        changed_paths = [
            line.strip()
            for line in self._git_stdout(["diff", "--name-only", handle.baseline_commit, "--"], cwd=worktree_path).splitlines()
            if line.strip()
        ]
        if not diff.strip() and not changed_paths:
            return None
        artifact_id = uuid.uuid4().hex
        artifact_dir = self.artifact_root / handle.run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        patch_path = artifact_dir / f"{artifact_id}.patch"
        meta_path = artifact_dir / f"{artifact_id}.json"
        patch_path.write_text(diff, encoding="utf-8")
        artifact = PatchArtifact(
            artifact_id=artifact_id,
            run_id=handle.run_id,
            agent=handle.agent,
            node_id=handle.node_id,
            attempt=handle.attempt,
            worktree_path=handle.worktree_path,
            patch_path=str(patch_path),
            source_head=handle.source_head,
            baseline_commit=handle.baseline_commit,
            dirty_context_digest=handle.dirty_context_digest,
            changed_paths=changed_paths,
            created_at=time.time(),
        )
        meta_path.write_text(json.dumps(artifact.model_dump(mode="python"), ensure_ascii=False, indent=2), encoding="utf-8")
        return artifact

    def apply_check(self, artifact: PatchArtifact) -> subprocess.CompletedProcess[str]:
        return self._git(["apply", "--check", artifact.patch_path], check=False)

    def apply(self, artifact: PatchArtifact) -> subprocess.CompletedProcess[str]:
        result = self._git(["apply", artifact.patch_path], check=False)
        if result.returncode == 0:
            return result
        return self._git(["apply", "--3way", artifact.patch_path], check=False)

    def build_effect(self, artifact: PatchArtifact) -> dict[str, Any]:
        patch_digest = hashlib.sha256(Path(artifact.patch_path).read_bytes()).hexdigest()
        normalized = {
            "artifact_id": artifact.artifact_id,
            "patch_path": artifact.patch_path,
            "changed_paths": list(artifact.changed_paths),
            "source_head": artifact.source_head,
            "baseline_commit": artifact.baseline_commit,
            "patch_digest": patch_digest,
        }
        return {
            "effect_id": str(uuid.uuid4()),
            "permission_domain": "approval",
            "tool_name": "apply_patch_artifact",
            "normalized_arguments": normalized,
            "analysis": {
                "family": "patch_artifact",
                "risk_class": "workspace_mutation",
                "summary": f"Apply isolated patch artifact {artifact.artifact_id}",
                "confidence_band": "high",
                "touches_workspace": True,
                "touches_external": False,
                "requests_network": False,
                "destructive_hint": False,
                "protected_path_hint": False,
            },
            "summary": f"Apply isolated patch artifact {artifact.artifact_id}",
            "payload_digest": hashlib.sha256(json.dumps(normalized, sort_keys=True).encode("utf-8")).hexdigest(),
            "created_at": time.time(),
            "baseline": {"kind": "patch_artifact", "patch_digest": patch_digest},
        }

    def stage_pending_artifact(
        self,
        artifact: PatchArtifact,
        pending_root: Path,
        *,
        session_id: str | None = None,
        workflow: str | None = None,
    ) -> dict[str, Any]:
        from pp_agent.storage.approvals import PendingActionStore

        effect = self.build_effect(artifact)
        return PendingActionStore(pending_root).stage(
            action_type="apply_patch_artifact",
            details={
                "artifact": artifact.model_dump(mode="python"),
                "artifact_id": artifact.artifact_id,
                "run_id": artifact.run_id,
                "session_id": session_id,
                "workflow": workflow,
                "changed_paths": list(artifact.changed_paths),
                "patch_path": artifact.patch_path,
            },
            effect=effect,
        )

    def _copy_dirty_context(self, worktree_path: Path) -> str:
        hasher = hashlib.sha256()
        diff = self._git_output(["diff", "--binary", "HEAD", "--"])
        hasher.update(diff.encode("utf-8", errors="replace"))
        if diff.strip():
            apply_result = self._git(["apply", "--binary", "--whitespace=nowarn", "-"], cwd=worktree_path, input_text=diff, check=False)
            if apply_result.returncode != 0:
                raise WorktreeUnavailable(f"failed to overlay parent dirty diff: {apply_result.stderr or apply_result.stdout}")
        untracked = self._git_stdout(["ls-files", "--others", "--exclude-standard", "-z"])
        for rel in [item for item in untracked.split("\0") if item]:
            if rel.startswith(".pp-agent/"):
                continue
            src = (self.workspace / rel).resolve()
            if not src.is_file():
                continue
            dest = (worktree_path / rel).resolve()
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            hasher.update(rel.encode("utf-8"))
            hasher.update(src.read_bytes())
        return hasher.hexdigest()

    def _baseline_commit(self, worktree_path: Path) -> str:
        self._git(["add", "-A"], cwd=worktree_path)
        self._git(
            [
                "-c",
                "user.name=pp-agent",
                "-c",
                "user.email=pp-agent@example.invalid",
                "commit",
                "--allow-empty",
                "-m",
                "pp-agent isolated worktree baseline",
            ],
            cwd=worktree_path,
        )
        return self._git_stdout(["rev-parse", "HEAD"], cwd=worktree_path)

    def _git_stdout(self, args: list[str], *, cwd: Path | None = None) -> str:
        result = self._git(args, cwd=cwd)
        return (result.stdout or "").strip()

    def _git_output(self, args: list[str], *, cwd: Path | None = None) -> str:
        result = self._git(args, cwd=cwd)
        return result.stdout or ""

    def _git(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        input_text: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=str((cwd or self.workspace).resolve()),
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
        )
        if check and result.returncode != 0:
            raise WorktreeUnavailable((result.stderr or result.stdout or "git command failed").strip())
        return result


__all__ = ["PatchArtifact", "WorktreeHandle", "WorktreeManager", "WorktreeUnavailable"]
