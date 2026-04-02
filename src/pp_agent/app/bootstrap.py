from __future__ import annotations

from pathlib import Path
from typing import Optional

from pp_agent.extensions.hooks import LifecycleSubscriber
from pp_agent.llm.models import ModelConfig, ProviderConfig
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.runtime.session_host import (
    SessionHost,
    confirm_tool_call,
    create_default_session_host,
    create_runtime_from_record,
)
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


def build_agent(
    workspace: Path,
    session_id: Optional[str] = None,
    lifecycle_subscribers: Optional[list[LifecycleSubscriber]] = None,
) -> AgentRuntime:
    host = create_session_host(workspace)
    if session_id:
        return host.restore_session(workspace, session_id, lifecycle_subscribers=lifecycle_subscribers)
    return host.create_session(workspace, lifecycle_subscribers=lifecycle_subscribers)


def create_session_host(workspace: Path) -> SessionHost:
    _ = workspace
    return create_default_session_host()


def switch_session_head(workspace: Path, session_id: str, head_id: Optional[str], subscribers: Optional[list[LifecycleSubscriber]] = None) -> str:
    host = create_session_host(workspace)
    runtime = host.switch_session(workspace, session_id, session_id, target_head_id=head_id, lifecycle_subscribers=subscribers)
    return runtime.session_id


def fork_session(workspace: Path, source_session_id: str, source_turn_id: Optional[str] = None, subscribers: Optional[list[LifecycleSubscriber]] = None) -> str:
    host = create_session_host(workspace)
    result = host.fork_session(workspace, source_session_id, head_id=source_turn_id, lifecycle_subscribers=subscribers)
    return result.session_id


def view_session_tree(workspace: Path, session_id: Optional[str] = None, subscribers: Optional[list[LifecycleSubscriber]] = None) -> None:
    host = create_session_host(workspace)
    host.get_tree(workspace, session_id=session_id, lifecycle_subscribers=subscribers)


def rewind_session_with_events(
    workspace: Path,
    source_session_id: str,
    *,
    message_count: Optional[int] = None,
    turn_count: Optional[int] = None,
    subscribers: Optional[list[LifecycleSubscriber]] = None,
) -> str:
    host = create_session_host(workspace)
    result = host.rewind_session(
        workspace,
        source_session_id,
        message_count=message_count,
        turn_count=turn_count,
        lifecycle_subscribers=subscribers,
    )
    return result.session_id
