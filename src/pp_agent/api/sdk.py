from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Optional

from pp_agent.runtime import AgentEvent, AgentRuntime, SessionHost
from pp_agent.runtime.session_host import create_default_session_host

Subscriber = Callable[[AgentEvent], None]


def create_runtime(
    workspace: Path,
    *,
    session_id: Optional[str] = None,
    lifecycle_subscribers: Optional[list[Subscriber]] = None,
    host: Optional[SessionHost] = None,
) -> AgentRuntime:
    session_host = host or create_default_session_host()
    if session_id:
        return session_host.restore_session(workspace, session_id, lifecycle_subscribers=lifecycle_subscribers)
    return session_host.create_session(workspace, lifecycle_subscribers=lifecycle_subscribers)


def create_session(workspace: Path, *, lifecycle_subscribers: Optional[list[Subscriber]] = None, host: Optional[SessionHost] = None) -> AgentRuntime:
    return (host or create_default_session_host()).create_session(workspace, lifecycle_subscribers=lifecycle_subscribers)


def restore_session(
    workspace: Path,
    session_id: str,
    *,
    lifecycle_subscribers: Optional[list[Subscriber]] = None,
    host: Optional[SessionHost] = None,
) -> AgentRuntime:
    return (host or create_default_session_host()).restore_session(workspace, session_id, lifecycle_subscribers=lifecycle_subscribers)


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
    return [entry.model_dump(mode="json") for entry in (host or create_default_session_host()).list_sessions(workspace)]


def get_session_tree(
    workspace: Path,
    session_id: Optional[str] = None,
    *,
    sort_mode: str = "branch",
    lifecycle_subscribers: Optional[list[Subscriber]] = None,
    host: Optional[SessionHost] = None,
) -> dict:
    view = (host or create_default_session_host()).get_tree(
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
    return (host or create_default_session_host()).fork_session(
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
    return (host or create_default_session_host()).rewind_session(
        workspace,
        session_id,
        turn_count=turn_count,
        message_count=message_count,
        lifecycle_subscribers=lifecycle_subscribers,
    ).model_dump(mode="json")


def approvals_summary(workspace: Path, *, host: Optional[SessionHost] = None) -> dict:
    return (host or create_default_session_host()).approvals_summary(workspace)


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
        "pending_tool_call_count": len(runtime.state.pending_tool_calls),
        "queued_message_count": len(runtime.state.queued_messages),
        "event_count": len(events),
    }
    if collect_events:
        payload["events"] = [event.model_dump(mode="json") for event in events]
    return payload
