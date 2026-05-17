from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pp_agent.domain import ChatMessage
from pp_agent.learning.extractor import LearningExtractor
from pp_agent.learning.file_memory_writer import FileMemoryWriter
from pp_agent.learning.models import LearningCandidate, LearningSettings
from pp_agent.learning.store import LearningStore

logger = logging.getLogger(__name__)


class LearningRuntime:
    """负责在对话的每个轮次被持久化后，
    自动从中提取“可学习”的知识（比如用户偏好、项目约定等），并将这些候选内容存储下来，同时尝试自动写入文件形式的记忆。"""
    def __init__(
        self,
        *,
        workspace: Path,
        llm_client: Any,
        settings: LearningSettings,
        store: LearningStore | None = None,
        extractor: LearningExtractor | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.settings = settings
        self.store = store or LearningStore(self.workspace / ".pp-agent" / "learning")
        self.extractor = extractor or LearningExtractor(llm_client, settings)
        self.file_memory_writer = FileMemoryWriter(workspace=self.workspace, settings=settings, store=self.store)

    def on_turn_persisted(
        self,
        *,
        session_id: str,
        turn_id: str,
        new_messages: list[ChatMessage],
    ) -> list[LearningCandidate]:
        """当一个新的对话轮次（turn）被持久化（即保存到对话历史）后调用，触发学习流程。"""
        if not self.settings.enable or not self.settings.auto_extract:
            return []
        try:
            candidates = self.extractor.extract(
                session_id=session_id,
                turn_id=turn_id,
                messages=new_messages,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Learning extraction failed for session=%s turn=%s: %s", session_id, turn_id, exc)
            raise
        self.store.append_candidates(candidates)
        try:
            self.file_memory_writer.auto_apply(candidates)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Automatic file memory write failed for session=%s turn=%s: %s", session_id, turn_id, exc)
        return candidates
