"""
PP-ECHO - 命令行入口模块
===========================
功能描述：
    为Windows 10系统设计的Python编码代理CLI工具，**双命令行解析模式**：
    1. 优先使用Typer库实现现代化、带自动补全的命令行交互
    2. 降级兼容标准argparse库，无依赖时也可正常运行
    提供聊天交互、指令执行、会话管理、审批管理、工作流、配置查看等核心功能
适用场景：
    开发者通过命令行与Python编码代理交互，管理会话、代码 checkpoint、能力插件等
作者：CHEN
日期：2026-04-03
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

try:
    import typer
except ImportError:  # pragma: no cover
    typer = None

# 初始化Typer主应用
app = typer.Typer(help="Personal Python coding agent for Windows 10.") if typer else None


if app:
    @app.command()
    def chat(
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
        session_id: Optional[str] = typer.Option(None, "--session"),
    ) -> None:
        """
        启动交互式聊天模式
        :param workspace: 工作目录，默认当前目录
        :param session_id: 会话ID，可选
        """
        from pp_agent.cli.chat import chat_main

        chat_main(workspace, session_id)


    @app.command()
    def run(
        prompt: Optional[str] = typer.Argument(None, help="Prompt to send to the agent."),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
        session_id: Optional[str] = typer.Option(None, "--session"),
        json_mode: bool = typer.Option(False, "--json"),
        mode: str = typer.Option("default", "--mode"),
    ) -> None:
        """
        执行单条指令，非交互式调用代理
        :param prompt: 发送给代理的指令（必传）
        :param workspace: 工作目录
        :param session_id: 会话ID
        :param json_mode: 是否以JSON格式返回结果
        :param mode: 执行模式，默认default
        """
        from pp_agent.cli.commands.run import run_main

        run_main(prompt, workspace, session_id, json_mode=json_mode, mode=mode)

    @app.command()
    def tui(
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
        session_id: Optional[str] = typer.Option(None, "--session"),
    ) -> None:
        from pp_agent.tui.main import tui_main

        tui_main(workspace, session_id)

    @app.command("claw-tui")
    def claw_tui(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        from pp_agent.cli.commands.claw_tui import claw_tui_main

        raise typer.Exit(claw_tui_main(workspace))

    # 注册二级子命令应用，分类管理不同功能模块
    sessions_app = typer.Typer(help="Manage stored sessions.")
    approvals_app = typer.Typer(help="Manage staged approvals.")
    workflow_app = typer.Typer(help="Guided repo-aware workflows.")
    config_app = typer.Typer(help="Show active configuration.")
    timeline_app = typer.Typer(help="Inspect persisted agent timeline history.")
    checkpoint_app = typer.Typer(help="Manage git-backed checkpoints.")
    capabilities_app = typer.Typer(help="Inspect and reload discoverable capabilities.")
    skills_app = typer.Typer(help="Inspect discovered skills.")
    eval_app = typer.Typer(help="Run and report agent evaluations.")

    # 将子命令组挂载到主应用
    app.add_typer(sessions_app, name="sessions")
    app.add_typer(approvals_app, name="approvals")
    app.add_typer(workflow_app, name="workflow")
    app.add_typer(config_app, name="config")
    app.add_typer(timeline_app, name="timeline")
    app.add_typer(checkpoint_app, name="checkpoint")
    app.add_typer(capabilities_app, name="capabilities")
    app.add_typer(skills_app, name="skills")
    app.add_typer(eval_app, name="eval")

    @sessions_app.command("list")
    def sessions_list(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        """列出所有会话"""
        from pp_agent.cli.commands.sessions import sessions_list_main

        sessions_list_main(workspace)


    @sessions_app.command("tree")
    def sessions_tree(
        sort_mode: str = typer.Option("branch", "--sort"),
        view_mode: str = typer.Option("default", "--view"),
        session_id: Optional[str] = typer.Option(None, "--session"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        """以树形结构展示会话"""
        from pp_agent.cli.commands.sessions import sessions_tree_main

        sessions_tree_main(workspace, session_id=session_id, sort_mode=sort_mode, view_mode=view_mode)


    @sessions_app.command("fork")
    def sessions_fork(session_id: str, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        """分叉会话"""
        from pp_agent.cli.commands.sessions import sessions_fork_main

        sessions_fork_main(workspace, session_id)


    @sessions_app.command("branch")
    def sessions_branch(session_id: str, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        """分支会话（复用分叉逻辑）"""
        from pp_agent.cli.commands.sessions import sessions_fork_main

        sessions_fork_main(workspace, session_id)


    @sessions_app.command("rewind")
    def sessions_rewind(
        session_id: str,
        message_count: int,
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        """回退会话指定消息数"""
        from pp_agent.cli.commands.sessions import sessions_rewind_main

        sessions_rewind_main(workspace, session_id, message_count)


    @sessions_app.command("rewind-turn")
    def sessions_rewind_turn(
        session_id: str,
        turn_count: int,
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        """回退会话指定轮次"""
        from pp_agent.cli.commands.sessions import sessions_rewind_turn_main

        sessions_rewind_turn_main(workspace, session_id, turn_count)


    @approvals_app.command("list")
    def approvals_list(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        """列出待审批项"""
        from pp_agent.cli.commands.approvals import approvals_list_main

        approvals_list_main(workspace)


    @approvals_app.command("summary")
    def approvals_summary(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        """审批项概览"""
        from pp_agent.cli.commands.approvals import approvals_summary_main

        approvals_summary_main(workspace)


    @approvals_app.command("show")
    def approvals_show(token: str, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        """查看指定审批项详情"""
        from pp_agent.cli.commands.approvals import approvals_show_main

        approvals_show_main(workspace, token)


    @approvals_app.command("approve")
    def approvals_approve(token: str, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        """通过指定审批项"""
        from pp_agent.cli.commands.approvals import approvals_approve_main

        approvals_approve_main(workspace, token)


    @approvals_app.command("reject")
    def approvals_reject(token: str, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        """拒绝指定审批项"""
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
        """仓库感知的引导式工作流"""
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


    @checkpoint_app.command("create")
    def checkpoint_create(
        session_id: str = typer.Option(..., "--session"),
        reason: str = typer.Option("manual", "--reason"),
        snapshot_type: str = typer.Option("head_snapshot", "--type"),
        force_stash: bool = typer.Option(False, "--stash"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        """创建Git快照（checkpoint）"""
        from pp_agent.cli.commands.checkpoint import checkpoint_create_main

        checkpoint_create_main(workspace, session_id, reason=reason, snapshot_type=snapshot_type, force_stash=force_stash)


    @checkpoint_app.command("list")
    def checkpoint_list(
        session_id: Optional[str] = typer.Option(None, "--session"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.checkpoint import checkpoint_list_main

        checkpoint_list_main(workspace, session_id=session_id)


    @checkpoint_app.command("restore")
    def checkpoint_restore(checkpoint_id: str, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        from pp_agent.cli.commands.checkpoint import checkpoint_restore_main

        checkpoint_restore_main(workspace, checkpoint_id)


    @capabilities_app.command("list")
    def capabilities_list(
        kind: Optional[str] = typer.Option(None, "--kind"),
        include_mcp: Optional[bool] = typer.Option(None, "--include-mcp"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.capabilities import capabilities_list_main

        capabilities_list_main(workspace, kind=kind, include_mcp=include_mcp)


    @capabilities_app.command("show")
    def capabilities_show(
        kind: str,
        name: str,
        include_mcp: Optional[bool] = typer.Option(None, "--include-mcp"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.capabilities import capabilities_show_main

        capabilities_show_main(workspace, kind, name, include_mcp=include_mcp)


    @capabilities_app.command("reload")
    def capabilities_reload(
        kind: Optional[str] = typer.Option(None, "--kind"),
        include_mcp: Optional[bool] = typer.Option(None, "--include-mcp"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.capabilities import capabilities_reload_main

        capabilities_reload_main(workspace, include_mcp=include_mcp)


    def _capabilities_legacy_hints_command(
        include_mcp: Optional[bool] = typer.Option(None, "--include-mcp"),
        json_mode: bool = typer.Option(False, "--json"),
        strict: bool = typer.Option(False, "--strict"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.capabilities import capabilities_legacy_hints_main

        capabilities_legacy_hints_main(workspace, include_mcp=include_mcp, json_mode=json_mode, strict=strict)

    capabilities_app.registered_commands.append(
        typer.models.CommandInfo(
            name="legacy-hints",
            callback=_capabilities_legacy_hints_command,
        )
    )


    @skills_app.command("list")
    def skills_list(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        from pp_agent.cli.commands.skills import skills_list_main

        skills_list_main(workspace)


    @skills_app.command("show")
    def skills_show(name: str, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        from pp_agent.cli.commands.skills import skills_show_main

        skills_show_main(workspace, name)


    @eval_app.command("run")
    def eval_run(
        dataset: Path = typer.Argument(..., help="Path to eval dataset JSON/JSONL."),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
        run_id: Optional[str] = typer.Option(None, "--run-id"),
        output_dir: Optional[Path] = typer.Option(None, "--output-dir"),
        reuse_session: bool = typer.Option(False, "--reuse-session"),
        stop_on_failure: bool = typer.Option(False, "--stop-on-failure"),
        preflight: bool = typer.Option(False, "--preflight"),
        json_mode: bool = typer.Option(False, "--json"),
    ) -> None:
        from pp_agent.cli.commands.eval import eval_run_main

        eval_run_main(
            dataset,
            workspace,
            run_id=run_id,
            output_dir=output_dir,
            reuse_session=reuse_session,
            stop_on_failure=stop_on_failure,
            preflight=preflight,
            json_mode=json_mode,
        )


    @eval_app.command("report")
    def eval_report(
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
        run_id: Optional[str] = typer.Option(None, "--run-id"),
        output_dir: Optional[Path] = typer.Option(None, "--output-dir"),
        json_mode: bool = typer.Option(False, "--json"),
    ) -> None:
        from pp_agent.cli.commands.eval import eval_report_main

        eval_report_main(workspace, run_id=run_id, output_dir=output_dir, json_mode=json_mode)


    @app.command("rewind-safe")
    def rewind_safe(
        session_id: str = typer.Option(..., "--session"),
        checkpoint_id: Optional[str] = typer.Option(None, "--checkpoint"),
        turns: Optional[int] = typer.Option(None, "--turns"),
        messages: Optional[int] = typer.Option(None, "--messages"),
        workspace_only: bool = typer.Option(False, "--workspace-only"),
        conversation_only: bool = typer.Option(False, "--conversation-only"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.checkpoint import rewind_safe_main

        rewind_safe_main(
            workspace,
            session_id=session_id,
            checkpoint_id=checkpoint_id,
            turn_count=turns,
            message_count=messages,
            workspace_only=workspace_only,
            conversation_only=conversation_only,
        )


def main() -> None:
    """
    命令行工具主入口
    逻辑：优先使用Typer模式，未安装则降级为argparse标准模式
    """
    if app and typer:
        app()
        return
    
    # 无Typer依赖时，使用Python内置argparse实现相同功能
    parser = argparse.ArgumentParser(description="Personal Python coding agent for Windows 10.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    chat_parser = subparsers.add_parser("chat")
    chat_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    chat_parser.add_argument("--session", default=None)
    tui_parser = subparsers.add_parser("tui")
    tui_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    tui_parser.add_argument("--session", default=None)
    claw_tui_parser = subparsers.add_parser("claw-tui")
    claw_tui_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("prompt", nargs="?")
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
    sessions_tree_parser.add_argument("--view", default="default")
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
    checkpoint_parser = subparsers.add_parser("checkpoint")
    checkpoint_subparsers = checkpoint_parser.add_subparsers(dest="checkpoint_command", required=True)
    checkpoint_create_parser = checkpoint_subparsers.add_parser("create")
    checkpoint_create_parser.add_argument("--session", required=True)
    checkpoint_create_parser.add_argument("--reason", default="manual")
    checkpoint_create_parser.add_argument("--type", dest="snapshot_type", default="head_snapshot")
    checkpoint_create_parser.add_argument("--stash", action="store_true")
    checkpoint_create_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    checkpoint_list_parser = checkpoint_subparsers.add_parser("list")
    checkpoint_list_parser.add_argument("--session", default=None)
    checkpoint_list_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    checkpoint_restore_parser = checkpoint_subparsers.add_parser("restore")
    checkpoint_restore_parser.add_argument("checkpoint_id")
    checkpoint_restore_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    capabilities_parser = subparsers.add_parser("capabilities")
    capabilities_subparsers = capabilities_parser.add_subparsers(dest="capabilities_command", required=True)
    capabilities_list_parser = capabilities_subparsers.add_parser("list")
    capabilities_list_parser.add_argument("--kind", default=None)
    capabilities_list_parser.add_argument("--include-mcp", dest="include_mcp", action="store_true")
    capabilities_list_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    capabilities_show_parser = capabilities_subparsers.add_parser("show")
    capabilities_show_parser.add_argument("kind")
    capabilities_show_parser.add_argument("name")
    capabilities_show_parser.add_argument("--include-mcp", dest="include_mcp", action="store_true")
    capabilities_show_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    capabilities_reload_parser = capabilities_subparsers.add_parser("reload")
    capabilities_reload_parser.add_argument("--kind", default=None)
    capabilities_reload_parser.add_argument("--include-mcp", dest="include_mcp", action="store_true")
    capabilities_reload_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    capabilities_legacy_hints_parser = capabilities_subparsers.add_parser("legacy-hints")
    capabilities_legacy_hints_parser.add_argument("--include-mcp", dest="include_mcp", action="store_true")
    capabilities_legacy_hints_parser.add_argument("--json", action="store_true")
    capabilities_legacy_hints_parser.add_argument("--strict", action="store_true")
    capabilities_legacy_hints_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    skills_parser = subparsers.add_parser("skills")
    skills_subparsers = skills_parser.add_subparsers(dest="skills_command", required=True)
    skills_list_parser = skills_subparsers.add_parser("list")
    skills_list_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    skills_show_parser = skills_subparsers.add_parser("show")
    skills_show_parser.add_argument("name")
    skills_show_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    eval_parser = subparsers.add_parser("eval")
    eval_subparsers = eval_parser.add_subparsers(dest="eval_command", required=True)
    eval_run_parser = eval_subparsers.add_parser("run")
    eval_run_parser.add_argument("dataset")
    eval_run_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    eval_run_parser.add_argument("--run-id", default=None)
    eval_run_parser.add_argument("--output-dir", default=None)
    eval_run_parser.add_argument("--reuse-session", action="store_true")
    eval_run_parser.add_argument("--stop-on-failure", action="store_true")
    eval_run_parser.add_argument("--preflight", action="store_true")
    eval_run_parser.add_argument("--json", action="store_true")
    eval_report_parser = eval_subparsers.add_parser("report")
    eval_report_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    eval_report_parser.add_argument("--run-id", default=None)
    eval_report_parser.add_argument("--output-dir", default=None)
    eval_report_parser.add_argument("--json", action="store_true")
    rewind_safe_parser = subparsers.add_parser("rewind-safe")
    rewind_safe_parser.add_argument("--session", required=True)
    rewind_safe_parser.add_argument("--checkpoint", default=None)
    rewind_safe_parser.add_argument("--turns", type=int, default=None)
    rewind_safe_parser.add_argument("--messages", type=int, default=None)
    rewind_safe_parser.add_argument("--workspace-only", action="store_true")
    rewind_safe_parser.add_argument("--conversation-only", action="store_true")
    rewind_safe_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))

    args = parser.parse_args()
    command = getattr(args, "command")
    if command == "chat":
        from pp_agent.cli.chat import chat_main

        chat_main(Path(args.workspace), args.session)
    elif command == "tui":
        from pp_agent.tui.main import tui_main

        tui_main(Path(args.workspace), args.session)
    elif command == "claw-tui":
        from pp_agent.cli.commands.claw_tui import claw_tui_main

        raise SystemExit(claw_tui_main(Path(args.workspace)))
    elif command == "run":
        from pp_agent.cli.commands.run import run_main

        run_main(args.prompt, Path(args.workspace), args.session, json_mode=args.json, mode=args.mode)
    elif command == "sessions" and args.sessions_command == "list":
        from pp_agent.cli.commands.sessions import sessions_list_main

        sessions_list_main(Path(args.workspace))
    elif command == "sessions" and args.sessions_command == "tree":
        from pp_agent.cli.commands.sessions import sessions_tree_main

        sessions_tree_main(Path(args.workspace), session_id=args.session, sort_mode=args.sort, view_mode=args.view)
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
    elif command == "checkpoint" and args.checkpoint_command == "create":
        from pp_agent.cli.commands.checkpoint import checkpoint_create_main

        checkpoint_create_main(Path(args.workspace), args.session, reason=args.reason, snapshot_type=args.snapshot_type, force_stash=args.stash)
    elif command == "checkpoint" and args.checkpoint_command == "list":
        from pp_agent.cli.commands.checkpoint import checkpoint_list_main

        checkpoint_list_main(Path(args.workspace), session_id=args.session)
    elif command == "checkpoint" and args.checkpoint_command == "restore":
        from pp_agent.cli.commands.checkpoint import checkpoint_restore_main

        checkpoint_restore_main(Path(args.workspace), args.checkpoint_id)
    elif command == "capabilities" and args.capabilities_command == "list":
        from pp_agent.cli.commands.capabilities import capabilities_list_main

        capabilities_list_main(Path(args.workspace), kind=args.kind, include_mcp=args.include_mcp or None)
    elif command == "capabilities" and args.capabilities_command == "show":
        from pp_agent.cli.commands.capabilities import capabilities_show_main

        capabilities_show_main(Path(args.workspace), args.kind, args.name, include_mcp=args.include_mcp or None)
    elif command == "capabilities" and args.capabilities_command == "reload":
        from pp_agent.cli.commands.capabilities import capabilities_reload_main

        capabilities_reload_main(Path(args.workspace), include_mcp=args.include_mcp or None)
    elif command == "capabilities" and args.capabilities_command == "legacy-hints":
        from pp_agent.cli.commands.capabilities import capabilities_legacy_hints_main

        capabilities_legacy_hints_main(
            Path(args.workspace),
            include_mcp=args.include_mcp or None,
            json_mode=args.json,
            strict=args.strict,
        )
    elif command == "skills" and args.skills_command == "list":
        from pp_agent.cli.commands.skills import skills_list_main

        skills_list_main(Path(args.workspace))
    elif command == "skills" and args.skills_command == "show":
        from pp_agent.cli.commands.skills import skills_show_main

        skills_show_main(Path(args.workspace), args.name)
    elif command == "eval" and args.eval_command == "run":
        from pp_agent.cli.commands.eval import eval_run_main

        eval_run_main(
            Path(args.dataset),
            Path(args.workspace),
            run_id=args.run_id,
            output_dir=Path(args.output_dir) if args.output_dir else None,
            reuse_session=args.reuse_session,
            stop_on_failure=args.stop_on_failure,
            preflight=args.preflight,
            json_mode=args.json,
        )
    elif command == "eval" and args.eval_command == "report":
        from pp_agent.cli.commands.eval import eval_report_main

        eval_report_main(
            Path(args.workspace),
            run_id=args.run_id,
            output_dir=Path(args.output_dir) if args.output_dir else None,
            json_mode=args.json,
        )
    elif command == "rewind-safe":
        from pp_agent.cli.commands.checkpoint import rewind_safe_main

        rewind_safe_main(
            Path(args.workspace),
            session_id=args.session,
            checkpoint_id=args.checkpoint,
            turn_count=args.turns,
            message_count=args.messages,
            workspace_only=args.workspace_only,
            conversation_only=args.conversation_only,
        )


__all__ = ["app", "main"]


if __name__ == "__main__":
    main()
