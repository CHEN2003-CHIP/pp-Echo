from types import SimpleNamespace

from pp_agent.llm.usage import LLMUsageStats, ModelPricing, estimate_cost_usd, normalize_usage


def test_normalize_usage_supports_openai_compatible_fields() -> None:
    usage = normalize_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 25,
            "total_tokens": 125,
            "prompt_tokens_details": {"cached_tokens": 40},
            "completion_tokens_details": {"reasoning_tokens": 5},
        }
    )

    assert usage.input_tokens == 100
    assert usage.output_tokens == 25
    assert usage.total_tokens == 125
    assert usage.cached_input_tokens == 40
    assert usage.reasoning_tokens == 5


def test_normalize_usage_supports_input_output_and_computes_total() -> None:
    usage = normalize_usage(SimpleNamespace(input_tokens="7", output_tokens=3))

    assert usage.input_tokens == 7
    assert usage.output_tokens == 3
    assert usage.total_tokens == 10


def test_estimate_cost_requires_known_pricing() -> None:
    usage = LLMUsageStats(input_tokens=1000, output_tokens=500, cached_input_tokens=100)

    assert estimate_cost_usd("unknown", usage) is None
    assert estimate_cost_usd(
        "priced",
        usage,
        ModelPricing(input_per_1m=2.0, output_per_1m=10.0, cached_input_per_1m=0.5),
    ) == 0.00685
