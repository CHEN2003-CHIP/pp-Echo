from __future__ import annotations

import logging
import time

from pp_agent.subagents.blackboard import Blackboard
from pp_agent.subagents.task_graph import TaskNode, WorkflowTemplate


logger = logging.getLogger(__name__)


class DeterministicScheduler:
    def __init__(self, template: WorkflowTemplate) -> None:
        self.template = template
        self._nodes = {node.id: node.model_copy(deep=True) for node in template.nodes}

    def node(self, node_id: str) -> TaskNode:
        return self._nodes[node_id]

    def runnable_batches(self) -> list[list[TaskNode]]:
        batches: list[list[TaskNode]] = []
        completed: set[str] = set()
        remaining = dict(self._nodes)
        while remaining:
            ready = [
                node
                for node in remaining.values()
                if all(dep in completed for dep in node.depends_on)
            ]
            if not ready:
                break
            batches.append([node.model_copy(deep=True) for node in ready])
            for node in ready:
                completed.add(node.id)
                remaining.pop(node.id, None)
        return batches

    def should_skip(self, node: TaskNode, blackboard: Blackboard) -> tuple[bool, str]:
        if node.id == "code_patch":
            planner = blackboard.get("implementation_plan")
            if planner is not None and planner.status != "success":
                return True, "implementation-planner did not succeed; skipping code-worker."
        failed_dependencies = [
            dep
            for dep in node.depends_on
            if blackboard.get(dep) is not None and blackboard.get(dep).status not in {"success"}
        ]
        if failed_dependencies and node.id != "change_review":
            return True, f"dependency failed: {', '.join(failed_dependencies)}"
        return False, ""

    def task_note(self, node: TaskNode, blackboard: Blackboard) -> str:
        if node.id == "change_review":
            patch = blackboard.get("code_patch")
            if patch is not None and patch.status != "success":
                return "Review the failed code-worker state and the current diff; do not assume a successful patch exists."
        return ""

    @staticmethod
    def mark_started(node: TaskNode) -> None:
        node.status = "running"
        node.attempt += 1
        node.started_at = time.time()
        logger.debug("workflow node started", extra={"node_id": node.id, "agent": node.agent})

    @staticmethod
    def mark_completed(node: TaskNode, status: str) -> None:
        node.status = status
        node.completed_at = time.time()
        logger.debug("workflow node completed", extra={"node_id": node.id, "agent": node.agent, "status": status})

    @staticmethod
    def mark_skipped(node: TaskNode, reason: str) -> None:
        node.status = "skipped"
        node.completed_at = time.time()
        node.skip_reason = reason
        logger.debug("workflow node skipped", extra={"node_id": node.id, "agent": node.agent, "reason": reason})


__all__ = ["DeterministicScheduler"]
