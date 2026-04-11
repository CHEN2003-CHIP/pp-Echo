from importlib import import_module

__all__ = [
    "PendingActionStore",
    "SessionRecord",
    "SessionStore",
    "Settings",
    "TimelineEntry",
    "TimelineStore",
    "ToolPolicyConfig",
]


def __getattr__(name: str):
    if name == "PendingActionStore":
        module = import_module("pp_agent.storage.approvals")
        return getattr(module, name)
    if name in {"SessionRecord", "SessionStore"}:
        module = import_module("pp_agent.storage.sessions")
        return getattr(module, name)
    if name in {"Settings", "ToolPolicyConfig"}:
        module = import_module("pp_agent.storage.settings")
        return getattr(module, name)
    if name in {"TimelineEntry", "TimelineStore"}:
        module = import_module("pp_agent.storage.timeline")
        return getattr(module, name)
    raise AttributeError(name)
