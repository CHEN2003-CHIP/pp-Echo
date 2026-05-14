from __future__ import annotations

import time
from pathlib import Path

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.learning.bootstrap_memory import BootstrapMemoryManager
from pp_agent.learning.models import LearningSettings
from pp_agent.learning.store import LearningStore
from pp_agent.runtime.state import AgentState


class ProjectMemoryContextHook:
    def __init__(self, *, workspace: Path, settings: LearningSettings, store: LearningStore | None = None) -> None:
        self.workspace = workspace.resolve()
        self.settings = settings
        self.store = store or LearningStore(self.workspace / ".pp-agent" / "learning")

    def transform_context(self, _state: AgentState, messages: list[ChatMessage]) -> list[ChatMessage]:
        if not self.settings.enable or not self.settings.project_memory_enable:
            return messages
        content = self._read_bootstrap_memory().strip()
        if not content:
            return messages
        if len(content) > self.settings.project_memory_char_limit:
            content = content[-self.settings.project_memory_char_limit :]
        memory_message = ChatMessage(
            role="system",
            content=[TextPart(text=f"Project memory learned by pp-Echo:\n{content}")],
            timestamp=time.time(),
        )
        if not messages:
            return [memory_message]
        return [messages[0], memory_message, *messages[1:]]

    def _read_bootstrap_memory(self) -> str:
        bootstrap = BootstrapMemoryManager(workspace=self.workspace, settings=self.settings).read().strip()
        if bootstrap:
            return bootstrap
        return self.store.read_project_memory()
