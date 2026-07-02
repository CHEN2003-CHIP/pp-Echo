from __future__ import annotations

import json

from pp_agent.context.adapters import build_context_pack_from_messages, context_pack_to_trace_details
from pp_agent.domain import ChatMessage, TextPart


def _message(role: str, text: str, *, metadata: dict | None = None) -> ChatMessage:
    return ChatMessage(role=role, content=[TextPart(text=text)], metadata=metadata or {}, timestamp=0.0)  # type: ignore[arg-type]


def test_context_trace_details_include_bounded_model_input_preview() -> None:
    messages = [
        _message("system", "You are pp-Echo.\napi_key: SHOULD_NOT_TRACE"),
        _message("system", "<think>private chain</think>\nRuntime note preview", metadata={"context_section": "runtime_notes"}),
        _message("user", "Visible user request preview"),
    ]

    details = context_pack_to_trace_details(build_context_pack_from_messages(state=None, messages=messages))
    preview = details["context"]["model_input_preview"]  # type: ignore[index]
    dumped = json.dumps(preview, ensure_ascii=False)

    assert preview["capture"] == "preview"  # type: ignore[index]
    assert preview["sections"]  # type: ignore[index]
    assert "Visible user request preview" in dumped
    assert "Runtime note preview" in dumped
    assert "SHOULD_NOT_TRACE" not in dumped
    assert "private chain" not in dumped
    assert "[hidden private reasoning]" in dumped
