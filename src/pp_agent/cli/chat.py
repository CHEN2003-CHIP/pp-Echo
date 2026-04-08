"""
pp-Echo 命令行交互聊天核心模块
功能: 实现AI智能体的CLI交互式对话主逻辑，包含会话管理、输入解析、异步任务执行、
      计划审批、消息队列、状态渲染等核心能力
作者: CHEN
日期: 2026-04-03
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

try:
    from prompt_toolkit import PromptSession
except ImportError:  # pragma: no cover
    PromptSession = None

from pp_agent.api import chat as create_chat_runtime
from pp_agent.cli.commands.approvals import approve_or_execute_pending_action, load_pending_action
from pp_agent.cli.dispatcher import handle_command, handle_queue_command
from pp_agent.cli.render.runtime import ChatEventRenderer, console, render_runtime_status


def build_agent(workspace: Path, session_id: Optional[str] = None):
    """
    构建AI智能体实例
    :param workspace: 工作区路径
    :param session_id: 会话ID，可选
    :return: 聊天运行时实例
    """
    return create_chat_runtime(workspace, session_id=session_id)


def chat_main(workspace: Path, session_id: Optional[str] = None) -> None:
    """
    聊天主函数：CLI交互入口，处理用户输入与智能体交互逻辑
    :param workspace: 工作区路径
    :param session_id: 会话ID，为空则新建会话
    """
    prompt_session = None
    if PromptSession:
        try:
            prompt_session = PromptSession()
        except Exception:
            prompt_session = None
    # 主循环：支持会话重建/切换
    while True:
        # 创建智能体实例并注册事件渲染器
        agent = build_agent(workspace, session_id=session_id)
        renderer = ChatEventRenderer(agent)
        agent.subscribe(renderer.render)
        worker: Optional[threading.Thread] = None

        # 判断智能体是否正在执行任务
        def is_busy() -> bool:
            return worker is not None and worker.is_alive()

        # 启动工作线程：异步执行任务，不阻塞命令行
        def start_worker(action: str, fn) -> None:
            nonlocal worker

            def runner() -> None:
                try:
                    fn()
                except Exception as exc:  # noqa: BLE001
                    console.print(f"[Error] {exc}")
                finally:
                    console.print()

            worker = threading.Thread(target=runner, name=f"pp-agent-{action}", daemon=True)
            worker.start()

        def safe_handle_command(raw_command: str):
            try:
                return handle_command(agent, raw_command, workspace)
            except Exception as exc:  # noqa: BLE001
                console.print(f"[Error] {exc}")
                return "handled"

        def safe_handle_queue_command(raw_command: str) -> None:
            try:
                handle_queue_command(agent, raw_command)
            except Exception as exc:  # noqa: BLE001
                console.print(f"[Error] {exc}")
        # 渲染基础信息：会话ID、模型名称
        console.print(f"pp-agent session={agent.session_id} model={agent.llm_client.model.model}")
        # 提示待审批的计划令牌
        if agent.state.pending_plan_token:
            console.print(
                f"Pending planner gate: {agent.state.pending_plan_token}. "
                f"Use /approve {agent.state.pending_plan_token} or /reject {agent.state.pending_plan_token}."
            )
        # 提示队列消息数量
        if agent.state.queued_messages:
            console.print(f"Queued messages: {len(agent.state.queued_messages)}. Use /queue to inspect them.")
        render_runtime_status(agent)
        console.print(
            "Tips: /status shows runtime state. Plain text while busy becomes follow-up queue. "
            "Use /queue steering <msg> for higher-priority guidance."
        )

        # 主命令循环：处理用户输入
        while True:
            #处理用户输入
            try:
                raw = prompt_session.prompt("\n> ").strip() if prompt_session else input("\n> ").strip()
            except EOFError:
                return
            if not raw:
                continue
            #优先处理队列任务
            if raw.startswith("/queue"):
                safe_handle_queue_command(raw)
                # 空闲状态下自动执行队列消息
                if not is_busy() and not agent.state.pending_plan_token and agent.state.queued_messages:
                    start_worker("queue", agent.continue_)
                continue
            #智能体忙的时候允许处理查询任务
            if is_busy():
                if raw.startswith("/"):
                    #TODO: maybe skill or mcp allowed here?
                    if raw in {"/session", "/settings", "/status", "/approvals", "/timeline"} or raw.startswith("/tree"):
                        result = safe_handle_command(raw)
                        if result == "quit":
                            console.print("Wait for the current task to finish before quitting.")
                        continue
                    # 非查询命令拒绝执行
                    console.print("Agent is busy. Use /queue steering <message>, /queue, or wait for the current task to finish.")
                    continue
                # 普通文本加入跟进队列:会话结束之后执行
                agent.enqueue_message(raw, delivery="follow_up")
                continue

            # 快捷审批：输入approve/yes...
            if agent.state.pending_plan_token and raw.strip().lower() in {"approve", "yes", "确认", "批准","允许","同意","好的"}:
                token = agent.state.pending_plan_token
                start_worker("approve", lambda: agent.approve_pending_plan(token))
                continue
            
            # 快捷拒绝：输入reject/no
            if agent.state.pending_plan_token and raw.strip().lower() in {"reject", "no", "拒绝","不允许","不同意","不好"}:
                token = agent.state.pending_plan_token
                result = safe_handle_command(f"/reject {token}")
                # 处理退出/新建会话逻辑
                if result == "quit":
                    return
                if result == "new":
                    session_id = None
                    break
                if result != "handled":
                    session_id = result
                    break
                continue

            # 前面提前把文本审批或者拒绝处理是为了防止被误入用户普通prompt当中
            # 处理审批命令
            if raw.startswith("/approve "):
                token = raw.split(" ", 1)[1].strip()
                payload = load_pending_action(workspace, token)
                # 计划审批：校验会话归属
                if payload["action_type"] == "planner_approval":
                    session_for_token = payload.get("details", {}).get("session_id")
                    if session_for_token != agent.session_id:
                        console.print(f"Planner token belongs to session {session_for_token}. Use /resume {session_for_token} first.")
                        continue
                    start_worker("approve", lambda: agent.approve_pending_plan(token))
                #其他类型普通审批
                else:
                    approve_or_execute_pending_action(workspace, token, render=True)
                continue

            # 处理拒绝命令
            if raw.startswith("/reject "):
                result = safe_handle_command(raw)
                if result == "quit":
                    return
                if result == "new":
                    session_id = None
                    break
                if result != "handled":
                    session_id = result
                    break
                continue
            
            # 处理通用系统命令
            if raw.startswith("/"):
                result = safe_handle_command(raw)
                if result == "handled":
                    continue
                #退出命令
                if result == "quit":
                    #agent当前繁忙会等待当前任务处理完成
                    if is_busy():
                        console.print("Wait for the current task to finish before quitting.")
                        continue
                    return
                #新建会话命令
                if result == "new":
                    if is_busy():
                        console.print("Wait for the current task to finish before creating a new session.")
                        continue
                    session_id = None
                    break
                #切换会话命令
                if result != "run":
                    if is_busy():
                        console.print("Wait for the current task to finish before switching sessions.")
                        continue
                    session_id = result
                    break
            # 普通消息：发送给智能体执行
            start_worker("prompt", lambda value=raw: agent.prompt(value))


__all__ = ["chat_main", "handle_command"]
