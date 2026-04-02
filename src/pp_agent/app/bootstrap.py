from __future__ import annotations

from pathlib import Path
from typing import Optional

from pp_agent.capabilities import (
    BuiltinToolCapabilityDiscoveryProvider,
    CapabilityCatalog,
    MCPCapabilityDiscoveryProvider,
    SkillCapabilityDiscoveryProvider,
)
from pp_agent.domain.checkpoints import CheckpointEntry
from pp_agent.extensions.hooks import LifecycleSubscriber
from pp_agent.llm.models import ModelConfig, ProviderConfig
from pp_agent.mcp import MCPManager
from pp_agent.llm.registry import create_llm_client
from pp_agent.runtime.git_checkpoint import GitCheckpointManager
from pp_agent.runtime.hooks import BeforeToolCallDecision
from pp_agent.runtime.lifecycle import CHECKPOINT_BEFORE_CREATE, CHECKPOINT_CREATED
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.runtime.session_host import SessionHost
from pp_agent.storage.approvals import PendingActionStore
from pp_agent.storage.checkpoints import CheckpointStore
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


def checkpoint_store_for(workspace: Path) -> CheckpointStore:
    settings = load_settings(workspace)
    candidates = [settings.global_dir / "checkpoints", settings.project_dir / "global" / "checkpoints"]
    last_error: Optional[Exception] = None
    for candidate in candidates:
        try:
            return CheckpointStore(candidate)
        except PermissionError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise PermissionError("Unable to create a writable checkpoint store")


def create_tool_registry(workspace: Path) -> ToolRegistry:
    settings = load_settings(workspace)
    return ToolRegistry(workspace, policy=settings.tool_policy)


def create_capability_catalog(workspace: Path) -> CapabilityCatalog:
    settings = load_settings(workspace)
    registry = ToolRegistry(workspace, policy=settings.tool_policy)
    providers = [
        SkillCapabilityDiscoveryProvider(workspace=workspace.resolve(), user_root=settings.global_dir),
        BuiltinToolCapabilityDiscoveryProvider(registry=registry),
    ]
    return CapabilityCatalog(providers)


def create_capability_catalog_with_mcp(
    workspace: Path,
    *,
    transport_factory=None,
    time_fn=None,
) -> CapabilityCatalog:
    settings = load_settings(workspace)
    registry = ToolRegistry(workspace, policy=settings.tool_policy)
    manager = create_mcp_manager(workspace, transport_factory=transport_factory, time_fn=time_fn)
    providers = [
        SkillCapabilityDiscoveryProvider(workspace=workspace.resolve(), user_root=settings.global_dir),
        BuiltinToolCapabilityDiscoveryProvider(registry=registry),
        MCPCapabilityDiscoveryProvider(manager=manager),
    ]
    return CapabilityCatalog(providers)


def create_mcp_manager(
    workspace: Path,
    *,
    transport_factory=None,
    time_fn=None,
) -> MCPManager:
    return MCPManager.from_workspace(workspace, transport_factory=transport_factory, time_fn=time_fn)


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
    session_store = session_store_for(workspace)
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
    _install_auto_checkpoint_hook(
        agent=agent,
        workspace=workspace,
        manager=GitCheckpointManager(workspace, checkpoint_store_for(workspace), session_store),
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
        checkpoint_store_factory=checkpoint_store_for,
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


def _install_auto_checkpoint_hook(*, agent: AgentRuntime, workspace: Path, manager: GitCheckpointManager) -> None:
    def before_tool_call(state, call, _registry):
        if not _should_auto_checkpoint(workspace, call.name, call.arguments):
            return BeforeToolCallDecision(action="allow")
        if not manager.is_git_repository():
            return BeforeToolCallDecision(action="allow")
        turn_key = f"turn-{state.turn.turn_id}"
        if getattr(agent, "_auto_checkpoint_turn_key", None) == turn_key:
            return BeforeToolCallDecision(action="allow")
        head_id, turn_id = manager.current_head_context(agent.session_id)
        list(
            agent._emit(
                agent._event(
                    CHECKPOINT_BEFORE_CREATE,
                    details={
                        "checkpoint_id": None,
                        "snapshot_type": "head_snapshot",
                        "session_id": agent.session_id,
                        "head_id": head_id,
                        "turn_id": turn_id,
                        "reason": f"auto:{call.name}",
                        "has_dirty_workspace": False,
                        "affected_file_count": 0,
                    },
                )
            )
        )
        entry = manager.create_head_snapshot(
            session_id=agent.session_id,
            head_id=head_id,
            turn_id=turn_id,
            reason=f"auto:{call.name}",
            summary=f"Automatic checkpoint before {call.name}",
        )
        setattr(agent, "_auto_checkpoint_turn_key", turn_key)
        list(agent._emit(agent._event(CHECKPOINT_CREATED, details=_checkpoint_event_details(entry))))
        return BeforeToolCallDecision(action="allow", details={"checkpoint_id": entry.checkpoint_id})

    agent.runtime_hooks.before_tool_call_hooks.insert(0, before_tool_call)


def _should_auto_checkpoint(workspace: Path, tool_name: str, arguments: dict) -> bool:
    if tool_name in {"write_file", "edit_file"}:
        return bool(arguments.get("apply"))
    if tool_name == "run_shell":
        return bool(arguments.get("apply"))
    if tool_name != "approve_pending_action":
        return False
    token = arguments.get("token")
    if not token:
        return False
    try:
        payload = pending_action_store_for(workspace).load(token)
    except FileNotFoundError:
        return False
    return payload["action_type"] in {"write_file", "edit_file", "run_shell"}


def _checkpoint_event_details(entry: CheckpointEntry) -> dict[str, object]:
    return {
        "checkpoint_id": entry.checkpoint_id,
        "snapshot_type": entry.snapshot_type,
        "session_id": entry.session_id,
        "head_id": entry.head_id,
        "turn_id": entry.turn_id,
        "reason": entry.reason,
        "has_dirty_workspace": entry.file_stats.has_dirty_workspace,
        "affected_file_count": entry.file_stats.changed_file_count,
    }


