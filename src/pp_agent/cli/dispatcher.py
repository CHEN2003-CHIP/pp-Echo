"""
文件: command_dispatcher.py
功能: pp-Echo 命令行指令统一分发处理器
     1. 实现队列指令(/queue)独立解析与消息入队管理
     2. 实现全量系统命令(/quit /new /session /status /approve等)路由分发
     3. 支持会话分支、回溯、恢复、模型切换、技能管理、MCP协议调用
     4. 统一处理审批通过/驳回、会话树渲染、时间线查看、插件重载能力
     5. 标准化命令返回状态码，供上层聊天主逻辑判断是否新开线程/切换会话
作者: CHEN
日期: 2026-04-01
"""

from __future__ import annotations

import json
from pathlib import Path

from pp_agent.app.bootstrap import reload_runtime_extensions
# 导入审批相关能力: 加载/执行/驳回待审批动作
from pp_agent.cli.commands.approvals import (
    approve_or_execute_pending_action,
    load_pending_action_or_user_error,
    reject_pending_action,
)
from pp_agent.cli.commands.learning import (
    apply_learning_candidate,
    consolidate_project_memory,
    dumps_payload,
    learning_review_payload,
    learning_show_payload,
    learning_status_payload,
    reject_learning_candidate,
)
from pp_agent.cli.commands.config import config_patch_main, config_set_main
from pp_agent.cli.commands.debug import debug_set_main
from pp_agent.cli.commands.model import model_set_main
# 导入会话管理能力: 分支/回溯/恢复/解析会话ID与轮次
from pp_agent.cli.commands.sessions import (
    branch_session,
    resolve_session_id,
    resolve_session_turn_ref,
    resume_target,
    rewind_session,
    rewind_session_turns,
)
from pp_agent.cli.commands.timeline import timeline_show_main
from pp_agent.cli.render.approvals import render_approval_panel
from pp_agent.cli.render.queue import render_queue_panel
from pp_agent.cli.render.runtime import console, render_runtime_status, render_settings
from pp_agent.cli.render.sessions import render_session_tree
from pp_agent.runtime.tool_surface import active_tool_surface


def handle_queue_command(agent, raw: str) -> bool:
    """
    处理/queue 系列队列管理命令
    :param agent: 当前运行中AI智能体实例
    :param raw: 用户原始输入命令字符串
    :return: bool 固定返回True标识命令已处理
    """
    if raw in {"/queue", "/queue list"}:
        #渲染队列列表
        render_queue_panel(agent)
        return True
    # 高优先级引导消息入队：会在下一轮次开始处理
    if raw.startswith("/queue steering "):
        text = raw.split(" ", 2)[2].strip()
        if not text:
            console.print("Usage: /queue steering <message>")
            return True
        agent.enqueue_message(text, delivery="steering")
        return True
    # 普通跟进消息入队(标准别名)
    if raw.startswith("/queue follow-up "):
        text = raw.split(" ", 2)[2].strip()
        if not text:
            console.print("Usage: /queue follow-up <message>")
            return True
        agent.enqueue_message(text, delivery="follow_up")
        return True
    if raw.startswith("/queue followup "):
        text = raw.split(" ", 2)[2].strip()
        if not text:
            console.print("Usage: /queue followup <message> ")
            return True
        agent.enqueue_message(text, delivery="follow_up")
        return True
    # 非法队列命令提示用法
    console.print("Usage: /queue | /queue list | /queue steering <message> | /queue follow-up <message>")
    return True


def handle_command(agent, raw: str, workspace: Path) -> str:
    """
    通用系统命令统一分发入口
    :param agent: 当前AI智能体实例
    :param raw: 用户输入原始命令
    :param workspace: 项目工作区根路径
    :return: str 状态标识: quit/new/handled/会话ID/run 供上层逻辑判断
    """
    if raw == "/quit":
        return "quit"
    if raw == "/new":
        return "new"
    #查询当前会话ID
    if raw == "/session":
        console.print(f"session: {agent.session_id}")
        return "handled"
    # 查看全局配置信息
    if raw == "/settings":
        render_settings(agent, workspace)
        return "handled"
    # 查看智能体实时运行状态
    if raw == "/status":
        render_runtime_status(agent)
        return "handled"
    if raw == "/tools":
        console.print(json.dumps(active_tool_surface(agent), ensure_ascii=False, indent=2))
        return "handled"
    # 查看所有待审批动作面板
    if raw == "/approvals":
        render_approval_panel(workspace)
        return "handled"
    # 查看会话操作时间线记录
    if raw == "/timeline":
        timeline_show_main(workspace, session_id=agent.session_id, limit=30)
        return "handled"
    # 压缩会话历史消息节省上下文
    if raw == "/compact":
        events = agent.compact_now()
        if not events:
            console.print("No new messages to compact.")
        return "handled"
    if raw.startswith("/config set "):
        parts = raw.split(" ", 3)
        if len(parts) != 4:
            console.print("Usage: /config set <path> <json-value>")
            return "handled"
        config_set_main(workspace, parts[2], parts[3])
        return "handled"
    if raw.startswith("/config patch "):
        patch = raw.split(" ", 2)[2].strip()
        if not patch:
            console.print("Usage: /config patch <json-merge-patch>")
            return "handled"
        config_patch_main(workspace, patch)
        return "handled"
    if raw.startswith("/debug set "):
        parts = raw.split(" ", 3)
        if len(parts) != 4:
            console.print("Usage: /debug set <path> <json-value>")
            return "handled"
        debug_set_main(workspace, parts[2], parts[3], session_id=agent.session_id)
        return "handled"
    # 重载运行时插件/扩展/工具/技能
    if raw == "/reload":
        payload = reload_runtime_extensions(agent, workspace)
        console.print(
            "Reloaded runtime: "
            f"{payload['extension_count']} extensions, "
            f"{payload['tool_count']} dynamic tools, "
            f"{payload['command_count']} commands, "
            f"{payload['resource_count']} resources, "
            f"{payload['skill_count']} skills."
        )
        return "handled"
    # 列出所有可用技能
    if raw in {"/skills", "/skills list"}:
        skill_runtime = getattr(agent, "skill_runtime", None)
        if skill_runtime is None:
            console.print("Skill runtime is not available.")
            return "handled"
        payload = [
            {
                "name": descriptor.name,
                "description": descriptor.description,
                "origin_type": descriptor.origin_type,
                "root_name": descriptor.root_name,
                "precedence": descriptor.precedence,
                "discovery_root": descriptor.discovery_root,
                "discovery_mode": descriptor.discovery_mode,
                "body_loaded": descriptor._body_cache is not None,
            }
            for descriptor in skill_runtime.available_skills().values()
        ]
        console.print(json.dumps(payload, ensure_ascii=False, indent=2))
        return "handled"
    # 查看当前已激活技能
    if raw == "/skills active":
        skill_runtime = getattr(agent, "skill_runtime", None)
        if skill_runtime is None:
            console.print("Skill runtime is not available.")
            return "handled"
        payload = [item.__dict__ for item in skill_runtime.active_skills()]
        console.print(json.dumps(payload, ensure_ascii=False, indent=2))
        return "handled"
    if raw == "/skills reload":
        payload = reload_runtime_extensions(agent, workspace)
        console.print(
            "Reloaded skills: "
            f"{payload['skill_count']} available, "
            f"{payload['active_skill_count']} active."
        )
        return "handled"
    # 手动启用指定技能(标准指令)
    if raw.startswith("/skill use "):
        skill_runtime = getattr(agent, "skill_runtime", None)
        if skill_runtime is None:
            console.print("Skill runtime is not available.")
            return "handled"
        name = raw.split(" ", 2)[2].strip()
        if not name:
            console.print("Usage: /skill use <name>")
            return "handled"
        try:
            descriptor = skill_runtime.use_skill(name)
        except KeyError:
            console.print(f"Unknown skill: {name}")
            return "handled"
        console.print(f"Activated skill {descriptor.name}")
        return "handled"
    # 简写快捷启用技能
    if raw.startswith("/skill:"):
        skill_runtime = getattr(agent, "skill_runtime", None)
        if skill_runtime is None:
            console.print("Skill runtime is not available.")
            return "handled"
        name = raw[len("/skill:") :].strip()
        if not name:
            console.print("Usage: /skill:<name>")
            return "handled"
        try:
            descriptor = skill_runtime.use_skill(name, source="explicit_command")
        except KeyError:
            console.print(f"Unknown skill: {name}")
            return "handled"
        console.print(f"Activated skill {descriptor.name}")
        return "handled"
    # 清空所有已激活技能
    if raw == "/skill clear":
        skill_runtime = getattr(agent, "skill_runtime", None)
        if skill_runtime is None:
            console.print("Skill runtime is not available.")
            return "handled"
        skill_runtime.clear_active()
        console.print("Cleared active skills.")
        return "handled"
    # 查看MCP协议服务运行状态
    if raw == "/learn status":
        console.print(dumps_payload(learning_status_payload(workspace)))
        return "handled"
    if raw == "/learn review":
        console.print(dumps_payload(learning_review_payload(workspace)))
        return "handled"
    if raw.startswith("/learn show "):
        candidate_id = raw.split(" ", 2)[2].strip()
        payload = learning_show_payload(workspace, candidate_id)
        if payload is None:
            console.print(f"Unknown learning candidate: {candidate_id}")
        else:
            console.print(dumps_payload(payload))
        return "handled"
    if raw.startswith("/learn reject "):
        candidate_id = raw.split(" ", 2)[2].strip()
        if reject_learning_candidate(workspace, candidate_id):
            console.print(f"Rejected learning candidate {candidate_id}")
        else:
            console.print(f"Unknown learning candidate: {candidate_id}")
        return "handled"
    if raw.startswith("/learn apply "):
        parts = raw.split()
        if len(parts) != 4:
            console.print("Usage: /learn apply <id> memory|skill")
            return "handled"
        payload = apply_learning_candidate(agent, workspace, parts[2], parts[3])
        console.print(dumps_payload(payload))
        if payload.get("ok") and parts[3] == "skill":
            reload_runtime_extensions(agent, workspace)
        return "handled"
    if raw == "/learn consolidate":
        console.print(dumps_payload(consolidate_project_memory(agent, workspace)))
        return "handled"
    if raw == "/mcp status":
        mcp_runtime = getattr(agent, "mcp_runtime", None)
        payload = {"enabled": False, "server_count": 0, "servers": [], "discovered": False, "active_sessions": [], "tool_count": 0, "resource_count": 0}
        if mcp_runtime is not None:
            payload = mcp_runtime.status()
        console.print(json.dumps(payload, ensure_ascii=False, indent=2))
        return "handled"
    if raw == "/mcp list":
        mcp_runtime = getattr(agent, "mcp_runtime", None)
        if mcp_runtime is None:
            console.print("[]")
            return "handled"
        payload = mcp_runtime.list_servers()
        console.print(json.dumps(payload, ensure_ascii=False, indent=2))
        return "handled"
    # 重载MCP服务与扩展
    if raw == "/mcp reload":
        payload = reload_runtime_extensions(agent, workspace)
        mcp_runtime = getattr(agent, "mcp_runtime", None)
        discovered = []
        if mcp_runtime is not None:
            discovered = mcp_runtime.list_servers()
        console.print(
            json.dumps(
                {
                    "reloaded": True,
                    "mcp_enabled": payload["mcp_enabled"],
                    "discovered": discovered,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return "handled"
    # 手动调用MCP工具能力
    if raw.startswith("/mcp call "):
        mcp_runtime = getattr(agent, "mcp_runtime", None)
        if mcp_runtime is None:
            console.print("MCP runtime is not enabled.")
            return "handled"
        target, arguments = _parse_mcp_call(raw)
        if not target:
            console.print("Usage: /mcp call <server.tool> [json-args|message]")
            return "handled"
        try:
            result = mcp_runtime.call_tool(target, arguments)
        except Exception as exc:  # noqa: BLE001
            console.print(f"[Error] {exc}")
            return "handled"
        console.print(
            json.dumps(
                {
                    "tool": target,
                    "is_error": result.is_error,
                    "content": result.content,
                    "details": result.details,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return "handled"
    # 渲染会话分支树结构
    if raw.startswith("/tree"):
        parts = raw.split()
        sort_mode = "branch"
        view_mode = "default"
        focus_session_id = None
        index = 1
        while len(parts) > index:
            current = parts[index]
            if current in {"branch", "updated"}:
                sort_mode = current
            elif current in {"default", "full", "all"}:
                view_mode = "full" if current in {"full", "all"} else "default"
            elif current == "focus" and len(parts) >= index + 2:
                focus_session_id = parts[index + 1]
                index += 1
            else:
                focus_session_id = current
            index += 1
        if focus_session_id:
            try:
                focus_session_id, focus_turn_id = resolve_session_turn_ref(workspace, focus_session_id, current_session_id=agent.session_id)
                focus_session_id = f"{focus_session_id}@{focus_turn_id}" if focus_turn_id else focus_session_id
            except (FileNotFoundError, ValueError) as exc:
                console.print(f"[Error] {exc}")
                return "handled"
        # 调用渲染函数 → 在终端画出会话树（树形结构展示对话历史）
        render_session_tree(
            workspace,
            current_session_id=agent.session_id,
            current_agent=agent,
            focus_session_id=focus_session_id,
            sort_mode=sort_mode,
            view_mode=view_mode,
        )
        return "handled"
    # 基于指定会话创建分支副本
    if raw.startswith("/branch "):
        source_ref = raw.split(" ", 1)[1].strip()
        try:
            source_session_id, source_turn_id = resolve_session_turn_ref(workspace, source_ref, current_session_id=agent.session_id)
        except (FileNotFoundError, ValueError) as exc:
            console.print(f"[Error] {exc}")
            return "handled"
        new_session_id = branch_session(workspace, source_session_id, source_turn_id)
        source_label = f"{source_session_id}@{source_turn_id}" if source_turn_id else source_session_id
        console.print(f"Branched {source_label} -> {new_session_id}")
        return new_session_id
    # 按轮次回溯会话历史
    if raw.startswith("/rewind-turn "):
        parts = raw.split()
        try:
            if len(parts) == 2:
                source_session_id = agent.session_id
                turn_count = int(parts[1])
            elif len(parts) == 3:
                source_session_id = resolve_session_id(workspace, parts[1])
                turn_count = int(parts[2])
            else:
                raise ValueError
        except ValueError:
            console.print("Usage: /rewind-turn <turn_count> or /rewind-turn <session_id> <turn_count>")
            return "handled"
        try:
            new_session_id = rewind_session_turns(workspace, source_session_id, turn_count)
        except (FileNotFoundError, ValueError) as exc:
            console.print(f"[Error] {exc}")
            return "handled"
        console.print(f"Turn-rewound {source_session_id} at turn_count={turn_count} -> {new_session_id}")
        return new_session_id
    if raw.startswith("/rewind "):
        parts = raw.split()
        try:
            if len(parts) == 2:
                source_session_id = agent.session_id
                message_count = int(parts[1])
            elif len(parts) == 3:
                source_session_id = resolve_session_id(workspace, parts[1])
                message_count = int(parts[2])
            else:
                raise ValueError
        except ValueError:
            console.print("Usage: /rewind <message_count> or /rewind <session_id> <message_count>")
            return "handled"
        try:
            new_session_id = rewind_session(workspace, source_session_id, message_count)
        except (FileNotFoundError, ValueError) as exc:
            console.print(f"[Error] {exc}")
            return "handled"
        console.print(f"Rewound {source_session_id} at message_count={message_count} -> {new_session_id}")
        return new_session_id
    # 手动审批指定待执行令牌
    if raw.startswith("/approve "):
        token = raw.split(" ", 1)[1].strip()
        try:
            payload = load_pending_action_or_user_error(workspace, token)
        except ValueError as exc:
            console.print(str(exc))
            return "handled"
        if payload["action_type"] == "planner_approval":
            session_id = payload.get("details", {}).get("session_id")
            if session_id != agent.session_id:
                console.print(f"Planner token belongs to session {session_id}. Use /resume {session_id} first.")
                return "handled"
            agent.approve_pending_plan(token)
            console.print()
        else:
            approve_or_execute_pending_action(workspace, token, render=True, runtime=agent)
        return "handled"
    
    if raw.startswith("/reject "):
        token = raw.split(" ", 1)[1].strip()
        try:
            payload = load_pending_action_or_user_error(workspace, token)
        except ValueError as exc:
            console.print(str(exc))
            return "handled"
        if payload["action_type"] == "planner_approval":
            session_id = payload.get("details", {}).get("session_id")
            if session_id != agent.session_id:
                console.print(f"Planner token belongs to session {session_id}. Use /resume {session_id} first.")
                return "handled"
            agent.reject_pending_plan(token)
            console.print(f"Rejected planner approval {token}")
        else:
            reject_pending_action(workspace, token, render=True, runtime=agent)
        return "handled"
    # 动态切换当前大模型
    if raw.startswith("/model "):
        model = raw.split(" ", 2)[2].strip() if raw.startswith("/model set ") else raw.split(" ", 1)[1].strip()
        if not model:
            console.print("Usage: /model set <provider/model>")
            return "handled"
        model_set_main(workspace, agent.session_id, model, busy=bool(getattr(agent.state, "is_streaming", False)))
        manager = getattr(agent, "config_manager", None)
        if manager is not None:
            agent.config_snapshot = manager.get_effective_snapshot(session_id=agent.session_id)
            agent.config_version = getattr(agent.config_snapshot, "config_version", None)
        agent.llm_client.model.model = model
        agent.state.model.model = model
        return "handled"
    # 恢复切入指定历史会话
    if raw.startswith("/resume "):
        session_ref = raw.split(" ", 1)[1].strip()
        try:
            return resume_target(workspace, session_ref, current_session_id=agent.session_id)
        except (FileNotFoundError, ValueError) as exc:
            console.print(f"[Error] {exc}")
            return "handled"
    extension_commands = getattr(agent, "extension_commands", None)
    if extension_commands is not None:
        result = extension_commands.dispatch(raw, agent, workspace)
        if result is not None:
            return result
    # 普通对话消息标记，交给上层开线程执行
    return "run"


__all__ = ["handle_command", "handle_queue_command"]


def _parse_mcp_call(raw: str) -> tuple[str, dict[str, object]]:
    remainder = raw[len("/mcp call ") :].strip()
    if not remainder:
        return "", {}
    if " " not in remainder:
        return remainder, {}
    target, arg_text = remainder.split(" ", 1)
    arg_text = arg_text.strip()
    if not arg_text:
        return target, {}
    if arg_text.startswith("{"):
        payload = json.loads(arg_text)
        if not isinstance(payload, dict):
            raise ValueError("MCP call arguments must be a JSON object")
        return target, payload
    return target, {"message": arg_text}
