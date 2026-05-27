"""
这个例子讲什么：
    Approval Gate：高风险工具不直接执行，而是生成 pending action 等待确认。

对应完整工程：
    src/pp_agent/tools/policy.py
    src/pp_agent/storage/approvals.py

运行命令：
    python mini-pp-echo/04_approval.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4


Decision = Literal["allow", "ask", "deny"]


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class PendingAction:
    id: str
    call: ToolCall
    effect_summary: str
    approved: bool | None = None


class Policy:
    """教学版策略：读操作允许，shell 和写操作需要审批，危险命令拒绝。"""

    def decide(self, call: ToolCall) -> Decision:
        if call.name == "run_shell" and "Remove-Item" in str(call.arguments):
            return "deny"
        if call.name in {"write_file", "run_shell"}:
            return "ask"
        return "allow"


class PendingActionStore:
    def __init__(self) -> None:
        self.actions: dict[str, PendingAction] = {}

    def create(self, call: ToolCall, effect_summary: str) -> PendingAction:
        action = PendingAction(str(uuid4())[:8], call, effect_summary)
        self.actions[action.id] = action
        return action

    def approve(self, action_id: str) -> PendingAction:
        action = self.actions[action_id]
        action.approved = True
        return action

    def reject(self, action_id: str) -> PendingAction:
        action = self.actions[action_id]
        action.approved = False
        return action


class ToolExecutor:
    def execute(self, call: ToolCall) -> str:
        if call.name == "read_file":
            return f"读取文件：{call.arguments['path']}"
        if call.name == "write_file":
            return f"写入文件：{call.arguments['path']}"
        if call.name == "run_shell":
            return f"执行命令：{call.arguments['command']}"
        return f"未知工具：{call.name}"


class MiniAgent:
    def __init__(self) -> None:
        self.policy = Policy()
        self.pending = PendingActionStore()
        self.executor = ToolExecutor()

    def handle_tool_call(self, call: ToolCall) -> str:
        decision = self.policy.decide(call)
        if decision == "deny":
            return f"已拒绝：{call.name} 被策略拦截"
        if decision == "allow":
            return self.executor.execute(call)

        effect = self.describe_effect(call)
        action = self.pending.create(call, effect)
        return f"需要审批：pending_id={action.id}\n效果预览：{effect}"

    def approve_and_run(self, action_id: str) -> str:
        action = self.pending.approve(action_id)
        if action.approved is not True:
            return "审批状态异常"
        return self.executor.execute(action.call)

    def describe_effect(self, call: ToolCall) -> str:
        if call.name == "write_file":
            return f"将修改文件 {call.arguments['path']}"
        if call.name == "run_shell":
            return f"将运行 shell 命令：{call.arguments['command']}"
        return f"将执行 {call.name}"


def main() -> None:
    agent = MiniAgent()

    safe = ToolCall("read_file", {"path": "README.md"})
    print("安全工具：")
    print(agent.handle_tool_call(safe))

    risky = ToolCall("run_shell", {"command": "python -m compileall mini-pp-echo"})
    print("\n高风险工具：")
    response = agent.handle_tool_call(risky)
    print(response)

    action_id = response.split("pending_id=")[1].split("\n")[0]
    print("\n用户批准后：")
    print(agent.approve_and_run(action_id))

    denied = ToolCall("run_shell", {"command": "Remove-Item -Recurse ."})
    print("\n策略拒绝：")
    print(agent.handle_tool_call(denied))


if __name__ == "__main__":
    main()
