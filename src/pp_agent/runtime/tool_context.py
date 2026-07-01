from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pp_agent.runtime.execution_context import RuntimeExecutionContext, runtime_execution_context_to_dict


@dataclass
class ToolExecutionContext:
    """Optional runtime context carried by tool execution without depending on coding.

    ToolRegistry and tools can read or update the contained RuntimeExecutionContext to enforce
    session-level guardrails. A missing runtime_execution_context means legacy flow skipped the
    guardrail checks; this context does not replace ToolPolicy, approval, sandbox, or payload
    digests.
    """

    runtime_execution_context: RuntimeExecutionContext | None = None


def tool_execution_context_to_dict(context: ToolExecutionContext | None) -> dict[str, Any] | None:
    """Serialize ToolExecutionContext for trace-safe details and tests.

    The helper is JSON-friendly and keeps tools on runtime contracts rather than coding contracts.
    It only reports optional guardrail context; it does not execute or approve tools.
    """

    if context is None:
        return None
    return {
        "runtime_execution_context": runtime_execution_context_to_dict(context.runtime_execution_context),
    }
