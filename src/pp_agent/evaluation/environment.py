from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess

from pp_agent.evaluation.models import CommandResult, EvalTask


IGNORED_PARTS = {".pp-agent", "__pycache__", ".pytest_cache"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}


class WorkspaceEnvironment:
    def __init__(self, repo_root: Path, task: EvalTask, run_root: Path) -> None:
        self.repo_root = repo_root
        self.task = task
        self.run_root = run_root
        self.workspace = run_root / task.id

    def prepare(self) -> Path:
        source = self.repo_root / "evals" / "fixtures" / self.task.workspace_fixture
        if not source.exists():
            raise FileNotFoundError(f"Missing fixture for task {self.task.id}: {source}")
        if self.workspace.exists():
            shutil.rmtree(self.workspace)
        shutil.copytree(source, self.workspace)
        return self.workspace

    def snapshot(self) -> dict[str, str]:
        return snapshot_files(self.workspace)

    def run_verification_commands(self) -> list[CommandResult]:
        results: list[CommandResult] = []
        for command in self.task.success_criteria.verification_commands:
            completed = subprocess.run(command, cwd=self.workspace, shell=True, text=True, capture_output=True, check=False)
            results.append(
                CommandResult(
                    command=command,
                    returncode=completed.returncode,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                )
            )
        return results


def snapshot_files(workspace: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(workspace)
        if _should_ignore(relative):
            continue
        snapshot[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def changed_files(before: dict[str, str], after: dict[str, str]) -> set[str]:
    names = set(before) | set(after)
    return {name for name in names if before.get(name) != after.get(name)}


def _should_ignore(relative_path: Path) -> bool:
    if any(part in IGNORED_PARTS for part in relative_path.parts):
        return True
    return relative_path.suffix in IGNORED_SUFFIXES

