from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

SENSITIVE_KEY_RE = re.compile(
    r"^(api[_-]?key|token|access[_-]?token|refresh[_-]?token|auth[_-]?token|id[_-]?token|bearer[_-]?token|"
    r"password|secret|private[_-]?key|authorization|cookie)$",
    re.IGNORECASE,
)
SECRET_TEXT_RE = re.compile(
    r"(-----BEGIN [A-Z ]*PRIVATE KEY-----|Authorization:\s*\S+|Bearer\s+[A-Za-z0-9._~+/=-]{12,}|"
    r"sk-[A-Za-z0-9_-]{12,})",
    re.IGNORECASE,
)
MAX_FIELD_CHARS = 16 * 1024


def safe_preview(text: Any, limit: int = 2000) -> str:
    """
    生成适合写入 trace 的短文本预览。

    该函数会把任意输入转换为字符串，移除明显密钥片段，并按 limit 截断。它用于
    user_goal_preview、tool output、memory snippet 等展示字段，避免把完整 stdout、
    .env、私钥或 Authorization header 写入审计文件。
    """

    value = "" if text is None else str(text)
    value = SECRET_TEXT_RE.sub("[REDACTED]", value)
    if len(value) > limit:
        return value[: max(0, limit - 14)] + "...[truncated]"
    return value


def redact_value(value: Any) -> Any:
    """
    对任意 JSON-like 值执行递归脱敏。

    Mapping 会按 key 名称识别敏感字段；list/tuple 会递归处理；字符串会裁剪到
    16KB 并替换常见密钥形态。该函数只返回可 JSON 序列化的安全摘要。
    """

    if isinstance(value, Mapping):
        return redact_mapping(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value[:200]]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value[:200]]
    if isinstance(value, str):
        return safe_preview(value, MAX_FIELD_CHARS)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if hasattr(value, "model_dump"):
        try:
            return redact_mapping(value.model_dump(mode="python"))
        except Exception:  # noqa: BLE001
            return safe_preview(value, 1000)
    return safe_preview(value, 1000)


def redact_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    """
    对字典按敏感 key 规则脱敏。

    key 名是 api_key/token/password/secret/private_key/authorization/cookie 等真实凭据字段时，
    value 会替换为 [REDACTED]。其它字段递归调用 redact_value。输出会限制字段数，
    防止异常工具结果造成 trace 文件膨胀。
    """

    result: dict[str, Any] = {}
    for index, (key, value) in enumerate(data.items()):
        if index >= 300:
            result["__truncated_keys__"] = True
            break
        safe_key = str(key)
        if SENSITIVE_KEY_RE.search(safe_key):
            result[safe_key] = "[REDACTED]"
        else:
            result[safe_key] = redact_value(value)
    return result


def sanitize_tool_args(args: dict[str, Any]) -> dict[str, Any]:
    """
    生成工具参数的审计安全版本。

    该函数是 redact_mapping 的语义化包装，供 ToolRegistry/Runtime 写 trace 时使用。
    对于 prompt/messages/content 等可能很长的字段，只保存截断预览，不保存完整内容。
    """

    sanitized = redact_mapping(args)
    for key in ("prompt", "messages", "content", "diff", "new_text", "old_text"):
        if key in sanitized:
            sanitized[key] = safe_preview(sanitized[key], 2000)
    return sanitized


def json_safe(data: Any) -> Any:
    """
    把任意对象转换为 JSON 可序列化值。

    TraceStore 写入前会调用该函数兜底，保证 pydantic 对象、Path、异常等值不会导致
    整个 trace 写入失败。
    """

    redacted = redact_value(data)
    try:
        json.dumps(redacted, ensure_ascii=False)
        return redacted
    except TypeError:
        return safe_preview(redacted, 2000)
