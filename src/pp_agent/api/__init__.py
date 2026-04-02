from __future__ import annotations

from pp_agent.api import sdk


def run(*args, **kwargs):
    return sdk.run(*args, **kwargs)


def chat(*args, **kwargs):
    return sdk.chat(*args, **kwargs)


def create_runtime(*args, **kwargs):
    return sdk.create_runtime(*args, **kwargs)


def create_session(*args, **kwargs):
    return sdk.create_session(*args, **kwargs)


def restore_session(*args, **kwargs):
    return sdk.restore_session(*args, **kwargs)


def continue_session(*args, **kwargs):
    return sdk.continue_session(*args, **kwargs)


def enqueue_message(*args, **kwargs):
    return sdk.enqueue_message(*args, **kwargs)


def list_sessions(*args, **kwargs):
    return sdk.list_sessions(*args, **kwargs)


def get_session_tree(*args, **kwargs):
    return sdk.get_session_tree(*args, **kwargs)


def sessions_tree(*args, **kwargs):
    return sdk.get_session_tree(*args, **kwargs)


def fork_session(*args, **kwargs):
    return sdk.fork_session(*args, **kwargs)


def rewind_session(*args, **kwargs):
    return sdk.rewind_session(*args, **kwargs)


def create_checkpoint(*args, **kwargs):
    return sdk.create_checkpoint(*args, **kwargs)


def list_checkpoints(*args, **kwargs):
    return sdk.list_checkpoints(*args, **kwargs)


def preview_rewind(*args, **kwargs):
    return sdk.preview_rewind(*args, **kwargs)


def rewind_safe(*args, **kwargs):
    return sdk.rewind_safe(*args, **kwargs)


def approvals_summary(*args, **kwargs):
    return sdk.approvals_summary(*args, **kwargs)


def subscribe(*args, **kwargs):
    return sdk.subscribe(*args, **kwargs)


__all__ = [
    "approvals_summary",
    "chat",
    "continue_session",
    "create_checkpoint",
    "create_runtime",
    "create_session",
    "enqueue_message",
    "fork_session",
    "get_session_tree",
    "list_checkpoints",
    "list_sessions",
    "preview_rewind",
    "restore_session",
    "rewind_session",
    "rewind_safe",
    "run",
    "sessions_tree",
    "subscribe",
]
