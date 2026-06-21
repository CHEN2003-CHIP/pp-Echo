from __future__ import annotations

from typing import Any

from pp_agent.llm.model_profile import ModelCapabilityProfile
from pp_agent.llm.registry import infer_model_profile
from pp_agent.runtime.profile import RuntimeProfile
from pp_agent.runtime.registry import DEFAULT_RUNTIME_REGISTRY


def resolve_model_profile(config: Any) -> ModelCapabilityProfile:
    """
    Resolve any supported config snapshot into the new ModelCapabilityProfile shape.

    New runtime code consumes profiles only. Provider/model strings are read from the
    current settings or concrete client config objects, not from the removed v0.2.x
    compatibility adapter.
    """
    provider_id, model_id = _provider_model_from_config(config)
    return infer_model_profile(provider_id or "unknown", model_id or "unknown")


def resolve_runtime_profile(config: Any) -> RuntimeProfile:
    """
    Resolve runtime selection into a RuntimeProfile, defaulting to pp_echo_native.

    Unknown runtime ids fall back to the native runtime and are tagged in metadata so
    callers can surface the migration issue without breaking existing chat flows.
    """
    runtime_id = _first_text(
        getattr(config, "runtime_id", None),
        _nested_attr(config, "settings", "runtime_id"),
        _nested_attr(config, "runtime", "id"),
    )
    if not runtime_id:
        return DEFAULT_RUNTIME_REGISTRY.get_default()
    try:
        return DEFAULT_RUNTIME_REGISTRY.get(runtime_id)
    except KeyError:
        fallback = DEFAULT_RUNTIME_REGISTRY.get_default().model_copy(deep=True)
        fallback.metadata = {
            **fallback.metadata,
            "source": "inferred",
            "requested_runtime_id": runtime_id,
            "fallback_reason": "unknown_runtime",
        }
        return fallback


def _provider_model_from_config(config: Any) -> tuple[str, str]:
    settings = getattr(config, "settings", None)
    root = settings or config
    provider_obj = getattr(root, "provider", None)
    model_obj = getattr(root, "model", None)
    provider_id = _first_text(
        getattr(provider_obj, "name", None),
        getattr(model_obj, "provider", None),
    )
    model_id = _first_text(
        getattr(model_obj, "model", None),
    )
    return provider_id or "unknown", model_id or "unknown"


def _nested_attr(value: Any, *names: str) -> Any:
    current = value
    for name in names:
        current = getattr(current, name, None)
        if current is None:
            return None
    return current


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
