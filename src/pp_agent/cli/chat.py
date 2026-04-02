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
from pp_agent.cli.render.runtime import console, render_event, render_runtime_status


def build_agent(workspace: Path, session_id: Optional[str] = None):
    return create_chat_runtime(workspace, session_id=session_id)


def chat_main(workspace: Path, session_id: Optional[str] = None) -> None:
    prompt_session = None
    if PromptSession:
        try:
            prompt_session = PromptSession()
        except Exception:
            prompt_session = None
    while True:
        agent = build_agent(workspace, session_id=session_id)
        agent.subscribe(render_event)
        worker: Optional[threading.Thread] = None

        def is_busy() -> bool:
            return worker is not None and worker.is_alive()

        def start_worker(action: str, fn) -> None:
            nonlocal worker

            def runner() -> None:
                try:
                    fn()
                finally:
                    console.print()

            worker = threading.Thread(target=runner, name=f"pp-agent-{action}", daemon=True)
            worker.start()

        console.print(f"pp-agent session={agent.session_id} model={agent.llm_client.model.model}")
        if agent.state.pending_plan_token:
            console.print(
                f"Pending planner gate: {agent.state.pending_plan_token}. "
                f"Use /approve {agent.state.pending_plan_token} or /reject {agent.state.pending_plan_token}."
            )
        if agent.state.queued_messages:
            console.print(f"Queued messages: {len(agent.state.queued_messages)}. Use /queue to inspect them.")
        render_runtime_status(agent)
        console.print(
            "Tips: /status shows runtime state. Plain text while busy becomes follow-up queue. "
            "Use /queue steering <msg> for higher-priority guidance."
        )

        while True:
            try:
                raw = prompt_session.prompt("\n> ").strip() if prompt_session else input("\n> ").strip()
            except EOFError:
                return
            if not raw:
                continue

            if raw.startswith("/queue"):
                handle_queue_command(agent, raw)
                if not is_busy() and not agent.state.pending_plan_token and agent.state.queued_messages:
                    start_worker("queue", agent.continue_)
                continue

            if is_busy():
                if raw.startswith("/"):
                    if raw in {"/session", "/settings", "/status", "/approvals", "/timeline"} or raw.startswith("/tree"):
                        result = handle_command(agent, raw, workspace)
                        if result == "quit":
                            console.print("Wait for the current task to finish before quitting.")
                        continue
                    console.print("Agent is busy. Use /queue steering <message>, /queue, or wait for the current task to finish.")
                    continue
                agent.enqueue_message(raw, delivery="follow_up")
                continue

            if agent.state.pending_plan_token and raw.strip().lower() in {"approve", "yes", "??", "??"}:
                token = agent.state.pending_plan_token
                start_worker("approve", lambda: agent.approve_pending_plan(token))
                continue

            if agent.state.pending_plan_token and raw.strip().lower() in {"reject", "no", "??"}:
                token = agent.state.pending_plan_token
                result = handle_command(agent, f"/reject {token}", workspace)
                if result == "quit":
                    return
                if result == "new":
                    session_id = None
                    break
                if result != "handled":
                    session_id = result
                    break
                continue

            if raw.startswith("/approve "):
                token = raw.split(" ", 1)[1].strip()
                payload = load_pending_action(workspace, token)
                if payload["action_type"] == "planner_approval":
                    session_for_token = payload.get("details", {}).get("session_id")
                    if session_for_token != agent.session_id:
                        console.print(f"Planner token belongs to session {session_for_token}. Use /resume {session_for_token} first.")
                        continue
                    start_worker("approve", lambda: agent.approve_pending_plan(token))
                else:
                    approve_or_execute_pending_action(workspace, token, render=True)
                continue

            if raw.startswith("/reject "):
                result = handle_command(agent, raw, workspace)
                if result == "quit":
                    return
                if result == "new":
                    session_id = None
                    break
                if result != "handled":
                    session_id = result
                    break
                continue

            if raw.startswith("/"):
                result = handle_command(agent, raw, workspace)
                if result == "handled":
                    continue
                if result == "quit":
                    if is_busy():
                        console.print("Wait for the current task to finish before quitting.")
                        continue
                    return
                if result == "new":
                    if is_busy():
                        console.print("Wait for the current task to finish before creating a new session.")
                        continue
                    session_id = None
                    break
                if result != "run":
                    if is_busy():
                        console.print("Wait for the current task to finish before switching sessions.")
                        continue
                    session_id = result
                    break

            start_worker("prompt", lambda value=raw: agent.prompt(value))


__all__ = ["chat_main", "handle_command"]
