from collections.abc import Iterator

import pytest

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.learning.extractor import LearningExtractor
from pp_agent.learning.models import LearningSettings
from pp_agent.llm.models import ModelConfig


class FakeExtractorClient:
    def __init__(self, text: str) -> None:
        self.model = ModelConfig()
        self.text = text

    def stream_chat(self, _messages, tools=None) -> Iterator[dict]:
        yield {"text": self.text, "tool_calls": [], "finish_reason": "stop", "raw": {}}


def test_learning_extractor_parses_llm_json_candidates() -> None:
    client = FakeExtractorClient(
        '[{"kind":"lesson","title":"Run tests","content":"Run focused tests after edits.",'
        '"evidence":"The turn fixed runtime code.","confidence":"high","suggested_target":"memory"}]'
    )
    extractor = LearningExtractor(client, LearningSettings())

    candidates = extractor.extract(
        session_id="session-1",
        turn_id="turn-1",
        messages=[ChatMessage(role="user", content=[TextPart(text="remember to run tests next time")], timestamp=0)],
    )

    assert len(candidates) == 1
    assert candidates[0].title == "Run tests"
    assert candidates[0].confidence == "high"


def test_learning_extractor_skips_turns_without_learning_signal() -> None:
    extractor = LearningExtractor(FakeExtractorClient("[]"), LearningSettings())

    candidates = extractor.extract(
        session_id="session-1",
        turn_id="turn-1",
        messages=[ChatMessage(role="user", content=[TextPart(text="hello")], timestamp=0)],
    )

    assert candidates == []


def test_learning_extractor_raises_on_invalid_json() -> None:
    extractor = LearningExtractor(FakeExtractorClient("not-json"), LearningSettings())

    with pytest.raises(ValueError):
        extractor.extract(
            session_id="session-1",
            turn_id="turn-1",
            messages=[ChatMessage(role="user", content=[TextPart(text="remember this workflow")], timestamp=0)],
        )
