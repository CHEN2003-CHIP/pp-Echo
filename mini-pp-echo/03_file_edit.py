"""
这个例子讲什么：
    文件读写与最小 patch：先预览差异，再把修改应用到文件。

对应完整工程：
    src/pp_agent/tools/file_tools.py
    src/pp_agent/tools/effects.py

运行命令：
    python mini-pp-echo/03_file_edit.py
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path
from tempfile import TemporaryDirectory


@dataclass
class Patch:
    path: Path
    before: str
    after: str

    def diff(self) -> str:
        return "".join(
            unified_diff(
                self.before.splitlines(keepends=True),
                self.after.splitlines(keepends=True),
                fromfile=f"a/{self.path.name}",
                tofile=f"b/{self.path.name}",
            )
        )


class FileEditor:
    """教学版文件工具：只允许在 workspace 内读写。"""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def _resolve(self, relative: str) -> Path:
        path = (self.workspace / relative).resolve()
        if self.workspace not in path.parents and path != self.workspace:
            raise ValueError("拒绝访问 workspace 外的路径")
        return path

    def read(self, relative: str) -> str:
        return self._resolve(relative).read_text(encoding="utf-8")

    def build_replace_patch(self, relative: str, old: str, new: str) -> Patch:
        path = self._resolve(relative)
        before = path.read_text(encoding="utf-8")
        if old not in before:
            raise ValueError(f"找不到要替换的文本：{old}")
        after = before.replace(old, new, 1)
        return Patch(path, before, after)

    def apply(self, patch: Patch) -> None:
        patch.path.write_text(patch.after, encoding="utf-8")


class FakeLLM:
    def propose_edit(self, content: str) -> tuple[str, str]:
        if "TODO" in content:
            return "TODO", "DONE"
        return "hello", "hello from mini agent"


def demo_workspace() -> TemporaryDirectory[str]:
    temp = TemporaryDirectory()
    root = Path(temp.name)
    (root / "task.txt").write_text(
        "hello\nTODO: explain tool-driven file edits\n",
        encoding="utf-8",
    )
    return temp


def main() -> None:
    with demo_workspace() as dirname:
        workspace = Path(dirname)
        editor = FileEditor(workspace)
        llm = FakeLLM()

        print(f"教学 workspace: {workspace}")
        print("\n--- before ---")
        content = editor.read("task.txt")
        print(content)

        old, new = llm.propose_edit(content)
        patch = editor.build_replace_patch("task.txt", old, new)

        print("--- preview diff ---")
        print(patch.diff())

        print("--- apply patch ---")
        editor.apply(patch)
        print(editor.read("task.txt"))

        print("重点：真实工程会把 patch 的效果摘要交给审批、timeline 和 checkpoint。")


if __name__ == "__main__":
    main()
