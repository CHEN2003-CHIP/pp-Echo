from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

try:
    import typer
except ImportError:  # pragma: no cover
    typer = None

try:
    from prompt_toolkit import PromptSession
except ImportError:  # pragma: no cover
    PromptSession = None

try:
    from rich.console import Console
except ImportError:  # pragma: no cover
    import sys

    class Console:  # type: ignore[override]
        def print(self, *args, end="\n", **kwargs):
            text = " ".join(str(arg) for arg in args)
            encoding = sys.stdout.encoding or "utf-8"
            safe = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
            print(safe, end=end)

from agent_core.llm.client import LLMClient
from agent_core.runtime.session import AgentSession
from agent_core.runtime.types import AgentEvent
from storage.settings import Settings
from storage.sessions import SessionStore
from tools.pending_actions import PendingActionStore
from tools.registry import ToolRegistry

console = Console()
app = typer.Typer(help="Personal Python coding agent for Windows 10.") if typer else None


def build_agent(workspace: Path, session_id: Optional[str] = None) -> AgentSession:
    settings = Settings.load(workspace)
    session_store = SessionStore(settings.global_dir / "sessions")
    record = session_store.load(session_id) if session_id else session_store.create(settings.system_prompt, settings.model)
    agent = AgentSession(
        llm_client=LLMClient(provider=settings.provider, model=record.model),
        tool_registry=ToolRegistry(workspace, policy=settings.tool_policy),
        session_store=session_store,
        session_id=record.id,
        system_prompt=record.system_prompt,
        confirm_callback=confirm_tool_call,
        initial_compaction=record.compaction,
    )
    agent.state.messages = list(record.messages)
    return agent


def session_store_for(workspace: Path) -> SessionStore:
    settings = Settings.load(workspace)
    return SessionStore(settings.global_dir / "sessions")


def pending_action_store_for(workspace: Path) -> PendingActionStore:
    return PendingActionStore((workspace.resolve() / ".pp-agent" / "pending-edits"))


def confirm_tool_call(tool_name: str, args: dict) -> bool:
    preview = ", ".join(f"{key}={value!r}" for key, value in args.items())
    if typer:
        return typer.confirm(f"Allow tool `{tool_name}` with args: {preview}?", default=False)
    answer = input(f"Allow tool {tool_name} with args: {preview}? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def render_event(event: AgentEvent) -> None:
    if event.type == "message_delta" and event.delta:
        console.print(event.delta, end="")
    elif event.type == "tool_start":
        console.print(f"\ntool start {event.tool_name} {event.tool_args}")
    elif event.type == "tool_end":
        label = "tool error" if event.is_error else "tool end"
        console.print(f"{label} {event.tool_name}: {event.message}")
    elif event.type == "compaction":
        console.print(f"context compacted: {event.details}")
    elif event.type == "error":
        console.print(f"error: {event.message}")


def render_settings(agent: AgentSession, workspace: Path) -> None:
    settings = Settings.load(workspace)
    payload = {
        "workspace": str(settings.workspace),
        "session_id": agent.session_id,
        "base_url": agent.llm_client.provider.base_url,
        "model": agent.llm_client.model.model,
        "enable_thinking": agent.llm_client.model.enable_thinking,
        "shell_timeout_seconds": settings.tool_policy.shell_timeout_seconds,
        "summary_length": len(agent.state.compaction.summary),
        "summarized_message_count": agent.state.compaction.summarized_message_count,
    }
    console.print(json.dumps(payload, ensure_ascii=False, indent=2))


def approvals_summary_payload(workspace: Path) -> dict:
    items = pending_action_store_for(workspace).list()
    by_type: dict[str, int] = {}
    for item in items:
        by_type[item["action_type"]] = by_type.get(item["action_type"], 0) + 1
    return {"count": len(items), "by_type": by_type, "tokens": [item["token"] for item in items]}


def handle_command(agent: AgentSession, raw: str, workspace: Path) -> str:
    if raw == "/quit":
        return "quit"
    if raw == "/new":
        return "new"
    if raw == "/session":
        console.print(f"session: {agent.session_id}")
        return "handled"
    if raw == "/settings":
        render_settings(agent, workspace)
        return "handled"
    if raw == "/approvals":
        console.print(json.dumps(approvals_summary_payload(workspace), ensure_ascii=False, indent=2))
        return "handled"
    if raw.startswith("/model "):
        agent.llm_client.model.model = raw.split(" ", 1)[1].strip()
        agent.state.model.model = agent.llm_client.model.model
        console.print(f"model set to {agent.llm_client.model.model}")
        return "handled"
    if raw.startswith("/resume "):
        return raw.split(" ", 1)[1].strip()
    return "run"


def chat_main(workspace: Path, session_id: Optional[str] = None) -> None:
    prompt_session = PromptSession() if PromptSession else None
    while True:
        agent = build_agent(workspace, session_id=session_id)
        agent.subscribe(render_event)
        console.print(f"pp-agent session={agent.session_id} model={agent.llm_client.model.model}")
        while True:
            raw = prompt_session.prompt("\n> ").strip() if prompt_session else input("\n> ").strip()
            if not raw:
                continue
            if raw.startswith("/"):
                result = handle_command(agent, raw, workspace)
                if result == "handled":
                    continue
                if result == "quit":
                    return
                if result == "new":
                    session_id = None
                    break
                if result != "run":
                    session_id = result
                    break
            agent.prompt(raw)
            console.print()


def run_main(prompt: str, workspace: Path, session_id: Optional[str] = None) -> None:
    agent = build_agent(workspace, session_id=session_id)
    agent.subscribe(render_event)
    agent.prompt(prompt)
    console.print()


def sessions_list_main(workspace: Path) -> None:
    store = session_store_for(workspace)
    payload = [{"id": session.id, "parent_id": session.parent_id, "model": session.model.model, "updated_at": session.updated_at, "summarized_message_count": session.compaction.summarized_message_count} for session in store.list()]
    console.print(json.dumps(payload, ensure_ascii=False, indent=2))


def sessions_fork_main(workspace: Path, session_id: str) -> None:
    store = session_store_for(workspace)
    forked = store.fork(session_id)
    store.save(forked)
    console.print(f"forked session: {forked.id} parent={forked.parent_id}")


def approvals_list_main(workspace: Path) -> None:
    store = pending_action_store_for(workspace)
    console.print(json.dumps(store.list(), ensure_ascii=False, indent=2))


def approvals_summary_main(workspace: Path) -> None:
    console.print(json.dumps(approvals_summary_payload(workspace), ensure_ascii=False, indent=2))


def approvals_show_main(workspace: Path, token: str) -> None:
    registry = ToolRegistry(workspace, policy=Settings.load(workspace).tool_policy)
    result = registry.execute("preview_pending_action", {"token": token})
    console.print(result.content)
    console.print(json.dumps(result.details, ensure_ascii=False, indent=2))


def approvals_approve_main(workspace: Path, token: str) -> None:
    registry = ToolRegistry(workspace, policy=Settings.load(workspace).tool_policy)
    result = registry.execute("approve_pending_action", {"token": token})
    console.print(result.content)
    if result.details:
        console.print(json.dumps(result.details, ensure_ascii=False, indent=2))


def approvals_reject_main(workspace: Path, token: str) -> None:
    registry = ToolRegistry(workspace, policy=Settings.load(workspace).tool_policy)
    result = registry.execute("reject_pending_action", {"token": token})
    console.print(result.content)


def approvals_approve_all_main(workspace: Path) -> None:
    store = pending_action_store_for(workspace)
    tokens = [item["token"] for item in store.list()]
    registry = ToolRegistry(workspace, policy=Settings.load(workspace).tool_policy)
    results = []
    for token in tokens:
        results.append(registry.execute("approve_pending_action", {"token": token}).content)
    console.print(json.dumps(results, ensure_ascii=False, indent=2))


def approvals_reject_all_main(workspace: Path) -> None:
    store = pending_action_store_for(workspace)
    tokens = [item["token"] for item in store.list()]
    registry = ToolRegistry(workspace, policy=Settings.load(workspace).tool_policy)
    results = []
    for token in tokens:
        results.append(registry.execute("reject_pending_action", {"token": token}).content)
    console.print(json.dumps(results, ensure_ascii=False, indent=2))


def workflow_repo_main(workspace: Path, query: Optional[str] = None, token: Optional[str] = None, auto_apply: bool = False) -> None:
    registry = ToolRegistry(workspace, policy=Settings.load(workspace).tool_policy)
    payload = {"steps": []}
    if query:
        grep = registry.execute("grep_code", {"query": query})
        payload["steps"].append({"step": "grep_code", "content": grep.content, "details": grep.details})
    summary = approvals_summary_payload(workspace)
    payload["steps"].append({"step": "approvals_summary", "details": summary})
    if token:
        preview = registry.execute("preview_pending_action", {"token": token})
        payload["steps"].append({"step": "preview_pending_action", "content": preview.content, "details": preview.details})
        if auto_apply:
            applied = registry.execute("approve_pending_action", {"token": token})
            payload["steps"].append({"step": "approve_pending_action", "content": applied.content, "details": applied.details})
    status = registry.execute("git_status", {})
    diff = registry.execute("git_diff_worktree", {})
    payload["steps"].append({"step": "git_status", "content": status.content, "details": status.details})
    payload["steps"].append({"step": "git_diff_worktree", "content": diff.content, "details": diff.details})
    console.print(json.dumps(payload, ensure_ascii=False, indent=2))


def config_show_main(workspace: Path) -> None:
    settings = Settings.load(workspace)
    payload = {
        "workspace": str(settings.workspace),
        "global_dir": str(settings.global_dir),
        "project_dir": str(settings.project_dir),
        "base_url": settings.provider.base_url,
        "model": settings.model.model,
        "enable_thinking": settings.model.enable_thinking,
        "shell_timeout_seconds": settings.tool_policy.shell_timeout_seconds,
        "tool_confirmation": {
            "write_file": settings.tool_policy.confirm_write_file,
            "edit_file": settings.tool_policy.confirm_edit_file,
            "run_shell": settings.tool_policy.confirm_run_shell,
        },
    }
    console.print(json.dumps(payload, ensure_ascii=False, indent=2))


if app:
    @app.command()
    def chat(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"), session_id: Optional[str] = typer.Option(None, "--session")) -> None:
        chat_main(workspace, session_id)


    @app.command()
    def run(prompt: str = typer.Argument(..., help="Prompt to send to the agent."), workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"), session_id: Optional[str] = typer.Option(None, "--session")) -> None:
        run_main(prompt, workspace, session_id)


    sessions_app = typer.Typer(help="Manage stored sessions.")
    approvals_app = typer.Typer(help="Manage staged approvals.")
    workflow_app = typer.Typer(help="Guided repo-aware workflows.")
    config_app = typer.Typer(help="Show active configuration.")
    app.add_typer(sessions_app, name="sessions")
    app.add_typer(approvals_app, name="approvals")
    app.add_typer(workflow_app, name="workflow")
    app.add_typer(config_app, name="config")

    @sessions_app.command("list")
    def sessions_list(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        sessions_list_main(workspace)


    @sessions_app.command("fork")
    def sessions_fork(session_id: str, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        sessions_fork_main(workspace, session_id)


    @approvals_app.command("list")
    def approvals_list(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        approvals_list_main(workspace)


    @approvals_app.command("summary")
    def approvals_summary(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        approvals_summary_main(workspace)


    @approvals_app.command("show")
    def approvals_show(token: str, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        approvals_show_main(workspace, token)


    @approvals_app.command("approve")
    def approvals_approve(token: str, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        approvals_approve_main(workspace, token)


    @approvals_app.command("reject")
    def approvals_reject(token: str, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        approvals_reject_main(workspace, token)


    @approvals_app.command("approve-all")
    def approvals_approve_all(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        approvals_approve_all_main(workspace)


    @approvals_app.command("reject-all")
    def approvals_reject_all(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        approvals_reject_all_main(workspace)


    @workflow_app.command("repo")
    def workflow_repo(query: Optional[str] = typer.Option(None, "--query"), token: Optional[str] = typer.Option(None, "--token"), auto_apply: bool = typer.Option(False, "--auto-apply"), workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        workflow_repo_main(workspace, query=query, token=token, auto_apply=auto_apply)


    @config_app.command("show")
    def config_show(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        config_show_main(workspace)


def main() -> None:
    if app and typer:
        app()
        return

    parser = argparse.ArgumentParser(description="Personal Python coding agent for Windows 10.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    chat_parser = subparsers.add_parser("chat")
    chat_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    chat_parser.add_argument("--session", default=None)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("prompt")
    run_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    run_parser.add_argument("--session", default=None)
    sessions_parser = subparsers.add_parser("sessions")
    sessions_subparsers = sessions_parser.add_subparsers(dest="sessions_command", required=True)
    sessions_list_parser = sessions_subparsers.add_parser("list")
    sessions_list_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    sessions_fork_parser = sessions_subparsers.add_parser("fork")
    sessions_fork_parser.add_argument("session_id")
    sessions_fork_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    approvals_parser = subparsers.add_parser("approvals")
    approvals_subparsers = approvals_parser.add_subparsers(dest="approvals_command", required=True)
    for name in ["list", "summary", "approve-all", "reject-all"]:
        p = approvals_subparsers.add_parser(name)
        p.add_argument("--workspace", "-w", default=str(Path.cwd()))
    approvals_show_parser = approvals_subparsers.add_parser("show")
    approvals_show_parser.add_argument("token")
    approvals_show_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    approvals_approve_parser = approvals_subparsers.add_parser("approve")
    approvals_approve_parser.add_argument("token")
    approvals_approve_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    approvals_reject_parser = approvals_subparsers.add_parser("reject")
    approvals_reject_parser.add_argument("token")
    approvals_reject_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    workflow_parser = subparsers.add_parser("workflow")
    workflow_subparsers = workflow_parser.add_subparsers(dest="workflow_command", required=True)
    workflow_repo_parser = workflow_subparsers.add_parser("repo")
    workflow_repo_parser.add_argument("--query", default=None)
    workflow_repo_parser.add_argument("--token", default=None)
    workflow_repo_parser.add_argument("--auto-apply", action="store_true")
    workflow_repo_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    config_parser = subparsers.add_parser("config")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)
    config_show_parser = config_subparsers.add_parser("show")
    config_show_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))

    args = parser.parse_args()
    command = getattr(args, "command")
    if command == "chat":
        chat_main(Path(args.workspace), args.session)
    elif command == "run":
        run_main(args.prompt, Path(args.workspace), args.session)
    elif command == "sessions" and args.sessions_command == "list":
        sessions_list_main(Path(args.workspace))
    elif command == "sessions" and args.sessions_command == "fork":
        sessions_fork_main(Path(args.workspace), args.session_id)
    elif command == "approvals" and args.approvals_command == "list":
        approvals_list_main(Path(args.workspace))
    elif command == "approvals" and args.approvals_command == "summary":
        approvals_summary_main(Path(args.workspace))
    elif command == "approvals" and args.approvals_command == "show":
        approvals_show_main(Path(args.workspace), args.token)
    elif command == "approvals" and args.approvals_command == "approve":
        approvals_approve_main(Path(args.workspace), args.token)
    elif command == "approvals" and args.approvals_command == "reject":
        approvals_reject_main(Path(args.workspace), args.token)
    elif command == "approvals" and args.approvals_command == "approve-all":
        approvals_approve_all_main(Path(args.workspace))
    elif command == "approvals" and args.approvals_command == "reject-all":
        approvals_reject_all_main(Path(args.workspace))
    elif command == "workflow" and args.workflow_command == "repo":
        workflow_repo_main(Path(args.workspace), query=args.query, token=args.token, auto_apply=args.auto_apply)
    elif command == "config" and args.config_command == "show":
        config_show_main(Path(args.workspace))


if __name__ == "__main__":
    main()