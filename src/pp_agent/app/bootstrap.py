from __future__ import annotations

from pathlib import Path
from typing import Optional

from pp_agent.llm.registry import create_llm_client
from pp_agent.runtime.runtime import AgentRuntime
from pp_agent.storage.approvals import PendingActionStore
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


def build_agent(workspace: Path, session_id: Optional[str] = None) -> AgentRuntime:
    settings = load_settings(workspace)
    session_store = create_session_store(settings)
    record = session_store.load(session_id) if session_id else session_store.create(settings.system_prompt, settings.model)
    agent = AgentRuntime(
        llm_client=create_llm_client(provider=settings.provider, model=record.model),
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
    agent.restore_session_record(record)
    return agent
