from __future__ import annotations

import time
import importlib
from pathlib import Path

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.learning.bootstrap_memory import BootstrapMemoryManager
from pp_agent.learning.models import LearningSettings
from pp_agent.runtime.state import AgentState


class ProjectMemoryContextHook:
    
    
    def __init__(self, *, workspace: Path, settings: LearningSettings) -> None:
        self.workspace = workspace.resolve()
        self.settings = settings

    def transform_context(self, _state: AgentState, messages: list[ChatMessage]) -> list[ChatMessage]:
        if not self.settings.enable or not self.settings.project_memory_enable:
            return messages
        result = _markdown_memory().read_workspace_memory(self.workspace, self.settings)
        if result.item is None:
            return messages
        content = result.item.content.strip()
        if len(content) > self.settings.project_memory_char_limit:
            content = content[-self.settings.project_memory_char_limit :]
        memory_message = ChatMessage(
            role="system",
            content=[TextPart(text=f"Workspace bootstrap memory learned by pp-Echo:\n{content}")],
            metadata=_message_metadata(result.item),
            timestamp=time.time(),
        )
        if not messages:
            return [memory_message]
        return [messages[0], memory_message, *messages[1:]]

    def _read_bootstrap_memory(self) -> str:
        return BootstrapMemoryManager(workspace=self.workspace, settings=self.settings).read().strip()


class GlobalMemoryContextHook:
    """注入全局用户记忆。
    与项目记忆不同，全局记忆存储在用户目录下的固定文件（MEMORY.md）中，跨项目生效，通常包含用户的个人偏好、常用约定等。"""
    def __init__(self, *, workspace: Path, settings: LearningSettings, global_root: Path) -> None:
        self.workspace = workspace.resolve()
        self.settings = settings
        self.global_root = global_root.resolve()

    def transform_context(self, _state: AgentState, messages: list[ChatMessage]) -> list[ChatMessage]:
        if not self.settings.enable:
            return messages
        result = _markdown_memory().read_global_memory(self.global_root, self.settings)
        if result.item is None:
            return messages
        content = result.item.content.strip()
        memory_message = ChatMessage(
            role="system",
            content=[TextPart(text=f"Global user memory learned by pp-Echo:\n{content}")],
            metadata=_message_metadata(result.item),
            timestamp=time.time(),
        )
        if not messages:
            return [memory_message]
        return [messages[0], memory_message, *messages[1:]]


def _message_metadata(item) -> dict[str, object]:
    source = item.source_ref
    return {
        "context_section": "markdown_memory",
        "context_type": "markdown_memory",
        "context_item_id": item.id,
        "source_type": "markdown_memory",
        "source_id": source.source_id,
        "path": source.path,
        "line_start": source.line_start,
        "line_end": source.line_end,
        "heading": source.heading,
        **item.metadata,
    }


def _markdown_memory():
    """Load markdown memory helpers lazily so learning keeps its architecture boundary."""

    return importlib.import_module("pp_agent.context.markdown_memory")
