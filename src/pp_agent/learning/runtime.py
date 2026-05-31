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
    """Best-effort learning extraction after each persisted turn."""

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
        self._extraction_disabled = False
        self._extraction_disabled_reason: str | None = None

    def refresh_llm_client(self, llm_client: Any, *, settings: LearningSettings | None = None) -> None:
        if settings is not None:
            self.settings = settings
            self.file_memory_writer.settings = settings
        self.extractor.llm_client = llm_client
        if self._extraction_disabled and self._extraction_disabled_reason:
            self._extraction_disabled = False
            self._extraction_disabled_reason = None

    def on_turn_persisted(
        self,
        *,
        session_id: str,
        turn_id: str,
        new_messages: list[ChatMessage],
    ) -> list[LearningCandidate]:
        if not self.settings.enable or not self.settings.auto_extract:
            return []
        if self._extraction_disabled:
            logger.debug(
                "Learning extraction is disabled for session=%s turn=%s; skipping extraction",
                session_id,
                turn_id,
            )
            return []
        try:
            candidates = self.extractor.extract(
                session_id=session_id,
                turn_id=turn_id,
                messages=new_messages,
            )
        except Exception as exc:  # noqa: BLE001
            if self._is_quota_exhausted_error(exc):
                self._extraction_disabled = True
                self._extraction_disabled_reason = str(exc)
                logger.warning(
                    "Learning extraction disabled for session=%s turn=%s after quota exhaustion: %s",
                    session_id,
                    turn_id,
                    exc,
                )
                return []
            logger.warning("Learning extraction failed for session=%s turn=%s: %s", session_id, turn_id, exc)
            return []
        self.store.append_candidates(candidates)
        try:
            self.file_memory_writer.auto_apply(candidates)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Automatic file memory write failed for session=%s turn=%s: %s", session_id, turn_id, exc)
        return candidates

    @staticmethod
    def _is_quota_exhausted_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return (
            "allocationquota.freetieronly" in text
            or "free tier of the model has been exhausted" in text
            or ("use free tier only" in text and "403" in text)
        )
