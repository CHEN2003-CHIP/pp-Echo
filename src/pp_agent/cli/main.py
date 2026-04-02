from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

try:
    import typer
except ImportError:  # pragma: no cover
    typer = None


app = typer.Typer(help="Personal Python coding agent for Windows 10.") if typer else None


if app:
    @app.command()
    def chat(
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
        session_id: Optional[str] = typer.Option(None, "--session"),
    ) -> None:
        from pp_agent.cli.chat import chat_main

        chat_main(workspace, session_id)


    @app.command()
    def run(
        prompt: str = typer.Argument(..., help="Prompt to send to the agent."),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
        session_id: Optional[str] = typer.Option(None, "--session"),
        json_mode: bool = typer.Option(False, "--json"),
        mode: str = typer.Option("default", "--mode"),
    ) -> None:
        from pp_agent.cli.commands.run import run_main

        run_main(prompt, workspace, session_id, json_mode=json_mode, mode=mode)


    sessions_app = typer.Typer(help="Manage stored sessions.")
    approvals_app = typer.Typer(help="Manage staged approvals.")
    workflow_app = typer.Typer(help="Guided repo-aware workflows.")
    config_app = typer.Typer(help="Show active configuration.")
    timeline_app = typer.Typer(help="Inspect persisted agent timeline history.")
    app.add_typer(sessions_app, name="sessions")
    app.add_typer(approvals_app, name="approvals")
    app.add_typer(workflow_app, name="workflow")
    app.add_typer(config_app, name="config")
    app.add_typer(timeline_app, name="timeline")

    @sessions_app.command("list")
    def sessions_list(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        from pp_agent.cli.commands.sessions import sessions_list_main

        sessions_list_main(workspace)


    @sessions_app.command("tree")
    def sessions_tree(
        sort_mode: str = typer.Option("branch", "--sort"),
        session_id: Optional[str] = typer.Option(None, "--session"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.sessions import sessions_tree_main

        sessions_tree_main(workspace, session_id=session_id, sort_mode=sort_mode)


    @sessions_app.command("fork")
    def sessions_fork(session_id: str, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        from pp_agent.cli.commands.sessions import sessions_fork_main

        sessions_fork_main(workspace, session_id)


    @sessions_app.command("branch")
    def sessions_branch(session_id: str, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        from pp_agent.cli.commands.sessions import sessions_fork_main

        sessions_fork_main(workspace, session_id)


    @sessions_app.command("rewind")
    def sessions_rewind(
        session_id: str,
        message_count: int,
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.sessions import sessions_rewind_main

        sessions_rewind_main(workspace, session_id, message_count)


    @sessions_app.command("rewind-turn")
    def sessions_rewind_turn(
        session_id: str,
        turn_count: int,
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.sessions import sessions_rewind_turn_main

        sessions_rewind_turn_main(workspace, session_id, turn_count)


    @approvals_app.command("list")
    def approvals_list(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        from pp_agent.cli.commands.approvals import approvals_list_main

        approvals_list_main(workspace)


    @approvals_app.command("summary")
    def approvals_summary(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        from pp_agent.cli.commands.approvals import approvals_summary_main

        approvals_summary_main(workspace)


    @approvals_app.command("show")
    def approvals_show(token: str, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        from pp_agent.cli.commands.approvals import approvals_show_main

        approvals_show_main(workspace, token)


    @approvals_app.command("approve")
    def approvals_approve(token: str, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        from pp_agent.cli.commands.approvals import approvals_approve_main

        approvals_approve_main(workspace, token)


    @approvals_app.command("reject")
    def approvals_reject(token: str, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        from pp_agent.cli.commands.approvals import approvals_reject_main

        approvals_reject_main(workspace, token)


    @approvals_app.command("approve-all")
    def approvals_approve_all(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        from pp_agent.cli.commands.approvals import approvals_approve_all_main

        approvals_approve_all_main(workspace)


    @approvals_app.command("reject-all")
    def approvals_reject_all(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        from pp_agent.cli.commands.approvals import approvals_reject_all_main

        approvals_reject_all_main(workspace)


    @workflow_app.command("repo")
    def workflow_repo(
        query: Optional[str] = typer.Option(None, "--query"),
        token: Optional[str] = typer.Option(None, "--token"),
        auto_apply: bool = typer.Option(False, "--auto-apply"),
        path_filter: Optional[str] = typer.Option(None, "--path-filter"),
        staged_only: bool = typer.Option(False, "--staged-only"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.workflow import workflow_repo_main

        workflow_repo_main(
            workspace,
            query=query,
            token=token,
            auto_apply=auto_apply,
            path_filter=path_filter,
            staged_only=staged_only,
        )


    @config_app.command("show")
    def config_show(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        from pp_agent.cli.commands.config import config_show_main

        config_show_main(workspace)


    @timeline_app.command("show")
    def timeline_show(
        session_id: Optional[str] = typer.Option(None, "--session"),
        limit: int = typer.Option(30, "--limit"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.timeline import timeline_show_main

        timeline_show_main(workspace, session_id=session_id, limit=limit)


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
    run_parser.add_argument("--json", action="store_true")
    run_parser.add_argument("--mode", default="default")
    sessions_parser = subparsers.add_parser("sessions")
    sessions_subparsers = sessions_parser.add_subparsers(dest="sessions_command", required=True)
    sessions_list_parser = sessions_subparsers.add_parser("list")
    sessions_list_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    sessions_tree_parser = sessions_subparsers.add_parser("tree")
    sessions_tree_parser.add_argument("--sort", default="branch")
    sessions_tree_parser.add_argument("--session", default=None)
    sessions_tree_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    for name in ["fork", "branch"]:
        command_parser = sessions_subparsers.add_parser(name)
        command_parser.add_argument("session_id")
        command_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    sessions_rewind_parser = sessions_subparsers.add_parser("rewind")
    sessions_rewind_parser.add_argument("session_id")
    sessions_rewind_parser.add_argument("message_count", type=int)
    sessions_rewind_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    sessions_rewind_turn_parser = sessions_subparsers.add_parser("rewind-turn")
    sessions_rewind_turn_parser.add_argument("session_id")
    sessions_rewind_turn_parser.add_argument("turn_count", type=int)
    sessions_rewind_turn_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    approvals_parser = subparsers.add_parser("approvals")
    approvals_subparsers = approvals_parser.add_subparsers(dest="approvals_command", required=True)
    for name in ["list", "summary", "approve-all", "reject-all"]:
        command_parser = approvals_subparsers.add_parser(name)
        command_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
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
    timeline_parser = subparsers.add_parser("timeline")
    timeline_subparsers = timeline_parser.add_subparsers(dest="timeline_command", required=True)
    timeline_show_parser = timeline_subparsers.add_parser("show")
    timeline_show_parser.add_argument("--session", default=None)
    timeline_show_parser.add_argument("--limit", type=int, default=30)
    timeline_show_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))

    args = parser.parse_args()
    command = getattr(args, "command")
    if command == "chat":
        from pp_agent.cli.chat import chat_main

        chat_main(Path(args.workspace), args.session)
    elif command == "run":
        from pp_agent.cli.commands.run import run_main

        run_main(args.prompt, Path(args.workspace), args.session, json_mode=args.json, mode=args.mode)
    elif command == "sessions" and args.sessions_command == "list":
        from pp_agent.cli.commands.sessions import sessions_list_main

        sessions_list_main(Path(args.workspace))
    elif command == "sessions" and args.sessions_command == "tree":
        from pp_agent.cli.commands.sessions import sessions_tree_main

        sessions_tree_main(Path(args.workspace), session_id=args.session, sort_mode=args.sort)
    elif command == "sessions" and args.sessions_command in {"fork", "branch"}:
        from pp_agent.cli.commands.sessions import sessions_fork_main

        sessions_fork_main(Path(args.workspace), args.session_id)
    elif command == "sessions" and args.sessions_command == "rewind":
        from pp_agent.cli.commands.sessions import sessions_rewind_main

        sessions_rewind_main(Path(args.workspace), args.session_id, args.message_count)
    elif command == "sessions" and args.sessions_command == "rewind-turn":
        from pp_agent.cli.commands.sessions import sessions_rewind_turn_main

        sessions_rewind_turn_main(Path(args.workspace), args.session_id, args.turn_count)
    elif command == "approvals" and args.approvals_command == "list":
        from pp_agent.cli.commands.approvals import approvals_list_main

        approvals_list_main(Path(args.workspace))
    elif command == "approvals" and args.approvals_command == "summary":
        from pp_agent.cli.commands.approvals import approvals_summary_main

        approvals_summary_main(Path(args.workspace))
    elif command == "approvals" and args.approvals_command == "show":
        from pp_agent.cli.commands.approvals import approvals_show_main

        approvals_show_main(Path(args.workspace), args.token)
    elif command == "approvals" and args.approvals_command == "approve":
        from pp_agent.cli.commands.approvals import approvals_approve_main

        approvals_approve_main(Path(args.workspace), args.token)
    elif command == "approvals" and args.approvals_command == "reject":
        from pp_agent.cli.commands.approvals import approvals_reject_main

        approvals_reject_main(Path(args.workspace), args.token)
    elif command == "approvals" and args.approvals_command == "approve-all":
        from pp_agent.cli.commands.approvals import approvals_approve_all_main

        approvals_approve_all_main(Path(args.workspace))
    elif command == "approvals" and args.approvals_command == "reject-all":
        from pp_agent.cli.commands.approvals import approvals_reject_all_main

        approvals_reject_all_main(Path(args.workspace))
    elif command == "workflow" and args.workflow_command == "repo":
        from pp_agent.cli.commands.workflow import workflow_repo_main

        workflow_repo_main(
            Path(args.workspace),
            query=args.query,
            token=args.token,
            auto_apply=args.auto_apply,
            path_filter=args.path_filter,
            staged_only=args.staged_only,
        )
    elif command == "config" and args.config_command == "show":
        from pp_agent.cli.commands.config import config_show_main

        config_show_main(Path(args.workspace))
    elif command == "timeline" and args.timeline_command == "show":
        from pp_agent.cli.commands.timeline import timeline_show_main

        timeline_show_main(Path(args.workspace), session_id=args.session, limit=args.limit)


__all__ = ["app", "main"]


if __name__ == "__main__":
    main()
