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
from agent_core.runtime.types import AgentEvent, PlanStep
from storage.settings import Settings
from storage.sessions import SessionStore
from tools.pending_actions import PendingActionStore
from tools.registry import ToolRegistry

console = Console()
app = typer.Typer(help="Personal Python coding agent for Windows 10.") if typer else None

PLAN_MARKERS = {
    "pending": "[ ]",
    "awaiting_approval": "[?]",
    "in_progress": "[~]",
    "completed": "[x]",
    "failed": "[!]",
}


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
        initial_pending_tool_calls=record.pending_tool_calls,
        initial_pending_plan_token=record.pending_plan_token,
        require_plan_approval=settings.tool_policy.confirm_high_risk_plan,
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


def format_plan_step(step: PlanStep) -> str:
    tool_part = f" [{step.tool_name}]" if step.tool_name else ""
    marker = PLAN_MARKERS.get(step.status, "[-]")
    return f"{marker} {step.title}{tool_part}"


def load_pending_action(workspace: Path, token: str) -> dict:
    return pending_action_store_for(workspace).load(token)


def render_event(event: AgentEvent) -> None:
    if event.type == "message_delta" and event.delta:
        console.print(event.delta, end="")
    elif event.type == "planner_start":
        console.print("\n=== Planner ===")
        console.print("Planned steps:")
    elif event.type == "planner_step" and event.plan_step is not None:
        if event.plan_step.status == "pending":
            console.print(f"  {format_plan_step(event.plan_step)}")
        else:
            console.print(f"Planner update: {format_plan_step(event.plan_step)}")
    elif event.type == "planner_end":
        token = event.details.get("token")
        if event.details.get("requires_approval"):
            console.print(f"Planner paused. Approve with /approve {token} or reject with /reject {token}")
        else:
            console.print("=== Executor ===")
    elif event.type == "tool_start":
        console.print(f"Start {event.tool_name} {event.tool_args}")
    elif event.type == "tool_end":
        label = "error" if event.is_error else "done"
        console.print(f"{label.upper()} {event.tool_name}: {event.message}")
    elif event.type == "compaction":
        console.print(f"[Runtime] context compacted: {event.details}")
    elif event.type == "error":
        console.print(f"[Error] {event.message}")


def render_settings(agent: AgentSession, workspace: Path) -> None:
    settings = Settings.load(workspace)
    payload = {
        "workspace": str(settings.workspace),
        "session_id": agent.session_id,
        "base_url": agent.llm_client.provider.base_url,
        "model": agent.llm_client.model.model,
        "enable_thinking": agent.llm_client.model.enable_thinking,
        "shell_timeout_seconds": settings.tool_policy.shell_timeout_seconds,
        "confirm_high_risk_plan": settings.tool_policy.confirm_high_risk_plan,
        "pending_plan_token": agent.state.pending_plan_token,
        "pending_tool_call_count": len(agent.state.pending_tool_calls),
        "summary_length": len(agent.state.compaction.summary),
        "summarized_message_count": agent.state.compaction.summarized_message_count,
    }
    console.print(json.dumps(payload, ensure_ascii=False, indent=2))


def approvals_summary_payload(workspace: Path) -> dict:
    items = pending_action_store_for(workspace).list()
    by_type: dict[str, int] = {}
    for item in items:
        by_type[item["action_type"]] = by_type.get(item["action_type"], 0) + 1
    return {"count": len(items), "by_type": by_type, "tokens": [item["token"] for item in items], "items": items}


def short_token(token: str) -> str:
    return token[:8]


def compact_text(value: str, limit: int = 90) -> str:
    text = value.replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def action_target(item: dict) -> str:
    if item["action_type"] == "planner_approval":
        return f"session={item.get('details', {}).get('session_id', '')}"
    return item.get("target_path") or item.get("command") or ""


def approval_preview(item: dict, limit: int = 8) -> str:
    if item["action_type"] == "run_shell":
        return compact_text(item.get("command") or "")
    if item["action_type"] == "planner_approval":
        summary = item.get("details", {}).get("summary", []) or []
        return "\n".join(summary[:limit]) if summary else "Planner approval with no summary available."
    diff_text = item.get("details", {}).get("diff", "") or ""
    lines = [line for line in diff_text.splitlines() if line.strip()]
    return "\n".join(lines[:limit]) if lines else "No diff preview."


def render_approval_panel(workspace: Path) -> None:
    summary = approvals_summary_payload(workspace)
    items = summary["items"]
    lines = ["Approvals Queue", f"Total: {summary['count']}", f"By type: {summary['by_type']}"]
    if not items:
        lines.append("No pending actions.")
        console.print("\n".join(lines))
        return
    for item in items[:5]:
        lines.append("")
        lines.append(f"[{short_token(item['token'])}] {item['action_type']}")
        lines.append(f"Target: {compact_text(action_target(item), 110)}")
        lines.append("Preview:")
        lines.append(approval_preview(item, limit=6))
    if len(items) > 5:
        lines.append("")
        lines.append(f"... {len(items) - 5} more pending actions")
    console.print("\n".join(lines))


def approve_or_execute_pending_action(workspace: Path, token: str, render: bool = True) -> dict:
    payload = load_pending_action(workspace, token)
    if payload["action_type"] == "planner_approval":
        session_id = payload.get("details", {}).get("session_id")
        if not session_id:
            raise ValueError("planner_approval token is missing session_id")
        agent = build_agent(workspace, session_id=session_id)
        agent.subscribe(render_event)
        events = agent.approve_pending_plan(token)
        if render:
            console.print()
        return {"token": token, "action_type": payload["action_type"], "session_id": session_id, "event_count": len(events), "result": "approved_and_executed"}
    registry = ToolRegistry(workspace, policy=Settings.load(workspace).tool_policy)
    result = registry.execute("approve_pending_action", {"token": token})
    if render:
        console.print(result.content)
        if result.details:
            console.print(json.dumps(result.details, ensure_ascii=False, indent=2))
    return {"token": token, "action_type": payload["action_type"], "result": result.content}


def reject_pending_action(workspace: Path, token: str, render: bool = True) -> dict:
    payload = load_pending_action(workspace, token)
    if payload["action_type"] == "planner_approval":
        session_id = payload.get("details", {}).get("session_id")
        if not session_id:
            raise ValueError("planner_approval token is missing session_id")
        agent = build_agent(workspace, session_id=session_id)
        agent.reject_pending_plan(token)
        message = f"Rejected planner approval {token} for session {session_id}"
        if render:
            console.print(message)
        return {"token": token, "action_type": payload["action_type"], "result": message}
    registry = ToolRegistry(workspace, policy=Settings.load(workspace).tool_policy)
    result = registry.execute("reject_pending_action", {"token": token})
    if render:
        console.print(result.content)
    return {"token": token, "action_type": payload["action_type"], "result": result.content}


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
        render_approval_panel(workspace)
        return "handled"
    if raw.startswith("/approve "):
        token = raw.split(" ", 1)[1].strip()
        payload = load_pending_action(workspace, token)
        if payload["action_type"] == "planner_approval":
            session_id = payload.get("details", {}).get("session_id")
            if session_id != agent.session_id:
                console.print(f"Planner token belongs to session {session_id}. Use /resume {session_id} first.")
                return "handled"
            agent.approve_pending_plan(token)
            console.print()
        else:
            approve_or_execute_pending_action(workspace, token, render=True)
        return "handled"
    if raw.startswith("/reject "):
        token = raw.split(" ", 1)[1].strip()
        payload = load_pending_action(workspace, token)
        if payload["action_type"] == "planner_approval":
            session_id = payload.get("details", {}).get("session_id")
            if session_id != agent.session_id:
                console.print(f"Planner token belongs to session {session_id}. Use /resume {session_id} first.")
                return "handled"
            agent.reject_pending_plan(token)
            console.print(f"Rejected planner approval {token}")
        else:
            reject_pending_action(workspace, token, render=True)
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
        if agent.state.pending_plan_token:
            console.print(f"Pending planner gate: {agent.state.pending_plan_token}. Use /approve {agent.state.pending_plan_token} or /reject {agent.state.pending_plan_token}.")
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
    payload = [{"id": session.id, "parent_id": session.parent_id, "model": session.model.model, "updated_at": session.updated_at, "summarized_message_count": session.compaction.summarized_message_count, "pending_plan_token": session.pending_plan_token, "pending_tool_call_count": len(session.pending_tool_calls)} for session in store.list()]
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
    render_approval_panel(workspace)


def approvals_show_main(workspace: Path, token: str) -> None:
    registry = ToolRegistry(workspace, policy=Settings.load(workspace).tool_policy)
    result = registry.execute("preview_pending_action", {"token": token})
    console.print(f"Token: {token}")
    console.print(result.content)
    console.print(json.dumps(result.details, ensure_ascii=False, indent=2))


def approvals_approve_main(workspace: Path, token: str) -> None:
    approve_or_execute_pending_action(workspace, token, render=True)


def approvals_reject_main(workspace: Path, token: str) -> None:
    reject_pending_action(workspace, token, render=True)


def approvals_approve_all_main(workspace: Path) -> None:
    store = pending_action_store_for(workspace)
    tokens = [item["token"] for item in store.list()]
    results = [approve_or_execute_pending_action(workspace, token, render=False) for token in tokens]
    console.print(json.dumps(results, ensure_ascii=False, indent=2))


def approvals_reject_all_main(workspace: Path) -> None:
    store = pending_action_store_for(workspace)
    tokens = [item["token"] for item in store.list()]
    results = [reject_pending_action(workspace, token, render=False) for token in tokens]
    console.print(json.dumps(results, ensure_ascii=False, indent=2))


def workflow_repo_main(workspace: Path, query: Optional[str] = None, token: Optional[str] = None, auto_apply: bool = False, path_filter: Optional[str] = None, staged_only: bool = False) -> None:
    registry = ToolRegistry(workspace, policy=Settings.load(workspace).tool_policy)
    payload = {"planner": [], "executor": [], "next_actions": []}
    target_path = path_filter
    if query:
        payload["planner"].append({"step": "Search the codebase for relevant symbols or text.", "status": "planned"})
        grep_args = {"query": query}
        if path_filter:
            grep_args["path"] = path_filter
        grep = registry.execute("grep_code", grep_args)
        payload["executor"].append({"step": "Run grep_code", "status": "done", "content": grep.content, "details": grep.details})
        payload["next_actions"].append("Review grep results and decide which file to change.")
    payload["planner"].append({"step": "Inspect staged actions before applying anything.", "status": "planned"})
    summary = approvals_summary_payload(workspace)
    payload["executor"].append({"step": "Inspect pending actions", "status": "done", "details": {"count": summary["count"], "by_type": summary["by_type"]}})
    if token:
        payload["planner"].append({"step": f"Preview the staged action for token {token}.", "status": "planned"})
        preview = registry.execute("preview_pending_action", {"token": token})
        target_path = preview.details.get("target_path") or target_path
        payload["executor"].append({"step": "Preview staged action", "status": "done", "content": preview.content, "details": preview.details})
        payload["next_actions"].append("Check the preview diff, shell command, or planner summary before approving it.")
        if auto_apply:
            payload["planner"].append({"step": "Approve the token and let execution continue.", "status": "planned"})
            applied = approve_or_execute_pending_action(workspace, token, render=False)
            payload["executor"].append({"step": "Approve and execute staged action", "status": "done", "details": applied})
            payload["next_actions"].append("Inspect git status and git diff after applying the action.")
        else:
            payload["planner"].append({"step": f"Approve token {token} when the preview looks correct.", "status": "pending"})
    payload["planner"].append({"step": "Inspect repository state after the planned change.", "status": "planned"})
    status = registry.execute("git_status", {})
    diff_args = {}
    if staged_only and target_path:
        diff_args["path"] = target_path
    elif path_filter:
        diff_args["path"] = path_filter
    diff = registry.execute("git_diff_worktree", diff_args)
    payload["executor"].append({"step": "Inspect git status", "status": "done", "content": status.content, "details": status.details})
    payload["executor"].append({"step": "Inspect git diff", "status": "done", "content": diff.content, "details": diff.details})
    if not token:
        payload["next_actions"].append("Stage an edit, shell action, or planner approval, then re-run workflow repo with --token.")
    if staged_only and not target_path:
        payload["next_actions"].append("No target path found for staged-only diff; provide --path-filter or a token tied to a file action.")
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
            "high_risk_plan": settings.tool_policy.confirm_high_risk_plan,
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
    def workflow_repo(query: Optional[str] = typer.Option(None, "--query"), token: Optional[str] = typer.Option(None, "--token"), auto_apply: bool = typer.Option(False, "--auto-apply"), path_filter: Optional[str] = typer.Option(None, "--path-filter"), staged_only: bool = typer.Option(False, "--staged-only"), workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        workflow_repo_main(workspace, query=query, token=token, auto_apply=auto_apply, path_filter=path_filter, staged_only=staged_only)


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
    workflow_repo_parser.add_argument("--path-filter", default=None)
    workflow_repo_parser.add_argument("--staged-only", action="store_true")
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
        workflow_repo_main(Path(args.workspace), query=args.query, token=args.token, auto_apply=args.auto_apply, path_filter=args.path_filter, staged_only=args.staged_only)
    elif command == "config" and args.config_command == "show":
        config_show_main(Path(args.workspace))


if __name__ == "__main__":
    main()
