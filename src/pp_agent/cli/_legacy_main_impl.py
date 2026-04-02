"""legacy compatibility shim; do not add new logic"""

from pp_agent.app.bootstrap import (
    build_agent,
    confirm_tool_call,
    create_session_store,
    create_tool_registry,
    load_settings,
    pending_action_store_for,
    session_store_for,
    timeline_store_for,
)
from pp_agent.cli.chat import chat_main, handle_command
from pp_agent.cli.commands.approvals import (
    approve_or_execute_pending_action,
    approvals_approve_all_main,
    approvals_approve_main,
    approvals_list_main,
    approvals_reject_all_main,
    approvals_reject_main,
    approvals_show_main,
    approvals_summary_main,
    load_pending_action,
    reject_pending_action,
)
from pp_agent.cli.commands.config import config_show_main
from pp_agent.cli.commands.run import run_main
from pp_agent.cli.commands.sessions import (
    branch_session,
    resolve_session_id,
    resolve_session_turn_ref,
    resolve_turn_id,
    resume_target,
    rewind_session,
    rewind_session_turns,
    sessions_fork_main,
    sessions_list_main,
    sessions_rewind_main,
    sessions_rewind_turn_main,
    sessions_tree_main,
    split_session_turn_ref,
)
from pp_agent.cli.commands.timeline import timeline_show_main
from pp_agent.cli.commands.workflow import workflow_repo_main
from pp_agent.cli.dispatcher import handle_queue_command
from pp_agent.cli.main import app, main
from pp_agent.cli.render.approvals import (
    action_target,
    approval_preview,
    approvals_summary_payload,
    render_approval_panel,
    short_token,
)
from pp_agent.cli.render.queue import render_queue_panel
from pp_agent.cli.render.runtime import (
    PLAN_MARKERS,
    RICH_AVAILABLE,
    RUNTIME_MONITOR,
    compact_text,
    console,
    format_plan_step,
    format_runtime_status,
    render_event,
    render_runtime_status,
    render_settings,
)
from pp_agent.cli.render.sessions import (
    print_tree_lines,
    render_session_tree,
    render_tree_entry_preview,
    render_turn_entry_preview,
    short_session,
    short_turn,
    tree_style_for,
)
from pp_agent.cli.render.timeline import render_timeline

__all__ = [name for name in globals() if not name.startswith("_")]
