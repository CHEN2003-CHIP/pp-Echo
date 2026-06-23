from __future__ import annotations

from pathlib import Path
from typing import Any

from pp_agent.memory.core_renderer import CoreMemoryBudget, CoreMemoryRenderer, workspace_id_for_path
from pp_agent.memory.core_store import CoreMemoryStore
from pp_agent.memory.core_service import CoreMemoryService, service_for_workspace
from pp_agent.memory.core_types import CoreMemoryCandidate, CoreMemorySource
from pp_agent.tools.base import BaseTool, ToolExecutionResult
from pp_agent.domain import ToolSpec
from pp_agent.tools.policy import PermissionDomain


def core_memory_store_for_settings(settings) -> CoreMemoryStore:
    return CoreMemoryStore(settings.core_memory_db_path(), busy_timeout_ms=settings.memory.sqlite_busy_timeout_ms)


def candidate_from_arguments(arguments: dict[str, Any], *, workspace: Path) -> CoreMemoryCandidate:
    source_payload = dict(arguments.get("source") or {})
    metadata = dict(arguments.get("metadata") or {})
    if arguments.get("reason"):
        metadata["reason"] = str(arguments["reason"])
    return CoreMemoryCandidate(
        scope=str(arguments.get("scope") or "workspace"),  # type: ignore[arg-type]
        workspace_id=str(arguments.get("workspace_id") or workspace_id_for_path(workspace)),
        section=str(arguments.get("section") or "project_profile"),  # type: ignore[arg-type]
        type=str(arguments.get("type") or "general"),  # type: ignore[arg-type]
        content=str(arguments.get("content") or ""),
        source=CoreMemorySource(**source_payload),
        confidence=float(arguments.get("confidence", 0.5)),
        metadata=metadata,
    )


class CoreMemoryBaseTool(BaseTool):
    def __init__(self, workspace: Path, policy_evaluator=None, *, settings=None) -> None:
        super().__init__(workspace, policy_evaluator)
        if settings is None:
            from pp_agent.storage.settings import Settings

            settings = Settings.load(workspace)
        self.settings = settings
        self.store = core_memory_store_for_settings(settings)
        self.service = service_for_workspace(self.workspace, settings)
        self.workspace_id = workspace_id_for_path(workspace)

    def _result(self, content: str, details: dict[str, object], *, is_error: bool = False) -> ToolExecutionResult:
        return ToolExecutionResult(tool_call_id="", tool_name=self.spec.name, content=content, is_error=is_error, details=details)


class MemoryProposeTool(CoreMemoryBaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="memory_propose",
            description="Create a pending governed memory candidate and preview the Markdown patch that approval would apply.",
            parameters=_candidate_schema(required=("content",)),
            permission_domain=PermissionDomain.READ,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        candidate = candidate_from_arguments(arguments, workspace=self.workspace)
        result = self.service.propose(
            candidate,
            actor="tool",
            reason=str(arguments.get("reason") or ""),
            explicit_user_memory=bool(arguments.get("explicit_user_memory", False)),
        )
        memory = result.memory
        return self._result(
            f"{memory.status}: {memory.id} [{memory.scope}/{memory.section}] {memory.content}",
            {
                "memory": memory.model_dump(mode="python"),
                "warnings": result.warnings,
                "duplicate_of": result.duplicate_of,
                "safety": result.safety,
                "conflicts_with": result.conflicts_with,
                "budget": result.budget,
                "audit": result.audit,
                "markdown": result.markdown,
                "immediate_effect": result.immediate_effect,
            },
        )


class MemoryPendingTool(CoreMemoryBaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="memory_pending",
            description="List pending core memory candidates with provenance, reason, and conflicts.",
            parameters={"type": "object", "properties": {"scope": {"type": "string"}, "workspace_id": {"type": "string"}}},
            permission_domain=PermissionDomain.READ,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        memories = self.service.store.list_pending(scope=arguments.get("scope"), workspace_id=arguments.get("workspace_id") or self.workspace_id)
        lines = [self._line(memory) for memory in memories]
        return self._result("\n".join(lines) if lines else "No pending core memory.", {"memories": [m.model_dump(mode="python") for m in memories]})

    @staticmethod
    def _line(memory) -> str:
        reason = memory.metadata.get("reason") or ""
        conflicts = memory.metadata.get("conflicts_with") or []
        return f"{memory.id} [{memory.scope}/{memory.section}/{memory.type}] {memory.content} reason={reason} conflicts_with={conflicts}"


class MemoryApproveTool(CoreMemoryBaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="memory_approve",
            description="Approve a pending governed memory and write it to Markdown memory by default for the next model turn.",
            parameters={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string"},
                    "apply_to_markdown": {"type": "boolean", "default": True},
                    "reason": {"type": "string"},
                },
                "required": ["memory_id"],
            },
            requires_confirmation=True,
            permission_domain=PermissionDomain.APPROVAL,
            model_callable=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        result = self.service.approve(
            str(arguments["memory_id"]),
            actor="tool",
            reason=str(arguments.get("reason") or ""),
            apply_to_markdown=bool(arguments.get("apply_to_markdown", True)),
            immediate_effect=True,
        )
        memory = result.memory
        target = result.markdown.get("target", {}) if isinstance(result.markdown, dict) else {}
        path = target.get("path") if isinstance(target, dict) else None
        heading = target.get("heading") if isinstance(target, dict) else None
        message = "This memory has been written to Markdown memory and will affect the next model turn." if result.immediate_effect else "Memory approved as governance record."
        return self._result(
            f"approved/applied: {memory.id} [{memory.scope}/{memory.section}] {memory.content}\n{message}",
            {
                "memory": memory.model_dump(mode="python"),
                "warnings": result.warnings,
                "budget": result.budget,
                "audit": result.audit,
                "markdown": result.markdown,
                "target_file": path,
                "heading": heading,
                "immediate_effect": result.immediate_effect,
                "message": message,
            },
        )


class MemoryRejectTool(CoreMemoryBaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="memory_reject",
            description="Reject a pending or active core memory.",
            parameters={"type": "object", "properties": {"memory_id": {"type": "string"}}, "required": ["memory_id"]},
            requires_confirmation=True,
            permission_domain=PermissionDomain.APPROVAL,
            model_callable=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        result = self.service.reject(str(arguments["memory_id"]), actor="tool")
        memory = result.memory
        return self._result(f"rejected: {memory.id} [{memory.scope}/{memory.section}] {memory.content}", {"memory": memory.model_dump(mode="python"), "audit": result.audit})


class MemoryArchiveTool(CoreMemoryBaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="memory_archive",
            description="Archive an active core memory so it is no longer injected.",
            parameters={"type": "object", "properties": {"memory_id": {"type": "string"}}, "required": ["memory_id"]},
            requires_confirmation=True,
            permission_domain=PermissionDomain.APPROVAL,
            model_callable=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        result = self.service.archive(str(arguments["memory_id"]), actor="tool")
        memory = result.memory
        return self._result(f"archived: {memory.id} [{memory.scope}/{memory.section}] {memory.content}", {"memory": memory.model_dump(mode="python"), "audit": result.audit})


class MemoryReplaceTool(CoreMemoryBaseTool):
    @property
    def spec(self) -> ToolSpec:
        schema = _candidate_schema(required=("old_memory_id", "content"))
        schema["properties"]["old_memory_id"] = {"type": "string"}
        return ToolSpec(
            name="memory_replace",
            description="Replace an old core memory with a new active memory while archiving the old one.",
            parameters=schema,
            requires_confirmation=True,
            permission_domain=PermissionDomain.APPROVAL,
            model_callable=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        candidate = candidate_from_arguments(arguments, workspace=self.workspace)
        result = self.service.replace(str(arguments["old_memory_id"]), candidate, actor="tool")
        memory = result.memory
        return self._result(f"replaced: {arguments['old_memory_id']} -> {memory.id}", {"memory": memory.model_dump(mode="python"), "warnings": result.warnings, "budget": result.budget, "audit": result.audit})


class MemorySnapshotTool(CoreMemoryBaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="memory_snapshot",
            description="Preview the debug-only SQLite governance snapshot. Markdown memory is the default prompt fact source.",
            parameters={"type": "object", "properties": {"workspace_id": {"type": "string"}}},
            permission_domain=PermissionDomain.READ,
            model_callable=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        workspace_id = str(arguments.get("workspace_id") or self.workspace_id)
        result = self.service.snapshot(workspace_id=workspace_id)
        payload = result.model_dump(mode="python")
        payload["debug_only"] = True
        payload["sqlite_governance_snapshot"] = True
        return self._result(result.snapshot or "No active governed core memory.", payload)


class MemoryAuditTool(CoreMemoryBaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="memory_audit",
            description="List Core Memory audit records for all memories or a single memory id.",
            parameters={"type": "object", "properties": {"memory_id": {"type": "string"}, "limit": {"type": "integer"}}},
            permission_domain=PermissionDomain.READ,
            model_callable=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        records = self.service.audit(memory_id=arguments.get("memory_id"), limit=int(arguments.get("limit") or 100))
        lines = [f"{record.created_at:.0f} {record.action} {record.memory_id} {record.before_status}->{record.after_status} {record.reason}" for record in records]
        return self._result("\n".join(lines) if lines else "No core memory audit records.", {"audit": [record.model_dump(mode="python") for record in records]})


class MemoryCompactPreviewTool(CoreMemoryBaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="memory_compact_preview",
            description="Preview Core Memory budget pressure and suggested explicit cleanup actions without changing memory.",
            parameters={"type": "object", "properties": {"workspace_id": {"type": "string"}}},
            permission_domain=PermissionDomain.READ,
            model_callable=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        payload = self.service.compact_preview(workspace_id=arguments.get("workspace_id") or self.workspace_id)
        return self._result(str(payload.get("recommendation") or "No compaction needed."), payload)


class MemoryCompactApplyTool(CoreMemoryBaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="memory_compact_apply",
            description="Record a Core Memory compaction request. This version does not auto-compress or auto-delete memory.",
            parameters={"type": "object", "properties": {"reason": {"type": "string"}}},
            requires_confirmation=True,
            permission_domain=PermissionDomain.APPROVAL,
            model_callable=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        payload = self.service.compact_apply(actor="tool", reason=str(arguments.get("reason") or "manual_compaction"))
        return self._result(str(payload.get("message") or "Compaction request recorded."), payload)


class MemoryMergePreviewTool(CoreMemoryBaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="memory_merge_preview",
            description="Preview duplicate Core Memory groups that can be merged into pending replacement candidates.",
            parameters={"type": "object", "properties": {}},
            permission_domain=PermissionDomain.READ,
            model_callable=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        payload = self.service.merge_preview()
        return self._result(f"{payload.get('mergeable_group_count', 0)} mergeable group(s).", payload)


class MemoryMergeApplyTool(CoreMemoryBaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="memory_merge_apply",
            description="Create pending Core Memory merge candidates. Source memories are archived only after approval.",
            parameters={"type": "object", "properties": {"reason": {"type": "string"}}},
            requires_confirmation=True,
            permission_domain=PermissionDomain.APPROVAL,
            model_callable=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        payload = self.service.merge_apply(actor="tool", reason=str(arguments.get("reason") or "auto_merge"))
        return self._result(f"Created {len(payload.get('generated', []))} pending merge candidate(s).", payload)


class MemoryProviderStatusTool(CoreMemoryBaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="memory_provider_status",
            description="Show additive Core Memory provider status.",
            parameters={"type": "object", "properties": {}},
            permission_domain=PermissionDomain.READ,
            model_callable=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        payload = self.service.provider.status()
        return self._result(str(payload), payload)


class MemoryExportToMarkdownTool(CoreMemoryBaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="memory_export_to_markdown",
            description="Export active SQLite governed memories that have not yet been written to Markdown memory.",
            parameters={"type": "object", "properties": {"reason": {"type": "string"}}},
            requires_confirmation=True,
            permission_domain=PermissionDomain.APPROVAL,
            model_callable=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        payload = self.service.export_active_core_memories_to_markdown(actor="tool", reason=str(arguments.get("reason") or "manual_export"))
        return self._result(f"Exported {len(payload.get('exported', []))} active memory item(s) to Markdown.", payload)


def register_core_memory_tools(registry, *, settings) -> None:
    from pp_agent.tools.metadata import ToolMetadata
    from pp_agent.tools.registry import ToolRegistration

    tool_classes = [
        MemoryProposeTool,
        MemoryPendingTool,
        MemoryApproveTool,
        MemoryRejectTool,
        MemoryArchiveTool,
        MemoryReplaceTool,
        MemorySnapshotTool,
        MemoryAuditTool,
        MemoryCompactPreviewTool,
        MemoryCompactApplyTool,
        MemoryMergePreviewTool,
        MemoryMergeApplyTool,
        MemoryProviderStatusTool,
        MemoryExportToMarkdownTool,
    ]
    for cls in tool_classes:
        factory = lambda cls=cls: cls(registry.workspace, registry.policy_evaluator, settings=settings)
        spec = factory().spec
        registry.register(
            ToolRegistration(
                name=spec.name,
                category="memory",
                spec_factory=lambda spec=spec: spec.model_copy(deep=True),
                tool_factory=factory,
                metadata=ToolMetadata(
                    name=spec.name,
                    category="memory",
                    requires_confirmation=spec.requires_confirmation,
                    permission_domain=spec.permission_domain,
                    sensitive=spec.sensitive,
                    model_callable=spec.model_callable,
                    tool_family="memory",
                    exact_effect_mode="none",
                ),
            ),
            replace=True,
        )


def _candidate_schema(*, required: tuple[str, ...]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "scope": {"type": "string", "enum": ["global", "workspace"]},
            "workspace_id": {"type": "string"},
            "section": {"type": "string", "enum": ["user_profile", "project_profile", "agent_notes"]},
            "type": {"type": "string", "enum": ["preference", "project_fact", "decision", "workflow", "error_fix", "general"]},
            "content": {"type": "string"},
            "confidence": {"type": "number"},
            "source": {"type": "object"},
            "metadata": {"type": "object"},
            "reason": {"type": "string"},
        },
        "required": list(required),
    }
