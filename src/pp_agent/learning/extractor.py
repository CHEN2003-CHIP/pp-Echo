from __future__ import annotations

import json
import logging
import time
from typing import Any

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.learning.models import LearningCandidate, LearningSettings
from pp_agent.learning.safety import clean_learning_text, is_safe_learning_text

logger = logging.getLogger(__name__)


class LearningExtractor:
    def __init__(self, llm_client: Any, settings: LearningSettings) -> None:
        self.llm_client = llm_client
        self.settings = settings

    def extract(
        self,
        *,
        session_id: str,
        turn_id: str,
        messages: list[ChatMessage],
    ) -> list[LearningCandidate]:
        if not self.settings.llm_extractor_enable or not self._should_extract(messages):
            return []
        prompt_messages = [
            ChatMessage(role="system", content=[TextPart(text=self._system_prompt())], timestamp=time.time()),
            ChatMessage(role="user", content=[TextPart(text=self._turn_text(messages))], timestamp=time.time()),
        ]
        text = ""
        for event in self.llm_client.stream_chat(prompt_messages, tools=None):
            text += str(event.get("text") or "")
        payload = self._parse_json_array(text)
        candidates: list[LearningCandidate] = []
        for item in payload[: self.settings.candidate_limit_per_turn]:
            candidate = self._candidate_from_payload(item, session_id=session_id, turn_id=turn_id)
            if candidate is not None and self._meets_confidence_threshold(candidate.confidence):
                candidates.append(candidate)
        return candidates

    def _candidate_from_payload(self, payload: object, *, session_id: str, turn_id: str) -> LearningCandidate | None:
        if not isinstance(payload, dict):
            return None
        raw_text = "\n".join(
            str(payload.get(key, ""))
            for key in ("title", "content", "evidence")
        )
        if not raw_text.strip() or not is_safe_learning_text(raw_text):
            return None
        try:
            target = str(payload.get("suggested_target") or "journal")
            if target == "bootstrap_memory":
                target = "workspace_bootstrap"
            elif target == "detailed_memory":
                target = "detailed"
            elif target == "memory":
                target = "journal"
            return LearningCandidate(
                kind=str(payload.get("kind") or "lesson"),
                title=clean_learning_text(str(payload.get("title") or "Untitled lesson"), limit=120),
                content=clean_learning_text(str(payload.get("content") or ""), limit=1600),
                evidence=clean_learning_text(str(payload.get("evidence") or ""), limit=800),
                confidence=str(payload.get("confidence") or "medium"),
                suggested_target=target,
                source_session_id=session_id,
                source_turn_id=turn_id,
            )
        except ValueError as exc:
            logger.debug("Skipped invalid learning candidate: %s", exc)
            return None

    @staticmethod
    def _parse_json_array(text: str) -> list[object]:
        stripped = text.strip()
        if not stripped:
            return []
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if stripped.lower().startswith("json"):
                stripped = stripped[4:].strip()
        start = stripped.find("[")
        end = stripped.rfind("]")
        if start >= 0 and end >= start:
            stripped = stripped[start : end + 1]
        payload = json.loads(stripped)
        if not isinstance(payload, list):
            raise ValueError("Learning extractor expected a JSON array")
        return payload

    def _should_extract(self, messages: list[ChatMessage]) -> bool:
        text = self._turn_text(messages).lower()
        if not text.strip():
            return False
        signals = (
            "remember",
            "learn",
            "next time",
            "always",
            "never",
            "fix",
            "failed",
            "error",
            "convention",
            "workflow",
            "记住",
            "学习",
            "下次",
            "总是",
            "不要",
            "约定",
            "失败",
            "修复",
        )
        return any(signal in text for signal in signals)

    @staticmethod
    def _turn_text(messages: list[ChatMessage]) -> str:
        lines: list[str] = []
        for message in messages:
            text = " ".join(part.text.strip() for part in message.content if isinstance(part, TextPart) and part.text.strip())
            if text:
                prefix = message.role
                if message.tool_name:
                    prefix = f"{prefix}:{message.tool_name}"
                lines.append(f"{prefix}: {text}")
        return "\n".join(lines)

    def _system_prompt(self) -> str:
        return (
            "Extract durable learning candidates from this pp-Echo turn. "
            "Return only a JSON array. Each item must have kind, title, content, evidence, "
            "confidence, and suggested_target. kind must be one of project_convention, lesson, "
            "workflow, user_preference, skill_candidate. confidence must be low, medium, or high. "
            "suggested_target must be global_bootstrap, workspace_bootstrap, journal, detailed, skill, or ignore. "
            "Use global_bootstrap only for stable cross-workspace user preferences and working habits. "
            "Use workspace_bootstrap for stable repo conventions and durable top-level project constraints that belong in MEMORY.md. "
            "Use journal for recent smoke results, short-lived findings, temporary observations, and day-scoped work notes that belong in memory/daily/*.md. "
            "Use detailed for durable bugs, architecture decisions, debugging experience, and reusable workflow details that belong in memory/*.md. "
            "Use skill only for reusable procedures that should become an explicit skill. "
            "Do not put one-off file names, temporary artifacts, transient logs, or short-lived task traces into bootstrap memory. "
            "Only include reusable facts grounded in the turn. Do not include secrets, temporary logs, or one-off details. "
            f"Return at most {self.settings.candidate_limit_per_turn} items."
        )

    def _meets_confidence_threshold(self, confidence: str) -> bool:
        order = {"low": 0, "medium": 1, "high": 2}
        return order.get(confidence, 0) >= order.get(self.settings.min_confidence_to_suggest, 1)
