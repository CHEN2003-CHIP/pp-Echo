"""Command-line entrypoint for pp-agent.

The Typer application is the primary CLI surface. An argparse fallback remains
for environments where Typer is unavailable.
"""

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

    @app.command()
    def web(
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
        host: str = typer.Option("127.0.0.1", "--host"),
        port: int = typer.Option(8765, "--port"),
    ) -> None:
        from pp_agent.cli.commands.web import web_main

        web_main(workspace, host=host, port=port)

    @app.command()
    def onboard(
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
        json_mode: bool = typer.Option(False, "--json"),
        check_model: bool = typer.Option(False, "--check-model"),
        no_color: bool = typer.Option(False, "--no-color"),
    ) -> None:
        from pp_agent.cli.commands.onboarding import onboarding_main

        onboarding_main(workspace, json_mode=json_mode, check_model=check_model, no_color=no_color)

    @app.command("claw-tui")
    def claw_tui(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        from pp_agent.cli.commands.claw_tui import claw_tui_main

        raise typer.Exit(claw_tui_main(workspace))

    sessions_app = typer.Typer(help="Manage stored sessions.")
    approvals_app = typer.Typer(help="Manage staged approvals.")
    workflow_app = typer.Typer(help="Guided repo-aware workflows.")
    config_app = typer.Typer(help="Show active configuration.")
    timeline_app = typer.Typer(help="Inspect persisted agent timeline history.")
    checkpoint_app = typer.Typer(help="Manage git-backed checkpoints.")
    capabilities_app = typer.Typer(help="Inspect and reload discoverable capabilities.")
    skills_app = typer.Typer(help="Inspect discovered skills.")
    eval_app = typer.Typer(help="Run and report agent evaluations.")
    memory_app = typer.Typer(help="Inspect and query Markdown file memory.")
    context_app = typer.Typer(help="Compare and replay ContextPipeline output.")

    app.add_typer(sessions_app, name="sessions")
    app.add_typer(approvals_app, name="approvals")
    app.add_typer(workflow_app, name="workflow")
    app.add_typer(config_app, name="config")
    app.add_typer(timeline_app, name="timeline")
    app.add_typer(checkpoint_app, name="checkpoint")
    app.add_typer(capabilities_app, name="capabilities")
    app.add_typer(skills_app, name="skills")
    app.add_typer(eval_app, name="eval")
    app.add_typer(memory_app, name="memory")
    app.add_typer(context_app, name="context")

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


    @workflow_app.command("doctor")
    def workflow_doctor(
        session_id: Optional[str] = typer.Option(None, "--session"),
        json_mode: bool = typer.Option(False, "--json"),
        fix: bool = typer.Option(False, "--fix"),
        dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
        apply: bool = typer.Option(False, "--apply"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.workflow import workflow_doctor_main

        workflow_doctor_main(workspace, session_id=session_id, json_mode=json_mode, fix=fix, dry_run=dry_run, apply=apply)


    @config_app.command("show")
    def config_show(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        from pp_agent.cli.commands.config import config_show_main

        config_show_main(workspace)

    @config_app.command("schema")
    def config_schema(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        from pp_agent.cli.commands.config import config_schema_main

        config_schema_main(workspace)

    @config_app.command("set")
    def config_set(
        path: str,
        value: str,
        base_hash: Optional[str] = typer.Option(None, "--base-hash"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.config import config_set_main

        config_set_main(workspace, path, value, base_hash=base_hash)

    @config_app.command("patch")
    def config_patch(
        patch: str,
        base_hash: Optional[str] = typer.Option(None, "--base-hash"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.config import config_patch_main

        config_patch_main(workspace, patch, base_hash=base_hash)


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

    @skills_app.command("list")
    def skills_list(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        from pp_agent.cli.commands.skills import skills_list_main

        skills_list_main(workspace)


    @skills_app.command("show")
    def skills_show(name: str, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        from pp_agent.cli.commands.skills import skills_show_main

        skills_show_main(workspace, name)

    @skills_app.command("roots")
    def skills_roots(workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        from pp_agent.cli.commands.skills import skills_roots_main

        skills_roots_main(workspace)

    @skills_app.command("add-dir")
    def skills_add_dir(directory: Path, workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w")) -> None:
        from pp_agent.cli.commands.skills import skills_add_dir_main

        skills_add_dir_main(workspace, directory)


    @eval_app.command("run")
    def eval_run(
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
        suite: str = typer.Option("pp_echo_core", "--suite"),
        mode: str = typer.Option("deterministic", "--mode"),
        model: Optional[str] = typer.Option(None, "--model"),
        cases: Optional[int] = typer.Option(None, "--cases"),
        seed: int = typer.Option(0, "--seed"),
        timeout_seconds: int = typer.Option(120, "--timeout-seconds"),
        output_dir: Optional[Path] = typer.Option(None, "--output-dir"),
        save_history: bool = typer.Option(False, "--save-history"),
        json_mode: bool = typer.Option(False, "--json"),
    ) -> None:
        from pp_agent.cli.commands.eval import eval_run_main

        eval_run_main(
            workspace,
            suite=suite,
            mode=mode,
            model=model,
            cases=cases,
            seed=seed,
            timeout_seconds=timeout_seconds,
            output_dir=output_dir,
            save_history=save_history,
            json_mode=json_mode,
        )


    @eval_app.command("report")
    def eval_report(
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
        output_dir: Optional[Path] = typer.Option(None, "--output-dir"),
        json_mode: bool = typer.Option(False, "--json"),
    ) -> None:
        from pp_agent.cli.commands.eval import eval_report_main

        eval_report_main(workspace, output_dir=output_dir, json_mode=json_mode)

    @context_app.command("compare-messages")
    def context_compare_messages(
        prompt: Optional[str] = typer.Option(None, "--prompt"),
        session_id: Optional[str] = typer.Option(None, "--session"),
        json_mode: bool = typer.Option(False, "--json"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.context import context_compare_messages_main

        context_compare_messages_main(workspace, prompt=prompt, session_id=session_id, json_mode=json_mode)

    @context_app.command("replay-trace")
    def context_replay_trace(
        run_id: Optional[str] = typer.Option(None, "--run-id"),
        session_id: Optional[str] = typer.Option(None, "--session"),
        json_mode: bool = typer.Option(False, "--json"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.context import context_replay_trace_main

        context_replay_trace_main(workspace, run_id=run_id, session_id=session_id, json_mode=json_mode)

    @context_app.command("grey-report")
    def context_grey_report(
        output: Optional[Path] = typer.Option(None, "--output"),
        json_mode: bool = typer.Option(False, "--json"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.context import context_grey_rollout_report_main

        context_grey_rollout_report_main(workspace, output=output, json_mode=json_mode)

    @memory_app.command("sync")
    def memory_sync(
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
        json_mode: bool = typer.Option(False, "--json"),
    ) -> None:
        from pp_agent.cli.commands.memory import memory_sync_main

        memory_sync_main(workspace, json_mode=json_mode)

    @memory_app.command("search")
    def memory_search(
        query: str = typer.Argument(...),
        top_k: int = typer.Option(5, "--top-k"),
        mode: str = typer.Option("auto", "--mode"),
        scope: str = typer.Option("auto", "--scope"),
        include_debug: bool = typer.Option(False, "--include-debug"),
        json_mode: bool = typer.Option(False, "--json"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.memory import memory_search_main

        memory_search_main(
            workspace,
            query,
            top_k=top_k,
            mode=mode,
            scope=scope,
            include_debug=include_debug,
            json_mode=json_mode,
        )

    @memory_app.command("get")
    def memory_get(
        path: str = typer.Argument(...),
        start_line: Optional[int] = typer.Option(None, "--start-line"),
        line_count: Optional[int] = typer.Option(None, "--line-count"),
        json_mode: bool = typer.Option(False, "--json"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.memory import memory_get_main

        memory_get_main(
            workspace,
            path,
            start_line=start_line,
            line_count=line_count,
            json_mode=json_mode,
        )

    @memory_app.command("propose")
    def memory_propose(
        content: str = typer.Argument(...),
        scope: str = typer.Option("workspace", "--scope"),
        section: str = typer.Option("project_profile", "--section"),
        memory_type: str = typer.Option("general", "--type"),
        confidence: float = typer.Option(0.5, "--confidence"),
        reason: str = typer.Option("", "--reason"),
        json_mode: bool = typer.Option(False, "--json"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.memory import memory_propose_main

        memory_propose_main(
            workspace,
            content,
            scope=scope,
            section=section,
            memory_type=memory_type,
            confidence=confidence,
            reason=reason,
            json_mode=json_mode,
        )

    @memory_app.command("pending")
    def memory_pending(
        json_mode: bool = typer.Option(False, "--json"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.memory import memory_pending_main

        memory_pending_main(workspace, json_mode=json_mode)

    @memory_app.command("approve")
    def memory_approve(
        memory_id: str,
        json_mode: bool = typer.Option(False, "--json"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.memory import memory_approve_main

        memory_approve_main(workspace, memory_id, json_mode=json_mode)

    @memory_app.command("reject")
    def memory_reject(
        memory_id: str,
        json_mode: bool = typer.Option(False, "--json"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.memory import memory_reject_main

        memory_reject_main(workspace, memory_id, json_mode=json_mode)

    @memory_app.command("archive")
    def memory_archive(
        memory_id: str,
        json_mode: bool = typer.Option(False, "--json"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.memory import memory_archive_main

        memory_archive_main(workspace, memory_id, json_mode=json_mode)

    @memory_app.command("replace")
    def memory_replace(
        old_memory_id: str,
        content: str,
        section: str = typer.Option("project_profile", "--section"),
        memory_type: str = typer.Option("general", "--type"),
        confidence: float = typer.Option(0.5, "--confidence"),
        json_mode: bool = typer.Option(False, "--json"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.memory import memory_replace_main

        memory_replace_main(
            workspace,
            old_memory_id,
            content,
            section=section,
            memory_type=memory_type,
            confidence=confidence,
            json_mode=json_mode,
        )

    @memory_app.command("snapshot")
    def memory_snapshot(
        json_mode: bool = typer.Option(False, "--json"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.memory import memory_snapshot_main

        memory_snapshot_main(workspace, json_mode=json_mode)

    @memory_app.command("audit")
    def memory_audit(
        memory_id: Optional[str] = typer.Argument(None),
        limit: int = typer.Option(100, "--limit"),
        json_mode: bool = typer.Option(False, "--json"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.memory import memory_audit_main

        memory_audit_main(workspace, memory_id=memory_id, limit=limit, json_mode=json_mode)

    @memory_app.command("compact-preview")
    def memory_compact_preview(
        json_mode: bool = typer.Option(False, "--json"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.memory import memory_compact_preview_main

        memory_compact_preview_main(workspace, json_mode=json_mode)

    @memory_app.command("compact-apply")
    def memory_compact_apply(
        reason: str = typer.Option("manual_compaction", "--reason"),
        json_mode: bool = typer.Option(False, "--json"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.memory import memory_compact_apply_main

        memory_compact_apply_main(workspace, reason=reason, json_mode=json_mode)

    @memory_app.command("merge-preview")
    def memory_merge_preview(
        json_mode: bool = typer.Option(False, "--json"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.memory import memory_merge_preview_main

        memory_merge_preview_main(workspace, json_mode=json_mode)

    @memory_app.command("merge-apply")
    def memory_merge_apply(
        reason: str = typer.Option("auto_merge", "--reason"),
        json_mode: bool = typer.Option(False, "--json"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.memory import memory_merge_apply_main

        memory_merge_apply_main(workspace, reason=reason, json_mode=json_mode)

    @memory_app.command("provider-status")
    def memory_provider_status(
        json_mode: bool = typer.Option(False, "--json"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.memory import memory_provider_status_main

        memory_provider_status_main(workspace, json_mode=json_mode)

    @memory_app.command("export-to-markdown")
    def memory_export_to_markdown(
        reason: str = typer.Option("manual_export", "--reason"),
        json_mode: bool = typer.Option(False, "--json"),
        workspace: Path = typer.Option(Path.cwd(), "--workspace", "-w"),
    ) -> None:
        from pp_agent.cli.commands.memory import memory_export_to_markdown_main

        memory_export_to_markdown_main(workspace, reason=reason, json_mode=json_mode)


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
    web_parser = subparsers.add_parser("web")
    web_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8765)
    onboard_parser = subparsers.add_parser("onboard")
    onboard_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    onboard_parser.add_argument("--json", action="store_true")
    onboard_parser.add_argument("--check-model", action="store_true")
    onboard_parser.add_argument("--no-color", action="store_true")
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
    workflow_doctor_parser = workflow_subparsers.add_parser("doctor")
    workflow_doctor_parser.add_argument("--session", default=None)
    workflow_doctor_parser.add_argument("--json", action="store_true")
    workflow_doctor_parser.add_argument("--fix", action="store_true")
    workflow_doctor_parser.add_argument("--dry-run", action="store_true", default=True)
    workflow_doctor_parser.add_argument("--apply", action="store_true")
    workflow_doctor_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
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
    skills_parser = subparsers.add_parser("skills")
    skills_subparsers = skills_parser.add_subparsers(dest="skills_command", required=True)
    skills_list_parser = skills_subparsers.add_parser("list")
    skills_list_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    skills_show_parser = skills_subparsers.add_parser("show")
    skills_show_parser.add_argument("name")
    skills_show_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    skills_roots_parser = skills_subparsers.add_parser("roots")
    skills_roots_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    skills_add_dir_parser = skills_subparsers.add_parser("add-dir")
    skills_add_dir_parser.add_argument("directory")
    skills_add_dir_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    eval_parser = subparsers.add_parser("eval")
    eval_subparsers = eval_parser.add_subparsers(dest="eval_command", required=True)
    eval_run_parser = eval_subparsers.add_parser("run")
    eval_run_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    eval_run_parser.add_argument("--suite", default="pp_echo_core")
    eval_run_parser.add_argument("--mode", choices=["deterministic", "live"], default="deterministic")
    eval_run_parser.add_argument("--model", default=None)
    eval_run_parser.add_argument("--cases", type=int, default=None)
    eval_run_parser.add_argument("--seed", type=int, default=0)
    eval_run_parser.add_argument("--timeout-seconds", type=int, default=120)
    eval_run_parser.add_argument("--output-dir", default=None)
    eval_run_parser.add_argument("--save-history", action="store_true")
    eval_run_parser.add_argument("--json", action="store_true")
    eval_report_parser = eval_subparsers.add_parser("report")
    eval_report_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    eval_report_parser.add_argument("--output-dir", default=None)
    eval_report_parser.add_argument("--json", action="store_true")
    memory_parser = subparsers.add_parser("memory")
    memory_subparsers = memory_parser.add_subparsers(dest="memory_command", required=True)
    memory_sync_parser = memory_subparsers.add_parser("sync")
    memory_sync_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    memory_sync_parser.add_argument("--json", action="store_true")
    memory_search_parser = memory_subparsers.add_parser("search")
    memory_search_parser.add_argument("query")
    memory_search_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    memory_search_parser.add_argument("--top-k", type=int, default=5)
    memory_search_parser.add_argument("--mode", default="auto")
    memory_search_parser.add_argument("--scope", default="auto")
    memory_search_parser.add_argument("--include-debug", action="store_true")
    memory_search_parser.add_argument("--json", action="store_true")
    memory_get_parser = memory_subparsers.add_parser("get")
    memory_get_parser.add_argument("path")
    memory_get_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    memory_get_parser.add_argument("--start-line", type=int, default=None)
    memory_get_parser.add_argument("--line-count", type=int, default=None)
    memory_get_parser.add_argument("--json", action="store_true")
    memory_audit_parser = memory_subparsers.add_parser("audit")
    memory_audit_parser.add_argument("memory_id", nargs="?")
    memory_audit_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    memory_audit_parser.add_argument("--limit", type=int, default=100)
    memory_audit_parser.add_argument("--json", action="store_true")
    memory_compact_preview_parser = memory_subparsers.add_parser("compact-preview")
    memory_compact_preview_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    memory_compact_preview_parser.add_argument("--json", action="store_true")
    memory_compact_apply_parser = memory_subparsers.add_parser("compact-apply")
    memory_compact_apply_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    memory_compact_apply_parser.add_argument("--reason", default="manual_compaction")
    memory_compact_apply_parser.add_argument("--json", action="store_true")
    memory_merge_preview_parser = memory_subparsers.add_parser("merge-preview")
    memory_merge_preview_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    memory_merge_preview_parser.add_argument("--json", action="store_true")
    memory_merge_apply_parser = memory_subparsers.add_parser("merge-apply")
    memory_merge_apply_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    memory_merge_apply_parser.add_argument("--reason", default="auto_merge")
    memory_merge_apply_parser.add_argument("--json", action="store_true")
    memory_provider_status_parser = memory_subparsers.add_parser("provider-status")
    memory_provider_status_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    memory_provider_status_parser.add_argument("--json", action="store_true")
    memory_export_parser = memory_subparsers.add_parser("export-to-markdown")
    memory_export_parser.add_argument("--workspace", "-w", default=str(Path.cwd()))
    memory_export_parser.add_argument("--reason", default="manual_export")
    memory_export_parser.add_argument("--json", action="store_true")
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
    elif command == "web":
        from pp_agent.cli.commands.web import web_main

        web_main(Path(args.workspace), host=args.host, port=args.port)
    elif command == "onboard":
        from pp_agent.cli.commands.onboarding import onboarding_main

        onboarding_main(Path(args.workspace), json_mode=args.json, check_model=args.check_model, no_color=args.no_color)
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
    elif command == "workflow" and args.workflow_command == "doctor":
        from pp_agent.cli.commands.workflow import workflow_doctor_main

        workflow_doctor_main(
            Path(args.workspace),
            session_id=args.session,
            json_mode=args.json,
            fix=args.fix,
            dry_run=args.dry_run,
            apply=args.apply,
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
    elif command == "skills" and args.skills_command == "list":
        from pp_agent.cli.commands.skills import skills_list_main

        skills_list_main(Path(args.workspace))
    elif command == "skills" and args.skills_command == "show":
        from pp_agent.cli.commands.skills import skills_show_main

        skills_show_main(Path(args.workspace), args.name)
    elif command == "skills" and args.skills_command == "roots":
        from pp_agent.cli.commands.skills import skills_roots_main

        skills_roots_main(Path(args.workspace))
    elif command == "skills" and args.skills_command == "add-dir":
        from pp_agent.cli.commands.skills import skills_add_dir_main

        skills_add_dir_main(Path(args.workspace), Path(args.directory))
    elif command == "eval" and args.eval_command == "run":
        from pp_agent.cli.commands.eval import eval_run_main

        eval_run_main(
            Path(args.workspace),
            suite=args.suite,
            mode=args.mode,
            model=args.model,
            cases=args.cases,
            seed=args.seed,
            timeout_seconds=args.timeout_seconds,
            output_dir=Path(args.output_dir) if args.output_dir else None,
            save_history=args.save_history,
            json_mode=args.json,
        )
    elif command == "eval" and args.eval_command == "report":
        from pp_agent.cli.commands.eval import eval_report_main

        eval_report_main(
            Path(args.workspace),
            output_dir=Path(args.output_dir) if args.output_dir else None,
            json_mode=args.json,
        )
    elif command == "memory" and args.memory_command == "sync":
        from pp_agent.cli.commands.memory import memory_sync_main

        memory_sync_main(Path(args.workspace), json_mode=args.json)
    elif command == "memory" and args.memory_command == "search":
        from pp_agent.cli.commands.memory import memory_search_main

        memory_search_main(
            Path(args.workspace),
            args.query,
            top_k=args.top_k,
            mode=args.mode,
            scope=args.scope,
            include_debug=args.include_debug,
            json_mode=args.json,
        )
    elif command == "memory" and args.memory_command == "get":
        from pp_agent.cli.commands.memory import memory_get_main

        memory_get_main(
            Path(args.workspace),
            args.path,
            start_line=args.start_line,
            line_count=args.line_count,
            json_mode=args.json,
        )
    elif command == "memory" and args.memory_command == "audit":
        from pp_agent.cli.commands.memory import memory_audit_main

        memory_audit_main(Path(args.workspace), memory_id=args.memory_id, limit=args.limit, json_mode=args.json)
    elif command == "memory" and args.memory_command == "compact-preview":
        from pp_agent.cli.commands.memory import memory_compact_preview_main

        memory_compact_preview_main(Path(args.workspace), json_mode=args.json)
    elif command == "memory" and args.memory_command == "compact-apply":
        from pp_agent.cli.commands.memory import memory_compact_apply_main

        memory_compact_apply_main(Path(args.workspace), reason=args.reason, json_mode=args.json)
    elif command == "memory" and args.memory_command == "merge-preview":
        from pp_agent.cli.commands.memory import memory_merge_preview_main

        memory_merge_preview_main(Path(args.workspace), json_mode=args.json)
    elif command == "memory" and args.memory_command == "merge-apply":
        from pp_agent.cli.commands.memory import memory_merge_apply_main

        memory_merge_apply_main(Path(args.workspace), reason=args.reason, json_mode=args.json)
    elif command == "memory" and args.memory_command == "provider-status":
        from pp_agent.cli.commands.memory import memory_provider_status_main

        memory_provider_status_main(Path(args.workspace), json_mode=args.json)
    elif command == "memory" and args.memory_command == "export-to-markdown":
        from pp_agent.cli.commands.memory import memory_export_to_markdown_main

        memory_export_to_markdown_main(Path(args.workspace), reason=args.reason, json_mode=args.json)
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
