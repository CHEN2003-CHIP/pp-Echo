"""
这个例子讲什么：
    Tool Registry 与工具调用：模型不直接执行函数，而是请求一个具名工具。

对应完整工程：
    src/pp_agent/tools/registry.py
    src/pp_agent/tools/base.py

运行命令：
    python mini-pp-echo/02_tool_call.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    ok: bool
    content: str


ToolFn = Callable[[dict[str, Any]], ToolResult]


class ToolRegistry:
    """教学版工具注册表：只保留注册、列出、调用三个动作。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolFn] = {}
        self._descriptions: dict[str, str] = {}

    def register(self, name: str, description: str, fn: ToolFn) -> None:
        if name in self._tools:
            raise ValueError(f"工具已存在：{name}")
        self._tools[name] = fn
        self._descriptions[name] = description

    def describe_tools(self) -> str:
        lines = ["可用工具："]
        for name, desc in self._descriptions.items():
            lines.append(f"- {name}: {desc}")
        return "\n".join(lines)

    def execute(self, call: ToolCall) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(False, f"未知工具：{call.name}")
        return tool(call.arguments)


class FakeLLM:
    """用关键词模拟模型选择工具。"""

    def decide(self, user_input: str, tool_text: str) -> ToolCall | str:
        print("\n--- tool context sent to llm ---")
        print(tool_text)
        if "列出" in user_input or "list" in user_input.lower():
            return ToolCall("list_files", {"path": "."})
        if "读" in user_input or "read" in user_input.lower():
            return ToolCall("read_text", {"path": "README.md", "max_chars": 120})
        return "不需要工具，我可以直接回答。"


def list_files(args: dict[str, Any]) -> ToolResult:
    root = Path(args.get("path", "."))
    names = sorted(p.name for p in root.iterdir())[:8]
    return ToolResult(True, "\n".join(names))


def read_text(args: dict[str, Any]) -> ToolResult:
    path = Path(str(args["path"]))
    max_chars = int(args.get("max_chars", 200))
    if not path.exists():
        return ToolResult(False, f"文件不存在：{path}")
    return ToolResult(True, path.read_text(encoding="utf-8", errors="replace")[:max_chars])


class MiniAgent:
    def __init__(self) -> None:
        self.registry = ToolRegistry()
        self.llm = FakeLLM()
        self.registry.register("list_files", "列出目录中的文件名", list_files)
        self.registry.register("read_text", "读取文本文件前 N 个字符", read_text)

    def run(self, user_input: str) -> None:
        print(f"\n用户：{user_input}")
        decision = self.llm.decide(user_input, self.registry.describe_tools())
        if isinstance(decision, str):
            print(f"助手：{decision}")
            return

        print(f"助手请求工具：{decision.name} {decision.arguments}")
        result = self.registry.execute(decision)
        print(f"工具结果 ok={result.ok}:\n{result.content}")
        print("助手：我已根据工具结果完成回答。")


def main() -> None:
    agent = MiniAgent()
    agent.run("请列出当前目录")
    agent.run("请读一下 README.md 的开头")
    agent.run("解释一下为什么工具要注册")


if __name__ == "__main__":
    main()
