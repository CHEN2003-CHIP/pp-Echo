from __future__ import annotations

from pathlib import Path
from typing import Optional

from pp_agent.extensions.hooks import LifecycleSubscriber
from pp_agent.llm.registry import create_llm_client
from pp_agent.llm.models import ModelConfig, ProviderConfig
from pp_agent.runtime.lifecycle import (
    SESSION_BEFORE_FORK,
    SESSION_BEFORE_SWITCH,
    SESSION_BEFORE_TREE,
    SESSION_FORKED,
    SESSION_REWOUND,
    SESSION_START,
    SESSION_TREE_NAVIGATED,
    SESSION_TREE_VIEWED,
)
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.runtime.state import AgentEvent
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.storage.models import StoredModelConfig, StoredProviderConfig
from pp_agent.storage.sessions import SessionStore
from pp_agent.storage.settings import Settings
from pp_agent.storage.timeline import TimelineStore
from pp_agent.tools.registry import ToolRegistry


def load_settings(workspace: Path) -> Settings:
    return Settings.load(workspace)


def create_session_store(settings: Settings) -> SessionStore:
    candidates = [settings.global_dir / "sessions", settings.project_dir / "global" / "sessions"]
    last_error: Optional[Exception] = None
    for candidate in candidates:
        try:
            return SessionStore(candidate)
        except PermissionError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise PermissionError("Unable to create a writable session tree store")


def session_store_for(workspace: Path) -> SessionStore:
    settings = Settings.load(workspace)
    return create_session_store(settings)


def timeline_store_for(workspace: Path) -> TimelineStore:
    settings = Settings.load(workspace)
    candidates = [settings.global_dir / "timelines", settings.project_dir / "global" / "timelines"]
    last_error: Optional[Exception] = None
    for candidate in candidates:
        try:
            return TimelineStore(candidate)
        except PermissionError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise PermissionError("Unable to create a writable timeline store")


def pending_action_store_for(workspace: Path) -> PendingActionStore:
    return PendingActionStore((workspace.resolve() / ".pp-agent" / "pending-edits"))


def create_tool_registry(workspace: Path) -> ToolRegistry:
    settings = load_settings(workspace)
    return ToolRegistry(workspace, policy=settings.tool_policy)


def provider_config_for_llm(config: StoredProviderConfig) -> ProviderConfig:
    return ProviderConfig(**config.model_dump(mode="python"))


def model_config_for_llm(config: StoredModelConfig) -> ModelConfig:
    return ModelConfig(**config.model_dump(mode="python"))


def confirm_tool_call(tool_name: str, args: dict) -> bool:
    try:
        import typer
    except ImportError:  # pragma: no cover
        typer = None
    preview = ", ".join(f"{key}={value!r}" for key, value in args.items())
    if typer:
        return typer.confirm(f"Allow tool `{tool_name}` with args: {preview}?", default=False)
    answer = input(f"Allow tool {tool_name} with args: {preview}? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def build_agent(
    workspace: Path,
    session_id: Optional[str] = None,
    lifecycle_subscribers: Optional[list[LifecycleSubscriber]] = None,
) -> AgentRuntime:
    settings = load_settings(workspace)
    session_store = create_session_store(settings)
    is_new_session = session_id is None
    record = session_store.load(session_id) if session_id else session_store.create(settings.system_prompt, settings.model)
    agent = AgentRuntime(
        llm_client=create_llm_client(
            provider=provider_config_for_llm(settings.provider),
            model=model_config_for_llm(record.model),
        ),
        tool_registry=ToolRegistry(workspace, policy=settings.tool_policy),
        session_store=session_store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=confirm_tool_call,
        initial_compaction=record.compaction,
        initial_pending_tool_calls=record.pending_tool_calls,
        initial_pending_plan_token=record.pending_plan_token,
        initial_queued_messages=record.queued_messages,
        require_plan_approval=settings.tool_policy.confirm_high_risk_plan,
        timeline_store=timeline_store_for(workspace),
    )
    for subscriber in lifecycle_subscribers or []:
        agent.subscribe(subscriber)
    if is_new_session:
        agent._queue_lifecycle_event(agent._event(SESSION_START, details={"new_session": True}))
    agent.restore_session_record(record)
    return agent


def _emit_bootstrap_event(
    event_type: str,
    *,
    session_id: str,
    subscribers: Optional[list[LifecycleSubscriber]] = None,
    details: Optional[dict[str, object]] = None,
) -> AgentEvent:
    event = AgentEvent(type=event_type, session_id=session_id, details=details or {})
    for subscriber in subscribers or []:
        subscriber(event)
    return event


def switch_session_head(workspace: Path, session_id: str, head_id: Optional[str], subscribers: Optional[list[LifecycleSubscriber]] = None) -> str:
    _emit_bootstrap_event(SESSION_BEFORE_SWITCH, session_id=session_id, subscribers=subscribers, details={"target_head_id": head_id})
    store = session_store_for(workspace)
    before = store.load(session_id).active_head_id
    if head_id is not None:
        store.set_active_head(session_id, head_id)
    after = store.load(session_id).active_head_id
    if before != after:
        _emit_bootstrap_event(SESSION_TREE_NAVIGATED, session_id=session_id, subscribers=subscribers, details={"from_head_id": before, "to_head_id": after})
    return session_id


def fork_session(workspace: Path, source_session_id: str, source_turn_id: Optional[str] = None, subscribers: Optional[list[LifecycleSubscriber]] = None) -> str:
    _emit_bootstrap_event(SESSION_BEFORE_FORK, session_id=source_session_id, subscribers=subscribers, details={"source_head_id": source_turn_id})
    store = session_store_for(workspace)
    forked = store.fork_from_head(source_session_id, source_turn_id) if source_turn_id is not None else store.fork(source_session_id)
    store.save(forked)
    _emit_bootstrap_event(SESSION_FORKED, session_id=forked.id, subscribers=subscribers, details={"source_session_id": source_session_id, "target_session_id": forked.id, "source_head_id": source_turn_id})
    return forked.id


def view_session_tree(workspace: Path, session_id: Optional[str] = None, subscribers: Optional[list[LifecycleSubscriber]] = None) -> None:
    _emit_bootstrap_event(SESSION_BEFORE_TREE, session_id=session_id or "", subscribers=subscribers, details={"view": "tree"})
    _emit_bootstrap_event(SESSION_TREE_VIEWED, session_id=session_id or "", subscribers=subscribers, details={"view": "tree"})


def rewind_session_with_events(
    workspace: Path,
    source_session_id: str,
    *,
    message_count: Optional[int] = None,
    turn_count: Optional[int] = None,
    subscribers: Optional[list[LifecycleSubscriber]] = None,
) -> str:
    store = session_store_for(workspace)
    rewound = store.rewind(source_session_id, message_count) if message_count is not None else store.rewind_turns(source_session_id, turn_count or 0)
    store.save(rewound)
    _emit_bootstrap_event(
        SESSION_REWOUND,
        session_id=rewound.id,
        subscribers=subscribers,
        details={"source_session_id": source_session_id, "target_session_id": rewound.id, "message_count": message_count, "turn_count": turn_count},
    )
    return rewound.id
