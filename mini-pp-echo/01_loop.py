"""
这个例子讲什么：
    最小 Agent Loop：用户输入 -> LLM 决策 -> 记录事件 -> 最终回答。

对应完整工程：
    src/pp_agent/runtime/runtime.py
    src/pp_agent/runtime/turn_loop.py

运行命令：
    python mini-pp-echo/01_loop.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Role = Literal["user", "assistant", "system"]


@dataclass
class Message:
    role: Role
    content: str


@dataclass
class Event:
    kind: str
    detail: str


@dataclass
class AgentState:
    messages: list[Message] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    turn_id: int = 0

    def add_message(self, role: Role, content: str) -> None:
        self.messages.append(Message(role, content))

    def emit(self, kind: str, detail: str) -> None:
        self.events.append(Event(kind, detail))
        print(f"[event] {kind}: {detail}")


class FakeLLM:
    """脚本化 LLM：用固定规则代替真实模型，方便观察 runtime。"""

    def complete(self, messages: list[Message]) -> str:
        last_user = next(m.content for m in reversed(messages) if m.role == "user")
        if "计划" in last_user or "plan" in last_user.lower():
            return "计划：1. 理解任务；2. 选择工具；3. 执行并总结。"
        return f"我已收到：{last_user}。这是一个最小 Agent Loop 的回答。"


class MiniAgent:
    def __init__(self, llm: FakeLLM) -> None:
        self.llm = llm
        self.state = AgentState()
        self.state.add_message("system", "你是一个教学用本地编程 Agent。")

    def run_turn(self, user_input: str) -> str:
        self.state.turn_id += 1
        self.state.emit("turn.started", f"turn={self.state.turn_id}")

        self.state.add_message("user", user_input)
        self.state.emit("context.ready", f"messages={len(self.state.messages)}")

        answer = self.llm.complete(self.state.messages)
        self.state.emit("llm.completed", answer[:40])

        self.state.add_message("assistant", answer)
        self.state.emit("turn.finished", f"turn={self.state.turn_id}")
        return answer


def print_transcript(agent: MiniAgent) -> None:
    print("\n--- transcript ---")
    for message in agent.state.messages:
        print(f"{message.role:>9}: {message.content}")


def print_events(agent: MiniAgent) -> None:
    print("\n--- events ---")
    for event in agent.state.events:
        print(f"{event.kind:16} {event.detail}")


def main() -> None:
    agent = MiniAgent(FakeLLM())

    print("用户：请给我一个实现本地 Agent 的计划")
    answer = agent.run_turn("请给我一个实现本地 Agent 的计划")
    print(f"助手：{answer}")

    print("\n用户：为什么需要 runtime？")
    answer = agent.run_turn("为什么需要 runtime？")
    print(f"助手：{answer}")

    print_transcript(agent)
    print_events(agent)


if __name__ == "__main__":
    main()
