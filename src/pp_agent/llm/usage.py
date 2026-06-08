from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


class UsageSnapshot(BaseModel):
    """LLM 使用情况快照。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class LLMUsageStats:
    """
    表示一次 LLM Provider 调用后可用于 TraceInspect 和 summary.py 的标准化用量数据。

    不同 provider 返回的 usage 字段命名并不一致，这个结构把它们归一成 pp-Echo
    内部稳定字段。它只保存 token、延迟、重试、request id 和可确定的成本摘要，不保存完整
    prompt、隐藏推理链、Authorization、cookie、API key 或私钥。provider 没有返回的字段保持
    None；当前没有内部重试时 retry_count 为 0、attempt_index 为 1。观测链路失败或字段缺失不应
    影响主流程。
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None
    provider_latency_ms: int | None = None
    retry_count: int = 0
    attempt_index: int = 1
    request_id: str | None = None

    def as_trace_attributes(self) -> dict[str, Any]:
        """返回适合写入 llm.call span attributes 的 JSON-like 字段。"""

        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "provider_latency_ms": self.provider_latency_ms,
            "retry_count": self.retry_count,
            "attempt_index": self.attempt_index,
            "request_id": self.request_id,
        }


@dataclass(frozen=True)
class ModelPricing:
    """
    表示某个模型的 token 价格配置，单位统一为 USD / 1M tokens。

    该结构只在用户明确配置或项目内置少量稳定价格时用于成本估算。未知价格不会被猜测，
    estimate_cost_usd 会返回 None，避免 TraceInspect 和 summary.py 展示误导性的成本。
    cached_input_per_1m 与 reasoning_per_1m 可选；缺失时会按普通 input/output 价格或 0 处理。
    """

    input_per_1m: float | None = None
    output_per_1m: float | None = None
    cached_input_per_1m: float | None = None
    reasoning_per_1m: float | None = None


def _mapping(raw: object | dict | None) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "model_dump"):
        try:
            value = raw.model_dump(mode="python")
            return value if isinstance(value, dict) else {}
        except Exception:  # noqa: BLE001
            return {}
    result: dict[str, Any] = {}
    for key in (
        "prompt_tokens",
        "completion_tokens",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "prompt_tokens_details",
        "completion_tokens_details",
        "input_tokens_details",
        "output_tokens_details",
    ):
        if hasattr(raw, key):
            result[key] = getattr(raw, key)
    return result


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _nested_int(data: dict[str, Any], key: str, nested_key: str) -> int | None:
    nested = _mapping(data.get(key))
    return _optional_int(nested.get(nested_key))


def normalize_usage(raw_usage: object | dict | None) -> LLMUsageStats:
    """
    将 provider 返回的原始 usage 对象或 dict 归一化为 LLMUsageStats。

    兼容 OpenAI-compatible 字段 prompt_tokens/completion_tokens/total_tokens、
    prompt_tokens_details.cached_tokens、completion_tokens_details.reasoning_tokens，也兼容
    input_tokens/output_tokens/total_tokens。total_tokens 缺失但 input/output 均存在时自动相加。
    函数只读取结构化用量字段，不读取或保存 prompt 内容、隐藏推理链或敏感认证信息。
    """

    data = _mapping(raw_usage)
    input_tokens = _optional_int(data.get("input_tokens"))
    if input_tokens is None:
        input_tokens = _optional_int(data.get("prompt_tokens"))
    output_tokens = _optional_int(data.get("output_tokens"))
    if output_tokens is None:
        output_tokens = _optional_int(data.get("completion_tokens"))
    total_tokens = _optional_int(data.get("total_tokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return LLMUsageStats(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_input_tokens=_nested_int(data, "prompt_tokens_details", "cached_tokens")
        or _nested_int(data, "input_tokens_details", "cached_tokens"),
        reasoning_tokens=_nested_int(data, "completion_tokens_details", "reasoning_tokens")
        or _nested_int(data, "output_tokens_details", "reasoning_tokens"),
    )


def estimate_cost_usd(model: str | None, usage: LLMUsageStats, pricing: ModelPricing | None = None) -> float | None:
    """
    基于明确传入的 ModelPricing 估算一次 LLM 调用成本。

    model 只用于未来接入配置表时保持签名稳定；当前没有 pricing 时直接返回 None，不猜测价格。
    计算按 input/output/cached/reasoning 分项累加，单位为 USD，结果 round 到 8 位小数。该函数只消费
    LLMUsageStats 的数值字段，不接触 prompt、API key 或 provider 原始响应。
    """

    _ = model
    if pricing is None:
        return None
    cost = 0.0
    saw_price = False
    cached_tokens = usage.cached_input_tokens or 0
    input_tokens = max(0, (usage.input_tokens or 0) - cached_tokens)
    if pricing.input_per_1m is not None and input_tokens:
        cost += input_tokens * pricing.input_per_1m / 1_000_000
        saw_price = True
    if pricing.cached_input_per_1m is not None and cached_tokens:
        cost += cached_tokens * pricing.cached_input_per_1m / 1_000_000
        saw_price = True
    elif pricing.input_per_1m is not None and cached_tokens:
        cost += cached_tokens * pricing.input_per_1m / 1_000_000
        saw_price = True
    if pricing.output_per_1m is not None and usage.output_tokens:
        cost += usage.output_tokens * pricing.output_per_1m / 1_000_000
        saw_price = True
    if pricing.reasoning_per_1m is not None and usage.reasoning_tokens:
        cost += usage.reasoning_tokens * pricing.reasoning_per_1m / 1_000_000
        saw_price = True
    return round(cost, 8) if saw_price else None
