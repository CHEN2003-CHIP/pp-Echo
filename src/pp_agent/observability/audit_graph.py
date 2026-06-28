from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from pp_agent.observability.schema import TraceDetail

DUPLICATE_FINAL_ANSWER = "DUPLICATE_FINAL_ANSWER"
MISSING_TOOL_POLICY = "MISSING_TOOL_POLICY"
MISSING_PARENT_LINK = "MISSING_PARENT_LINK"
UNBUDGETED_CONTEXT_ITEM = "UNBUDGETED_CONTEXT_ITEM"
UNRELATED_BOT_DELIVERY = "UNRELATED_BOT_DELIVERY"
MISSING_RUN_LINK = "MISSING_RUN_LINK"


@dataclass(frozen=True)
class AuditNode:
    id: str
    kind: str
    run_id: str | None = None
    parent_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuditEdge:
    source: str
    target: str
    kind: str


@dataclass(frozen=True)
class AuditWarning:
    code: str
    message: str
    node_id: str | None = None
    run_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditGraph:
    nodes: list[AuditNode] = field(default_factory=list)
    edges: list[AuditEdge] = field(default_factory=list)
    warnings: list[AuditWarning] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def nodes_by_kind(self, kind: str) -> list[AuditNode]:
        return [node for node in self.nodes if node.kind == kind]

    def warning_codes(self) -> set[str]:
        return {warning.code for warning in self.warnings}

    def add_warning(
        self,
        code: str,
        message: str,
        *,
        node_id: str | None = None,
        run_id: str | None = None,
        legacy: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        self.warnings.append(
            AuditWarning(
                code=code,
                message=message,
                node_id=node_id,
                run_id=run_id,
                attributes=attributes or {},
            )
        )
        self.violations.append(legacy or message)


def build_audit_graph(detail: TraceDetail, *, bot_traces: Iterable[dict[str, Any]] | None = None) -> AuditGraph:
    """Build a replay-oriented audit graph from existing trace records.

    The builder is intentionally observational: it never re-runs the model or tools.
    It links the user turn, context/memory, policy, tools, final answer, and bot
    delivery records that already exist in TraceStore/Bot Center data.
    """

    graph = AuditGraph()
    run = detail.run
    run_id = run.run_id if run is not None else _first_run_id(detail)
    session_id = run.session_id if run is not None else _first_session_id(detail)
    previous_id: str | None = None

    if run is None:
        graph.add_warning(MISSING_RUN_LINK, "Trace detail is missing a run record.", legacy="missing_run_record")
    else:
        user_id = f"user.message:{run.run_id}"
        graph.nodes.append(
            AuditNode(
                id=user_id,
                kind="user.message",
                run_id=run.run_id,
                attributes={
                    "session_id": run.session_id,
                    "profile_id": run.attributes.get("profile_id", "default"),
                    "channel_id": run.attributes.get("channel_id"),
                    "preview": run.user_goal_preview,
                },
            )
        )
        previous_id = user_id

    context_nodes: list[str] = []
    for span in detail.spans:
        if span.name == "memory.recall":
            node_id = f"memory.lookup:{span.span_id}"
            graph.nodes.append(AuditNode(id=node_id, kind="memory.lookup", run_id=span.run_id, parent_id=previous_id, attributes=span.output))
            _link(graph, previous_id, node_id, "feeds")
            context_nodes.append(node_id)
        if span.name == "context.build":
            node_id = f"context.item:{span.span_id}"
            context = span.output.get("context") if isinstance(span.output.get("context"), dict) else {}
            graph.nodes.append(AuditNode(id=node_id, kind="context.item", run_id=span.run_id, parent_id=previous_id, attributes=context))
            _link(graph, previous_id, node_id, "feeds")
            context_nodes.append(node_id)
            _check_context_budget(graph, context)

    policy_by_call: dict[str, str] = {}
    for span in detail.spans:
        if span.name != "policy.decision":
            continue
        tool_call_id = str(span.attributes.get("tool_call_id") or span.attributes.get("source_tool_call_id") or span.attributes.get("call_id") or "")
        tool_name = str(span.attributes.get("tool_name") or span.attributes.get("source_tool_name") or "")
        key = tool_call_id or tool_name
        node_id = f"tool.policy:{span.span_id}"
        graph.nodes.append(AuditNode(id=node_id, kind="tool.policy", run_id=span.run_id, parent_id=_last(context_nodes, previous_id), attributes=span.attributes))
        _link(graph, _last(context_nodes, previous_id), node_id, "authorizes")
        if key:
            policy_by_call[key] = node_id

    tool_nodes: list[str] = []
    for span in detail.spans:
        if span.name != "tool.call":
            continue
        tool_call_id = str(span.attributes.get("tool_call_id") or "")
        tool_name = str(span.attributes.get("tool_name") or "")
        key = tool_call_id or tool_name
        node_id = f"tool.call:{span.span_id}"
        graph.nodes.append(AuditNode(id=node_id, kind="tool.call", run_id=span.run_id, parent_id=policy_by_call.get(key), attributes={**span.attributes, "status": span.status}))
        if key and key in policy_by_call:
            _link(graph, policy_by_call[key], node_id, "permits")
        else:
            graph.add_warning(
                MISSING_TOOL_POLICY,
                "Tool call has no preceding policy decision.",
                node_id=node_id,
                run_id=span.run_id,
                legacy=f"tool_without_policy:{tool_name or tool_call_id or span.span_id}",
                attributes={"tool_name": tool_name, "tool_call_id": tool_call_id},
            )
        tool_nodes.append(node_id)
        result_id = f"tool.result:{span.span_id}"
        graph.nodes.append(AuditNode(id=result_id, kind="tool.result", run_id=span.run_id, parent_id=node_id, attributes=span.output))
        _link(graph, node_id, result_id, "produces")

    final_spans = [span for span in detail.spans if span.name == "final.answer"]
    if len(final_spans) > 1:
        graph.add_warning(DUPLICATE_FINAL_ANSWER, "Trace contains more than one final answer.", legacy="duplicate_final_answer")
    for span in final_spans:
        node_id = f"final.answer:{span.span_id}"
        graph.nodes.append(AuditNode(id=node_id, kind="final.answer", run_id=span.run_id, parent_id=_last(tool_nodes, _last(context_nodes, previous_id)), attributes=span.attributes))
        _link(graph, _last(tool_nodes, _last(context_nodes, previous_id)), node_id, "answers")

    final_id = _last([node.id for node in graph.nodes if node.kind == "final.answer"], None)
    for trace in bot_traces or []:
        delivery_run_id = trace.get("runtime_trace_run_id")
        node_id = f"bot.delivery:{trace.get('trace_id') or trace.get('run_id') or len(graph.nodes)}"
        graph.nodes.append(AuditNode(id=node_id, kind="bot.delivery", run_id=str(delivery_run_id or ""), parent_id=trace.get("parent_id"), attributes=dict(trace)))
        _link(graph, final_id, node_id, "delivers")
        if delivery_run_id != run_id or trace.get("parent_id") != run_id:
            graph.add_warning(
                UNRELATED_BOT_DELIVERY,
                "Bot delivery is not linked to the runtime trace run.",
                node_id=node_id,
                run_id=str(delivery_run_id or ""),
                legacy="bot_delivery_unlinked_runtime_run",
            )
        if session_id and trace.get("session_id") not in {None, session_id}:
            graph.add_warning(
                UNRELATED_BOT_DELIVERY,
                "Bot delivery session does not match the runtime session.",
                node_id=node_id,
                run_id=str(delivery_run_id or ""),
                legacy="bot_delivery_session_mismatch",
            )

    _check_parent_linkage(graph, run_id)
    return graph


def _check_context_budget(graph: AuditGraph, context: dict[str, Any]) -> None:
    budget = context.get("budget_report") if isinstance(context.get("budget_report"), dict) else {}
    if not budget:
        return
    for item in budget.get("included_items") or []:
        if not isinstance(item, dict):
            continue
        if "estimated_chars" not in item:
            graph.add_warning(
                UNBUDGETED_CONTEXT_ITEM,
                "Context item is included without budget metadata.",
                legacy=f"unbudgeted_context_item:{item.get('id', 'unknown')}",
                attributes={"context_item_id": item.get("id", "unknown")},
            )


def _check_parent_linkage(graph: AuditGraph, run_id: str | None) -> None:
    if not run_id:
        graph.add_warning(MISSING_RUN_LINK, "Audit graph cannot determine a runtime run id.", legacy="missing_run_linkage")
        return
    for node in graph.nodes:
        if node.kind == "user.message":
            continue
        if node.run_id and node.run_id != run_id:
            graph.add_warning(
                MISSING_RUN_LINK,
                "Audit node is linked to a different runtime run.",
                node_id=node.id,
                run_id=node.run_id,
                legacy=f"run_linkage_mismatch:{node.kind}",
            )
        if node.kind not in {"bot.delivery"} and node.parent_id is None:
            graph.add_warning(
                MISSING_PARENT_LINK,
                "Audit node is missing parent linkage.",
                node_id=node.id,
                run_id=node.run_id,
                legacy=f"missing_parent_id:{node.kind}",
                attributes={"kind": node.kind},
            )


def _first_run_id(detail: TraceDetail) -> str | None:
    for span in detail.spans:
        return span.run_id
    for event in detail.events:
        return event.run_id
    return None


def _first_session_id(detail: TraceDetail) -> str | None:
    for span in detail.spans:
        return span.session_id
    for event in detail.events:
        return event.session_id
    return None


def _link(graph: AuditGraph, source: str | None, target: str, kind: str) -> None:
    if source:
        graph.edges.append(AuditEdge(source=source, target=target, kind=kind))


def _last(values: list[str], fallback: str | None) -> str | None:
    return values[-1] if values else fallback
