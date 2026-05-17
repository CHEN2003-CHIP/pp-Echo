from __future__ import annotations

from typing import Any

"""
explicit_orchestrated_edit_request 负责意图检测，确保只有用户明确要求使用编排进行编辑时才触发规范化。
canonicalize_orchestration_arguments 负责参数纠正，用原始用户消息覆盖模型的 goal，并强制设置工作流类型、编辑权限和合理的代理预算。
"""
def explicit_orchestrated_edit_request(text: str) -> bool:
    """Return True when the latest user message creates a strict orchestration edit contract."""
    value = text.strip()
    if not value:
        return False
    lowered = value.lower()
    explicit_orchestration = (
        "orchestrate_agents" in lowered
        or "workflow=code_change" in lowered
        or "workflow = code_change" in lowered
        or "allow_edits=true" in lowered
        or "allow_edits = true" in lowered
        or "\u5fc5\u987b\u4f7f\u7528 orchestrate_agents" in value
        or "\u4f7f\u7528 orchestrate_agents" in value
    )
    edit_intent = any(
        marker in lowered
        for marker in (
            "edit",
            "write",
            "modify",
            "change",
            "append",
            "create",
            "implement",
            "fix",
            "\u4fee\u6539",
            "\u8ffd\u52a0",
            "\u5199\u5165",
            "\u7f16\u8f91",
            "\u521b\u5efa",
            "\u5b9e\u73b0",
            "\u4fee\u590d",
        )
    )
    direct_edit_forbidden = (
        "\u4e0d\u8981\u76f4\u63a5\u8c03\u7528 edit_file" in value
        or "\u4e0d\u8981\u76f4\u63a5\u8c03\u7528 edit_file/write_file" in value
        or "do not directly call edit_file" in lowered
    )
    return bool(explicit_orchestration and (edit_intent or direct_edit_forbidden))


def canonicalize_orchestration_arguments(
    arguments: dict[str, Any],
    *,
    latest_user_text: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Make explicit code-change orchestration use the user's raw request, not an LLM summary.

    The runtime is the first guard when the model fails to call `orchestrate_agents`.
    This helper is the tool-level guard when the model does call it but provides a lossy
    or self-authored goal. This mirrors mature multi-agent systems where the tool surface
    canonicalizes user contract inputs before scheduling child work.
    """
    metadata: dict[str, Any] = {"orchestrated_edit_contract": False}
    if not explicit_orchestrated_edit_request(latest_user_text):
        return dict(arguments), metadata

    canonical = dict(arguments)
    original_goal = str(canonical.get("goal") or "").strip()
    canonical["goal"] = latest_user_text.strip()
    canonical["workflow"] = "code_change"
    canonical["allow_edits"] = True
    try:
        current_budget = int(canonical.get("max_agents") or 0)
    except (TypeError, ValueError):
        current_budget = 0
    canonical["max_agents"] = max(current_budget, 6)
    metadata.update(
        {
            "orchestrated_edit_contract": True,
            "goal_source": "latest_user_message",
            "original_tool_goal": original_goal,
            "canonical_workflow": "code_change",
            "canonical_allow_edits": True,
            "canonical_max_agents": canonical["max_agents"],
        }
    )
    return canonical, metadata
