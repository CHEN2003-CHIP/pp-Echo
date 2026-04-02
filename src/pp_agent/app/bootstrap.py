from __future__ import annotations

from pathlib import Path
from typing import Optional

from pp_agent.extensions.hooks import LifecycleSubscriber
from pp_agent.llm.registry import create_llm_client
from pp_agent.llm.models import ModelConfig, ProviderConfig
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.runtime.session_host import SessionHost
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.storage.models import StoredModelConfig, StoredProviderConfig
from pp_agent.storage.sessions import SessionRecord, SessionStore
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
    return create_session_store(load_settings(workspace))


def timeline_store_for(workspace: Path) -> TimelineStore:
    settings = load_settings(workspace)
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
    return PendingActionStore(workspace.resolve() / ".pp-agent" / "pending-edits")


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


def create_runtime_from_record(
    workspace: Path,
    record: SessionRecord,
    lifecycle_subscribers: Optional[list[LifecycleSubscriber]] = None,
) -> AgentRuntime:
    settings = load_settings(workspace)
    agent = AgentRuntime(
        llm_client=create_llm_client(
            provider=provider_config_for_llm(settings.provider),
            model=model_config_for_llm(record.model),
        ),
        tool_registry=ToolRegistry(workspace, policy=settings.tool_policy),
        session_store=session_store_for(workspace),
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
    return agent


def session_defaults_for(workspace: Path) -> dict[str, object]:
    settings = load_settings(workspace)
    return {"system_prompt": settings.system_prompt, "model": settings.model.model_copy(deep=True)}


def create_session_host(workspace: Path) -> SessionHost:
    _ = workspace
    return SessionHost(
        runtime_factory=create_runtime_from_record,
        session_store_factory=session_store_for,
        pending_action_store_factory=pending_action_store_for,
        session_defaults_factory=session_defaults_for,
    )


def build_agent(
    workspace: Path,
    session_id: Optional[str] = None,
    lifecycle_subscribers: Optional[list[LifecycleSubscriber]] = None,
) -> AgentRuntime:
    host = create_session_host(workspace)
    if session_id:
        return host.restore_session(workspace, session_id, lifecycle_subscribers=lifecycle_subscribers)
    return host.create_session(workspace, lifecycle_subscribers=lifecycle_subscribers)


def switch_session_head(workspace: Path, session_id: str, head_id: Optional[str], subscribers: Optional[list[LifecycleSubscriber]] = None) -> str:
    host = create_session_host(workspace)
    runtime = host.switch_session(workspace, session_id, session_id, target_head_id=head_id, lifecycle_subscribers=subscribers)
    return runtime.session_id


def fork_session(workspace: Path, source_session_id: str, source_turn_id: Optional[str] = None, subscribers: Optional[list[LifecycleSubscriber]] = None) -> str:
    host = create_session_host(workspace)
    result = host.fork_session(workspace, source_session_id, head_id=source_turn_id, lifecycle_subscribers=subscribers)
    return result.session_id


def view_session_tree(workspace: Path, session_id: Optional[str] = None, subscribers: Optional[list[LifecycleSubscriber]] = None) -> None:
    create_session_host(workspace).get_tree(workspace, session_id=session_id, lifecycle_subscribers=subscribers)


def rewind_session_with_events(
    workspace: Path,
    source_session_id: str,
    *,
    message_count: Optional[int] = None,
    turn_count: Optional[int] = None,
    subscribers: Optional[list[LifecycleSubscriber]] = None,
) -> str:
    result = create_session_host(workspace).rewind_session(
        workspace,
        source_session_id,
        message_count=message_count,
        turn_count=turn_count,
        lifecycle_subscribers=subscribers,
    )
    return result.session_id
