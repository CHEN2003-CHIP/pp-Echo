from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RuntimeContext:
    profile_id: str = "default"
    session_id: str | None = None
    channel_id: str | None = None
    user_id: str | None = None
    external_user_id: str | None = None
    source_ref: str | None = None
    run_id: str | None = None
    runtime_trace_run_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeInput:
    text: str
    context: RuntimeContext = field(default_factory=RuntimeContext)

    @property
    def profile_id(self) -> str:
        return self.context.profile_id

    @property
    def session_id(self) -> str | None:
        return self.context.session_id

    @property
    def channel_id(self) -> str | None:
        return self.context.channel_id

    @property
    def user_id(self) -> str | None:
        return self.context.user_id or self.context.external_user_id

    @property
    def source_ref(self) -> str | None:
        return self.context.source_ref


@dataclass(frozen=True)
class RuntimeResult:
    text: str
    context: RuntimeContext = field(default_factory=RuntimeContext)
    events: list[Any] = field(default_factory=list)
    raw: Any | None = None

    @property
    def run_id(self) -> str | None:
        return self.context.run_id

    @property
    def runtime_trace_run_id(self) -> str | None:
        return self.context.runtime_trace_run_id or self.context.run_id

    @property
    def session_id(self) -> str | None:
        return self.context.session_id


def runtime_context_from_mapping(payload: dict[str, Any] | None) -> RuntimeContext:
    payload = dict(payload or {})
    return RuntimeContext(
        profile_id=str(payload.get("profile_id") or "default"),
        session_id=_optional_str(payload.get("session_id")),
        channel_id=_optional_str(payload.get("channel_id")),
        user_id=_optional_str(payload.get("user_id")),
        external_user_id=_optional_str(payload.get("external_user_id")),
        source_ref=_optional_str(payload.get("source_ref")),
        run_id=_optional_str(payload.get("run_id")),
        runtime_trace_run_id=_optional_str(payload.get("runtime_trace_run_id")),
        metadata=dict(payload.get("metadata") or {}),
    )


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
