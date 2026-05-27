"""
这个例子讲什么：
    Checkpoint 与回退：在修改前保存快照，出错后恢复。

对应完整工程：
    src/pp_agent/runtime/git_checkpoint.py
    src/pp_agent/runtime/safe_rewind.py

运行命令：
    python mini-pp-echo/06_checkpoint.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory


@dataclass
class Checkpoint:
    id: str
    files: dict[str, str]
    note: str


class CheckpointManager:
    """教学版 checkpoint：用内存保存文件内容，真实工程使用 Git-backed 流程。"""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.checkpoints: list[Checkpoint] = []

    def create(self, note: str) -> Checkpoint:
        files: dict[str, str] = {}
        for path in self.workspace.rglob("*"):
            if path.is_file():
                files[str(path.relative_to(self.workspace))] = path.read_text(encoding="utf-8")
        checkpoint = Checkpoint(f"ckpt-{len(self.checkpoints) + 1}", files, note)
        self.checkpoints.append(checkpoint)
        return checkpoint

    def preview_restore(self, checkpoint: Checkpoint) -> str:
        current = self._snapshot()
        lines = [f"准备恢复 {checkpoint.id}: {checkpoint.note}"]
        for name, old_content in checkpoint.files.items():
            new_content = current.get(name)
            if new_content != old_content:
                lines.append(f"- restore {name}")
        for name in current:
            if name not in checkpoint.files:
                lines.append(f"- remove new file {name}")
        return "\n".join(lines)

    def restore(self, checkpoint: Checkpoint) -> None:
        for path in self.workspace.rglob("*"):
            if path.is_file() and str(path.relative_to(self.workspace)) not in checkpoint.files:
                path.unlink()
        for name, content in checkpoint.files.items():
            path = self.workspace / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def _snapshot(self) -> dict[str, str]:
        data: dict[str, str] = {}
        for path in self.workspace.rglob("*"):
            if path.is_file():
                data[str(path.relative_to(self.workspace))] = path.read_text(encoding="utf-8")
        return data


def show_file(path: Path) -> None:
    print(f"{path.name}: {path.read_text(encoding='utf-8').strip()}")


def main() -> None:
    with TemporaryDirectory() as dirname:
        workspace = Path(dirname)
        task = workspace / "task.py"
        task.write_text("print('stable version')\n", encoding="utf-8")

        manager = CheckpointManager(workspace)
        checkpoint = manager.create("修改前的稳定状态")

        print("--- before edit ---")
        show_file(task)

        task.write_text("print('broken version'\n", encoding="utf-8")
        (workspace / "notes.txt").write_text("临时调试文件\n", encoding="utf-8")

        print("\n--- after bad edit ---")
        show_file(task)

        print("\n--- preview rewind ---")
        print(manager.preview_restore(checkpoint))

        print("\n--- restore ---")
        manager.restore(checkpoint)
        show_file(task)
        print(f"notes exists: {(workspace / 'notes.txt').exists()}")


if __name__ == "__main__":
    main()
