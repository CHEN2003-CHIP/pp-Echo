from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Optional

from pp_agent.runtime import AgentEvent, AgentRuntime, SessionHost

Subscriber = Callable[[AgentEvent], None]


def create_runtime(
    workspace: Path,
    *,
    session_id: Optional[str] = None,
    lifecycle_subscribers: Optional[list[Subscriber]] = None,
    host: Optional[SessionHost] = None,
) -> AgentRuntime:
    session_host = host or _default_host(workspace)
    if session_id:
        return session_host.restore_session(workspace, session_id, lifecycle_subscribers=lifecycle_subscribers)
    return session_host.create_session(workspace, lifecycle_subscribers=lifecycle_subscribers)


def create_session(workspace: Path, *, lifecycle_subscribers: Optional[list[Subscriber]] = None, host: Optional[SessionHost] = None) -> AgentRuntime:
    return (host or _default_host(workspace)).create_session(workspace, lifecycle_subscribers=lifecycle_subscribers)


def restore_session(
    workspace: Path,
    session_id: str,
    *,
    lifecycle_subscribers: Optional[list[Subscriber]] = None,
    host: Optional[SessionHost] = None,
) -> AgentRuntime:
    return (host or _default_host(workspace)).restore_session(workspace, session_id, lifecycle_subscribers=lifecycle_subscribers)


def run(
    prompt: str,
    workspace: Path,
    *,
    session_id: Optional[str] = None,
    collect_events: bool = False,
    subscriber: Optional[Subscriber] = None,
    subscribers: Optional[list[Subscriber]] = None,
    host: Optional[SessionHost] = None,
) -> dict:
    event_subscribers = _merge_subscribers(subscriber=subscriber, subscribers=subscribers)
    runtime = create_runtime(workspace, session_id=session_id, lifecycle_subscribers=event_subscribers, host=host)
    events = runtime.prompt(prompt)
    return _result_payload(runtime, events, collect_events=collect_events)


def continue_session(
    workspace: Path,
    session_id: str,
    *,
    collect_events: bool = False,
    subscriber: Optional[Subscriber] = None,
    subscribers: Optional[list[Subscriber]] = None,
    host: Optional[SessionHost] = None,
) -> dict:
    event_subscribers = _merge_subscribers(subscriber=subscriber, subscribers=subscribers)
    runtime = restore_session(workspace, session_id, lifecycle_subscribers=event_subscribers, host=host)
    events = runtime.continue_()
    return _result_payload(runtime, events, collect_events=collect_events)


def enqueue_message(
    workspace: Path,
    session_id: str,
    text: str,
    *,
    delivery: str = "follow_up",
    lifecycle_subscribers: Optional[list[Subscriber]] = None,
    host: Optional[SessionHost] = None,
) -> dict:
    runtime = restore_session(workspace, session_id, lifecycle_subscribers=lifecycle_subscribers, host=host)
    item = runtime.enqueue_message(text, delivery=delivery)
    return {"session_id": runtime.session_id, "queued_message_id": item.id, "delivery": item.delivery, "queued_message_count": len(runtime.state.queued_messages)}


def list_sessions(workspace: Path, *, host: Optional[SessionHost] = None) -> list[dict]:
    return [entry.model_dump(mode="json") for entry in (host or _default_host(workspace)).list_sessions(workspace)]


def list_capabilities(
    workspace: Path,
    *,
    kind: Optional[str] = None,
    include_mcp: Optional[bool] = None,
) -> list[dict]:
    bootstrap = import_module("pp_agent.app.bootstrap")
    catalog = bootstrap.create_capability_catalog(workspace, include_mcp=include_mcp)
    return [entry.model_dump(mode="json") for entry in catalog.list(kind=kind)]


def get_capability(
    workspace: Path,
    *,
    kind: str,
    name: str,
    include_mcp: Optional[bool] = None,
) -> dict:
    bootstrap = import_module("pp_agent.app.bootstrap")
    catalog = bootstrap.create_capability_catalog(workspace, include_mcp=include_mcp)
    return catalog.get(kind, name).model_dump(mode="json")


def reload_capabilities(
    workspace: Path,
    *,
    kind: Optional[str] = None,
    include_mcp: Optional[bool] = None,
) -> list[dict]:
    bootstrap = import_module("pp_agent.app.bootstrap")
    catalog = bootstrap.create_capability_catalog(workspace, include_mcp=include_mcp)
    catalog.reload()
    return [entry.model_dump(mode="json") for entry in catalog.list(kind=kind)]


def legacy_hint_readiness(
    workspace: Path,
    *,
    include_mcp: Optional[bool] = None,
) -> dict:
    bootstrap = import_module("pp_agent.app.bootstrap")
    return bootstrap.inspect_legacy_hint_readiness(workspace, include_mcp=include_mcp)


def get_session_tree(
    workspace: Path,
    session_id: Optional[str] = None,
    *,
    sort_mode: str = "branch",
    lifecycle_subscribers: Optional[list[Subscriber]] = None,
    host: Optional[SessionHost] = None,
) -> dict:
    view = (host or _default_host(workspace)).get_tree(
        workspace,
        session_id=session_id,
        sort_mode=sort_mode,
        lifecycle_subscribers=lifecycle_subscribers,
    )
    return view.model_dump(mode="json")


def fork_session(
    workspace: Path,
    session_id: str,
    *,
    head_id: Optional[str] = None,
    lifecycle_subscribers: Optional[list[Subscriber]] = None,
    host: Optional[SessionHost] = None,
) -> dict:
    return (host or _default_host(workspace)).fork_session(
        workspace,
        session_id,
        head_id=head_id,
        lifecycle_subscribers=lifecycle_subscribers,
    ).model_dump(mode="json")


def rewind_session(
    workspace: Path,
    session_id: str,
    *,
    turn_count: Optional[int] = None,
    message_count: Optional[int] = None,
    lifecycle_subscribers: Optional[list[Subscriber]] = None,
    host: Optional[SessionHost] = None,
) -> dict:
    return (host or _default_host(workspace)).rewind_session(
        workspace,
        session_id,
        turn_count=turn_count,
        message_count=message_count,
        lifecycle_subscribers=lifecycle_subscribers,
    ).model_dump(mode="json")


def create_checkpoint(
    workspace: Path,
    session_id: str,
    *,
    head_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    reason: str = "manual",
    snapshot_type: str = "head_snapshot",
    lifecycle_subscribers: Optional[list[Subscriber]] = None,
    host: Optional[SessionHost] = None,
) -> dict:
    return (host or _default_host(workspace)).create_checkpoint(
        workspace,
        session_id=session_id,
        head_id=head_id,
        turn_id=turn_id,
        reason=reason,
        snapshot_type=snapshot_type,
        lifecycle_subscribers=lifecycle_subscribers,
    ).model_dump(mode="json")


def list_checkpoints(workspace: Path, *, session_id: Optional[str] = None, host: Optional[SessionHost] = None) -> list[dict]:
    return [item.model_dump(mode="json") for item in (host or _default_host(workspace)).list_checkpoints(workspace, session_id=session_id)]


def preview_rewind(
    workspace: Path,
    session_id: str,
    *,
    checkpoint_id: Optional[str] = None,
    turn_count: Optional[int] = None,
    message_count: Optional[int] = None,
    mode: str = "conversation_and_workspace",
    allow_stash_snapshot: bool = False,
    lifecycle_subscribers: Optional[list[Subscriber]] = None,
    host: Optional[SessionHost] = None,
) -> dict:
    return (host or _default_host(workspace)).preview_rewind(
        workspace,
        session_id,
        checkpoint_id=checkpoint_id,
        turn_count=turn_count,
        message_count=message_count,
        mode=mode,
        allow_stash_snapshot=allow_stash_snapshot,
        lifecycle_subscribers=lifecycle_subscribers,
    ).model_dump(mode="json")


def rewind_safe(
    workspace: Path,
    session_id: str,
    *,
    checkpoint_id: Optional[str] = None,
    turn_count: Optional[int] = None,
    message_count: Optional[int] = None,
    mode: str = "conversation_and_workspace",
    allow_stash_snapshot: bool = False,
    lifecycle_subscribers: Optional[list[Subscriber]] = None,
    host: Optional[SessionHost] = None,
) -> dict:
    return (host or _default_host(workspace)).rewind_safe(
        workspace,
        session_id,
        checkpoint_id=checkpoint_id,
        turn_count=turn_count,
        message_count=message_count,
        mode=mode,
        allow_stash_snapshot=allow_stash_snapshot,
        lifecycle_subscribers=lifecycle_subscribers,
    ).model_dump(mode="json")


def approvals_summary(workspace: Path, *, host: Optional[SessionHost] = None) -> dict:
    return (host or _default_host(workspace)).approvals_summary(workspace)


def subscribe(runtime: AgentRuntime, callback: Subscriber) -> AgentRuntime:
    runtime.subscribe(callback)
    return runtime


def chat(
    workspace: Path,
    *,
    session_id: Optional[str] = None,
    lifecycle_subscribers: Optional[list[Subscriber]] = None,
    host: Optional[SessionHost] = None,
) -> AgentRuntime:
    return create_runtime(workspace, session_id=session_id, lifecycle_subscribers=lifecycle_subscribers, host=host)


def _default_host(workspace: Path) -> SessionHost:
    bootstrap = import_module("pp_agent.app.bootstrap")
    return bootstrap.create_session_host(workspace)


def _merge_subscribers(*, subscriber: Optional[Subscriber], subscribers: Optional[list[Subscriber]]) -> list[Subscriber]:
    merged: list[Subscriber] = []
    if subscriber is not None:
        merged.append(subscriber)
    if subscribers:
        merged.extend(subscribers)
    return merged


def _assistant_preview(runtime: AgentRuntime, limit: int = 400) -> str:
    for message in reversed(runtime.state.messages):
        if message.role != "assistant":
            continue
        parts = [part.text.strip() for part in message.content if getattr(part, "text", "").strip()]
        text = " ".join(parts)
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."
    return ""


def _result_payload(runtime: AgentRuntime, events: list[AgentEvent], *, collect_events: bool) -> dict:
    payload = {
        "session_id": runtime.session_id,
        "assistant": _assistant_preview(runtime),
        "pending_plan_token": runtime.state.pending_plan_token,
        "event_count": len(events),
    }
    stats = {
        "pending_tool_call_count": len(runtime.state.pending_tool_calls),
        "queued_message_count": len(runtime.state.queued_messages),
    }
    if any(value for value in stats.values()):
        payload["stats"] = stats
    if collect_events:
        payload["events"] = [event.model_dump(mode="json") for event in events]
    return payload
