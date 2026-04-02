from __future__ import annotations

from collections.abc import Callable

from pp_agent.runtime.state import AgentEvent


LifecycleSubscriber = Callable[[AgentEvent], None]
