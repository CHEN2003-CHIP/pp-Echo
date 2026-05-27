"""
这个例子讲什么：
    记忆检索与上下文注入：不是塞入全部历史，而是找相关片段。

对应完整工程：
    src/pp_agent/memory/retrieval.py
    src/pp_agent/memory/recall_builder.py
    src/pp_agent/learning/context.py

运行命令：
    python mini-pp-echo/05_memory.py
"""

from __future__ import annotations

from dataclasses import dataclass
from math import log


@dataclass
class Memory:
    id: str
    text: str
    tags: list[str]


@dataclass
class ScoredMemory:
    memory: Memory
    score: float


class MemoryStore:
    def __init__(self) -> None:
        self.items: list[Memory] = []

    def add(self, text: str, tags: list[str]) -> None:
        memory_id = f"m{len(self.items) + 1}"
        self.items.append(Memory(memory_id, text, tags))

    def search(self, query: str, limit: int = 3) -> list[ScoredMemory]:
        query_terms = tokenize(query)
        scored: list[ScoredMemory] = []
        for item in self.items:
            item_terms = tokenize(item.text + " " + " ".join(item.tags))
            overlap = len(query_terms & item_terms)
            if overlap == 0:
                continue
            score = overlap * log(len(item_terms) + 1)
            scored.append(ScoredMemory(item, score))
        return sorted(scored, key=lambda x: x.score, reverse=True)[:limit]


def tokenize(text: str) -> set[str]:
    separators = ",.;:!?，。；：！？/\\()[]{}-_"
    normalized = text.lower()
    for sep in separators:
        normalized = normalized.replace(sep, " ")
    return {part for part in normalized.split() if part}


class RecallBuilder:
    """把检索结果压成一段可注入 prompt 的上下文。"""

    def build(self, memories: list[ScoredMemory]) -> str:
        if not memories:
            return "没有找到相关记忆。"
        lines = ["相关记忆："]
        for item in memories:
            lines.append(f"- ({item.memory.id}, score={item.score:.2f}) {item.memory.text}")
        return "\n".join(lines)


class FakeLLM:
    def answer(self, question: str, recall_context: str) -> str:
        return (
            f"问题：{question}\n"
            f"我会优先参考这些记忆：\n{recall_context}\n"
            "回答：Agent 需要在当前任务上下文中注入少量高相关记忆。"
        )


def seed_memory() -> MemoryStore:
    store = MemoryStore()
    store.add("AgentRuntime 负责 turn loop、工具调用和事件记录。", ["runtime", "agent"])
    store.add("ToolRegistry 统一注册工具，并在执行前经过策略判断。", ["tool", "policy"])
    store.add("Checkpoint 用 Git-backed snapshot 帮助恢复代码状态。", ["checkpoint", "rewind"])
    store.add("Memory 应该检索相关内容，而不是把所有历史都塞进 prompt。", ["memory", "context"])
    return store


def main() -> None:
    store = seed_memory()
    builder = RecallBuilder()
    llm = FakeLLM()

    question = "AgentRuntime 和 memory context 有什么关系？"
    results = store.search(question)
    context = builder.build(results)

    print("--- recall context ---")
    print(context)
    print("\n--- llm answer ---")
    print(llm.answer(question, context))


if __name__ == "__main__":
    main()
