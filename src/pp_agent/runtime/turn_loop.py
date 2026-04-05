from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pp_agent.domain import QueuedMessage
from pp_agent.runtime.state import AgentState


@dataclass
class TurnDecision:
    action: str
    queued_message: Optional[QueuedMessage] = None
    reason: str = ""
    phase: str = "idle"


class TurnController:
    #每一个回合刚开始时
    def on_turn_start(self, state: AgentState) -> TurnDecision:
        return TurnDecision(action="continue", reason="turn_start", phase="planning")

    #收到「继续执行」的请求时（核心调度方法）
    def on_continue_request(self, state: AgentState, next_message: Optional[QueuedMessage]) -> TurnDecision:
        if state.pending_tool_calls or state.pending_plan_token:
            return TurnDecision(action="resume_current", reason="pending_state", phase="executing")
        if next_message is not None:
            return TurnDecision(action="inject_message", queued_message=next_message, reason=f"queued_{next_message.delivery}", phase="draining_queue")
        return TurnDecision(action="resume_current", reason="no_queue", phase="planning")

    #Agent 生成计划后、计划被批准前
    def before_plan_approval(self) -> TurnDecision:
        return TurnDecision(action="pause", reason="planner_approval", phase="awaiting_approval")

    #工具即将执行前（计划审批通过后）
    def before_tool_execution(self) -> TurnDecision:
        return TurnDecision(action="continue", reason="tool_execution", phase="executing")

    #AI 助手回合结束后（AI 给用户回复完消息后）
    def after_assistant_turn(self, next_message: Optional[QueuedMessage]) -> TurnDecision:
        if next_message is not None:
            return TurnDecision(action="inject_message", queued_message=next_message, reason=f"queued_{next_message.delivery}", phase="draining_queue")
        return TurnDecision(action="stop", reason="idle", phase="idle")

    #工具执行轮次结束后（工具运行完成 / 失败后）
    def after_tool_round(
        self,
        *,
        tool_failed: bool,
        continue_after_error: bool,
        steering_message: Optional[QueuedMessage],
    ) -> TurnDecision:
        if not tool_failed and steering_message is not None:
            return TurnDecision(action="inject_message", queued_message=steering_message, reason="post_turn_steering", phase="draining_queue")
        if tool_failed and not continue_after_error:
            return TurnDecision(action="stop", reason="tool_error", phase="idle")
        return TurnDecision(action="continue", reason="continue_loop", phase="planning")

    #回合最终结束时
    def on_turn_end(self) -> TurnDecision:
        return TurnDecision(action="stop", reason="turn_end", phase="idle")
