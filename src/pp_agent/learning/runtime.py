from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pp_agent.domain import ChatMessage
from pp_agent.learning.extractor import LearningExtractor
from pp_agent.learning.models import LearningCandidate, LearningSettings
from pp_agent.learning.store import LearningStore

logger = logging.getLogger(__name__)


class LearningRuntime:
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

    def on_turn_persisted(
        self,
        *,
        session_id: str,
        turn_id: str,
        new_messages: list[ChatMessage],
    ) -> list[LearningCandidate]:
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
        return candidates
