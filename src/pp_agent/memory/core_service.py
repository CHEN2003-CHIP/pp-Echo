from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pp_agent.memory.core_governance import (
    SafetyScanResult,
    detect_conflicts,
    find_duplicate,
    find_near_duplicate,
    normalize_memory_content,
    scan_memory_candidate,
)
from pp_agent.memory.core_provider import LocalMemoryProviderPlugin, MemoryProviderPlugin, NoopMemoryProviderPlugin
from pp_agent.memory.core_renderer import CoreMemoryBudget, CoreMemoryRenderer, workspace_id_for_path
from pp_agent.memory.core_store import CoreMemoryStore
from pp_agent.memory.core_types import (
    CoreMemory,
    CoreMemoryAuditRecord,
    CoreMemoryBudgetReport,
    CoreMemoryCandidate,
    CoreMemorySnapshotResult,
    CoreMemorySource,
    CoreMemoryWriteResult,
)
from pp_agent.memory.markdown_router import route_core_memory_to_markdown
from pp_agent.memory.markdown_writer import MarkdownMemoryApplyError, apply_markdown_patch, build_markdown_patch


@dataclass
class CoreMemoryService:
    """Policy boundary for curated long-term memory.

    CoreMemoryStore deliberately stays close to SQLite CRUD. This service owns
    the higher-level rules that must be shared by CLI, tools, runtime, and API:
    safety scanning, dedupe, conflict metadata, budget reporting, approvals,
    audit records, and provider mirroring.
    """

    store: CoreMemoryStore
    settings: object
    workspace: Path
    provider: MemoryProviderPlugin = NoopMemoryProviderPlugin()

    @property
    def workspace_id(self) -> str:
        return workspace_id_for_path(self.workspace)

    @property
    def renderer(self) -> CoreMemoryRenderer:
        budget = self.settings.memory.core_memory.budgets
        return CoreMemoryRenderer(
            CoreMemoryBudget(
                user_profile_chars=budget.user_profile_chars,
                project_profile_chars=budget.project_profile_chars,
                agent_notes_chars=budget.agent_notes_chars,
                total_chars=budget.total_chars,
            )
        )

    def propose(
        self,
        candidate: CoreMemoryCandidate,
        *,
        actor: str = "user",
        reason: str = "",
        source: Optional[CoreMemorySource] = None,
        explicit_user_memory: bool = False,
    ) -> CoreMemoryWriteResult:
        """Create a candidate and record the complete governance decision.

        A proposal is the only ingestion path for new long-term memory. Even an
        explicit user "remember..." request goes through this method so approval
        and audit semantics stay identical across runtime, CLI, tools, and API.
        """
        candidate = self._candidate_with_defaults(candidate, source=source, reason=reason, explicit_user_memory=explicit_user_memory)
        existing = self.store.list_for_governance(candidate.scope, candidate.workspace_id, candidate.section, candidate.type)
        warnings: list[str] = []
        safety = self._safety(candidate)
        duplicate = self._duplicate(candidate, existing)
        if duplicate is not None:
            audit = self._audit(
                duplicate.id,
                "duplicate",
                actor=actor,
                before_status=duplicate.status,
                after_status=duplicate.status,
                reason=reason or "duplicate_core_memory",
                source=candidate.source,
                metadata={"candidate": candidate.model_dump(mode="python")},
            )
            result = CoreMemoryWriteResult(
                memory=duplicate,
                duplicate_of=duplicate.id,
                warnings=["duplicate_core_memory"],
                safety=safety.to_dict(),
                audit=[audit.model_dump(mode="python")],
            )
            result.markdown = self._markdown_payload_for_memory(duplicate, applied=False)
            return result
        status = self._initial_status(safety=safety, explicit_user_memory=explicit_user_memory)
        memory = candidate.to_memory(status=status)
        metadata = dict(memory.metadata)
        if not safety.allowed:
            metadata["rejected_reason"] = list(safety.reasons)
            warnings.append("rejected_by_safety_scan")
        conflicts = self._conflicts(memory, existing)
        if conflicts:
            metadata["conflicts_with"] = conflicts
        budget = self._budget_for_candidate(memory)
        if status == "active" and budget.needs_compaction:
            warnings.append("core_memory_budget_exceeded")
        metadata["budget"] = budget.model_dump(mode="python")
        memory.metadata = metadata
        self.store.add_memory(memory)
        audit = self._audit(
            memory.id,
            "propose",
            actor=actor,
            before_status=None,
            after_status=memory.status,
            reason=reason,
            source=memory.source,
            metadata={
                "safety": safety.to_dict(),
                "conflicts_with": conflicts,
                "budget": budget.model_dump(mode="python"),
                "explicit_user_memory": explicit_user_memory,
            },
        )
        self.provider.mirror_core_write(memory=memory, action="propose")
        result = CoreMemoryWriteResult(
            memory=memory,
            warnings=warnings,
            safety=safety.to_dict(),
            conflicts_with=conflicts,
            budget=budget.model_dump(mode="python"),
            audit=[audit.model_dump(mode="python")],
        )
        result.markdown = self._markdown_payload_for_memory(memory, applied=False)
        return result

    def approve(
        self,
        memory_id: str,
        *,
        actor: str = "user",
        reason: str = "",
        apply_to_markdown: bool = True,
        immediate_effect: bool = True,
    ) -> CoreMemoryWriteResult:
        """Approve a candidate and, by default, apply it to Markdown memory."""
        before = self.store.get(memory_id)
        if before is None:
            raise KeyError(memory_id)
        safety = self._safety(before)
        if not safety.allowed:
            rejected = self.store.update(memory_id, {"status": "rejected", "metadata": {**before.metadata, "rejected_reason": list(safety.reasons)}})
            audit = self._audit(
                memory_id,
                "approve_blocked_safety",
                actor=actor,
                before_status=before.status,
                after_status=rejected.status,
                reason=reason or "safety_scan_failed",
                source=rejected.source,
                metadata={"safety": safety.to_dict()},
            )
            return CoreMemoryWriteResult(memory=rejected, warnings=["rejected_by_safety_scan"], safety=safety.to_dict(), audit=[audit.model_dump(mode="python")])
        budget = self._budget_for_candidate(before.model_copy(update={"status": "active"}, deep=True))
        metadata = {**before.metadata, "budget": budget.model_dump(mode="python")}
        markdown_payload: dict[str, object] = {}
        markdown_audits: list[CoreMemoryAuditRecord] = []
        markdown_warnings: list[str] = []
        if apply_to_markdown:
            preview = self.markdown_preview(memory_id)
            markdown_payload = preview.model_dump(mode="python")
            try:
                applied = apply_markdown_patch(
                    preview,
                    workspace=self.workspace,
                    global_root=self.settings.global_dir,
                    settings=self.settings,
                )
                markdown_payload = applied.patch.model_dump(mode="python")
                markdown_warnings.extend(applied.warnings)
                metadata.update(
                    {
                        "markdown_applied": True,
                        "markdown_target_path": applied.patch.target.path,
                        "markdown_heading": applied.patch.target.heading,
                        "markdown_marker_id": applied.patch.target.marker_id,
                        "markdown_content_hash_after": applied.patch.content_hash_after,
                        "immediate_effect": bool(immediate_effect),
                    }
                )
                markdown_audits.append(
                    self._audit(
                        memory_id,
                        "markdown_apply",
                        actor=actor,
                        before_status=before.status,
                        after_status="active",
                        reason=reason,
                        source=before.source,
                        metadata=self._markdown_audit_metadata(applied.patch, immediate_effect=immediate_effect),
                    )
                )
                if immediate_effect:
                    markdown_audits.append(
                        self._audit(
                            memory_id,
                            "immediate_effect_enabled",
                            actor=actor,
                            before_status=before.status,
                            after_status="active",
                            reason=reason,
                            source=before.source,
                            metadata={"target_path": applied.patch.target.path, "marker_id": applied.patch.target.marker_id},
                        )
                    )
            except MarkdownMemoryApplyError as exc:
                action = "external_edit_detected" if exc.code == "external_edit_detected" else "markdown_apply_failed"
                markdown_warnings.append(exc.code)
                if exc.patch is not None:
                    markdown_payload = exc.patch.model_dump(mode="python")
                markdown_audits.append(
                    self._audit(
                        memory_id,
                        action,
                        actor=actor,
                        before_status=before.status,
                        after_status=before.status,
                        reason=str(exc),
                        source=before.source,
                        metadata={"code": exc.code, **({"target_path": markdown_payload.get("target", {}).get("path")} if isinstance(markdown_payload.get("target"), dict) else {})},
                    )
                )
                return CoreMemoryWriteResult(
                    memory=before,
                    warnings=markdown_warnings,
                    safety=safety.to_dict(),
                    budget=budget.model_dump(mode="python"),
                    audit=[item.model_dump(mode="python") for item in markdown_audits],
                    markdown=markdown_payload,
                    immediate_effect=False,
                )
        else:
            metadata["not_applied_to_markdown"] = True
        after = self.store.update(memory_id, {"status": "active", "metadata": metadata})
        warnings = [*markdown_warnings]
        if budget.needs_compaction:
            warnings.append("core_memory_budget_exceeded")
        audit = self._audit(
            memory_id,
            "approve",
            actor=actor,
            before_status=before.status,
            after_status=after.status,
            reason=reason,
            source=after.source,
            metadata={"budget": budget.model_dump(mode="python"), "warnings": warnings, "apply_to_markdown": apply_to_markdown},
        )
        self.provider.mirror_core_write(memory=after, action="approve")
        archive_audits = self._archive_sources_on_approve(after, actor=actor, reason=reason or "auto_replacement_approved")
        return CoreMemoryWriteResult(
            memory=after,
            warnings=warnings,
            safety=safety.to_dict(),
            budget=budget.model_dump(mode="python"),
            audit=[
                audit.model_dump(mode="python"),
                *[item.model_dump(mode="python") for item in markdown_audits],
                *[item.model_dump(mode="python") for item in archive_audits],
            ],
            markdown=markdown_payload,
            immediate_effect=bool(apply_to_markdown and immediate_effect and not markdown_warnings),
        )

    def markdown_preview(self, memory_id: str):
        memory = self.store.get(memory_id)
        if memory is None:
            raise KeyError(memory_id)
        patch = build_markdown_patch(
            memory,
            route_core_memory_to_markdown(memory, workspace=self.workspace, global_root=self.settings.global_dir, marker_id=memory.id),
            workspace=self.workspace,
            global_root=self.settings.global_dir,
        )
        self._audit(
            memory_id,
            "markdown_preview",
            actor="system",
            before_status=memory.status,
            after_status=memory.status,
            reason="markdown_first_governance_preview",
            source=memory.source,
            metadata=self._markdown_audit_metadata(patch, immediate_effect=False),
        )
        return patch

    def markdown_apply(self, memory_id: str, *, actor: str = "user", reason: str = "") -> CoreMemoryWriteResult:
        memory = self.store.get(memory_id)
        if memory is None:
            raise KeyError(memory_id)
        patch = self.markdown_preview(memory_id)
        applied = apply_markdown_patch(patch, workspace=self.workspace, global_root=self.settings.global_dir, settings=self.settings)
        metadata = {
            **memory.metadata,
            "markdown_applied": True,
            "markdown_target_path": applied.patch.target.path,
            "markdown_heading": applied.patch.target.heading,
            "markdown_marker_id": applied.patch.target.marker_id,
            "markdown_content_hash_after": applied.patch.content_hash_after,
            "immediate_effect": True,
        }
        after = self.store.update(memory_id, {"metadata": metadata})
        audit = self._audit(
            memory_id,
            "markdown_apply",
            actor=actor,
            before_status=memory.status,
            after_status=after.status,
            reason=reason,
            source=after.source,
            metadata=self._markdown_audit_metadata(applied.patch, immediate_effect=True),
        )
        return CoreMemoryWriteResult(
            memory=after,
            warnings=applied.warnings,
            audit=[audit.model_dump(mode="python")],
            markdown=applied.patch.model_dump(mode="python"),
            immediate_effect=True,
        )

    def export_active_core_memories_to_markdown(self, *, actor: str = "user", reason: str = "export_active_core_memories_to_markdown") -> dict[str, object]:
        exported: list[dict[str, object]] = []
        skipped: list[str] = []
        warnings: list[str] = []
        for memory in self.store.list_active(workspace_id=self.workspace_id):
            if memory.metadata.get("markdown_marker_id") or memory.metadata.get("markdown_applied"):
                skipped.append(memory.id)
                continue
            result = self.markdown_apply(memory.id, actor=actor, reason=reason)
            exported.append({"id": memory.id, "markdown": result.markdown})
            warnings.extend(result.warnings)
            self._audit(
                memory.id,
                "exported_to_markdown",
                actor=actor,
                before_status=memory.status,
                after_status="active",
                reason=reason,
                source=memory.source,
                metadata=result.markdown,
            )
        return {"exported": exported, "skipped": skipped, "warnings": warnings}

    def reject(self, memory_id: str, *, actor: str = "user", reason: str = "") -> CoreMemoryWriteResult:
        return self._status_transition(memory_id, "rejected", "reject", actor=actor, reason=reason)

    def archive(self, memory_id: str, *, actor: str = "user", reason: str = "") -> CoreMemoryWriteResult:
        return self._status_transition(memory_id, "archived", "archive", actor=actor, reason=reason)

    def replace(self, old_id: str, candidate: CoreMemoryCandidate, *, actor: str = "user", reason: str = "") -> CoreMemoryWriteResult:
        old = self.store.get(old_id)
        if old is None:
            raise KeyError(old_id)
        candidate = self._candidate_with_defaults(candidate, source=candidate.source, reason=reason, explicit_user_memory=False)
        replacement = candidate.to_memory(status="active")
        replacement.supersedes = list(dict.fromkeys([*replacement.supersedes, old.id]))
        budget = self._budget_for_candidate(replacement)
        replacement.metadata = {**replacement.metadata, "budget": budget.model_dump(mode="python")}
        memory = self.store.replace(old_id, replacement)
        warnings = ["core_memory_budget_exceeded"] if budget.needs_compaction else []
        audit_new = self._audit(
            memory.id,
            "replace_new",
            actor=actor,
            before_status=None,
            after_status="active",
            reason=reason,
            source=memory.source,
            metadata={"supersedes": [old.id], "budget": budget.model_dump(mode="python"), "warnings": warnings},
        )
        audit_old = self._audit(
            old.id,
            "replace_archive_old",
            actor=actor,
            before_status=old.status,
            after_status="archived",
            reason=reason,
            source=old.source,
            metadata={"replaced_by": memory.id},
        )
        self.provider.mirror_core_write(memory=memory, action="replace")
        return CoreMemoryWriteResult(
            memory=memory,
            warnings=warnings,
            budget=budget.model_dump(mode="python"),
            audit=[audit_new.model_dump(mode="python"), audit_old.model_dump(mode="python")],
        )

    def snapshot(self, *, workspace_id: Optional[str] = None, session_id: Optional[str] = None) -> CoreMemorySnapshotResult:
        """Render a debug governance snapshot from active memory only.

        Markdown memory is now the prompt fact source. This snapshot is kept for
        debugging, budget reports, and compatibility with management surfaces.
        """
        workspace_id = workspace_id or self.workspace_id
        memories = []
        skipped_reasons: dict[str, str] = {}
        for memory in self.store.list_active(workspace_id=workspace_id):
            safety = self._safety(memory)
            if not safety.allowed:
                skipped_reasons[memory.id] = "safety_scan"
                self._audit(
                    memory.id,
                    "snapshot_skip_unsafe",
                    actor="runtime",
                    before_status=memory.status,
                    after_status=memory.status,
                    reason="active_memory_failed_defensive_scan",
                    source=memory.source,
                    metadata={"safety": safety.to_dict()},
                )
                continue
            memories.append(memory)
        text, budget = self.renderer.render_with_report(memories)
        skipped_reasons.update(budget.skipped_reasons)
        budget.skipped_reasons = skipped_reasons
        snapshot_hash = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""
        return CoreMemorySnapshotResult(
            snapshot=text,
            workspace_id=workspace_id,
            session_id=session_id,
            included_ids=list(budget.included_ids),
            skipped_ids=list(dict.fromkeys([*budget.skipped_ids, *skipped_reasons])),
            skipped_reasons=skipped_reasons,
            chars=len(text),
            snapshot_hash=snapshot_hash,
            budget=budget,
        )

    def _markdown_payload_for_memory(self, memory: CoreMemory, *, applied: bool) -> dict[str, object]:
        try:
            patch = build_markdown_patch(
                memory,
                route_core_memory_to_markdown(memory, workspace=self.workspace, global_root=self.settings.global_dir, marker_id=memory.id),
                workspace=self.workspace,
                global_root=self.settings.global_dir,
            )
            if applied:
                patch = patch.model_copy(update={"applied": True}, deep=True)
            return patch.model_dump(mode="python")
        except Exception as exc:  # noqa: BLE001
            return {"warning": f"markdown_preview_failed: {exc}"}

    @staticmethod
    def _markdown_audit_metadata(patch, *, immediate_effect: bool) -> dict[str, object]:
        import hashlib

        return {
            "target_path": patch.target.path,
            "heading": patch.target.heading,
            "marker_id": patch.target.marker_id,
            "content_hash_before": patch.content_hash_before,
            "content_hash_after": patch.content_hash_after,
            "diff_hash": hashlib.sha256(patch.diff.encode("utf-8")).hexdigest(),
            "immediate_effect": immediate_effect,
        }

    def search(self, query: str, *, scope: Optional[str] = None, workspace_id: Optional[str] = None) -> list[CoreMemory]:
        return self.store.search_core_memory(query, scope=scope, workspace_id=workspace_id or self.workspace_id)

    def audit(self, *, memory_id: Optional[str] = None, limit: int = 100) -> list[CoreMemoryAuditRecord]:
        return self.store.list_audit(memory_id=memory_id, limit=limit)

    def merge_preview(self, *, workspace_id: Optional[str] = None) -> dict[str, object]:
        if not self.settings.memory.core_memory.automation.enabled:
            return {"enabled": False, "mergeable_group_count": 0, "groups": [], "provider": self.provider.status()}
        memories = self.store.list_active(workspace_id=workspace_id or self.workspace_id)
        groups = self._merge_groups(memories)
        return {
            "mergeable_group_count": len(groups),
            "groups": [self._automation_group_payload(group, action="merge") for group in groups],
            "provider": self.provider.status(),
        }

    def merge_apply(self, *, actor: str = "user", reason: str = "auto_merge") -> dict[str, object]:
        preview = self.merge_preview()
        if preview.get("enabled") is False:
            return {**preview, "applied": False, "generated": []}
        results: list[dict[str, object]] = []
        for group_payload in preview["groups"]:  # type: ignore[index]
            ids = [str(item) for item in group_payload.get("ids", [])]  # type: ignore[union-attr]
            group = [memory for memory in self.store.list_active(workspace_id=self.workspace_id) if memory.id in ids]
            if len(group) < 2:
                continue
            results.append(self._create_automation_candidate(group, action="merge", actor=actor, reason=reason).model_dump(mode="python"))
        self._audit(
            memory_id="core-memory",
            action="merge_apply",
            actor=actor,
            before_status=None,
            after_status=None,
            reason=reason,
            source=CoreMemorySource(),
            metadata={"preview": preview, "generated_count": len(results)},
        )
        return {**preview, "applied": True, "generated": results}

    def compact_preview(self, *, workspace_id: Optional[str] = None) -> dict[str, object]:
        if not self.settings.memory.core_memory.automation.enabled:
            return {"enabled": False, "needs_compaction": False, "included_ids": [], "skipped_ids": [], "skipped_reasons": {}, "groups": []}
        result = self.snapshot(workspace_id=workspace_id)
        memories = self.store.list_active(workspace_id=workspace_id or self.workspace_id)
        groups = self._compaction_groups(memories, result.skipped_ids)
        return {
            "needs_compaction": result.budget.needs_compaction,
            "included_ids": result.included_ids,
            "skipped_ids": result.skipped_ids,
            "skipped_reasons": result.skipped_reasons,
            "groups": [self._automation_group_payload(group, action="compact") for group in groups],
            "llm_summary_enabled": bool(self.settings.memory.core_memory.automation.use_llm_summary),
            "recommendation": "Apply compaction to create pending replacement candidates; originals are archived only after approval.",
        }

    def compact_apply(self, *, actor: str = "user", reason: str = "manual_compaction") -> dict[str, object]:
        """Create pending compaction candidates without directly rewriting memory."""
        preview = self.compact_preview()
        if preview.get("enabled") is False:
            return {**preview, "applied": False, "generated": []}
        results: list[dict[str, object]] = []
        for group_payload in preview["groups"]:  # type: ignore[index]
            ids = [str(item) for item in group_payload.get("ids", [])]  # type: ignore[union-attr]
            group = [memory for memory in self.store.list_active(workspace_id=self.workspace_id) if memory.id in ids]
            if len(group) < 2:
                continue
            results.append(self._create_automation_candidate(group, action="compact", actor=actor, reason=reason).model_dump(mode="python"))
        self._audit(
            memory_id="core-memory",
            action="compact_apply",
            actor=actor,
            before_status=None,
            after_status=None,
            reason=reason,
            source=CoreMemorySource(),
            metadata={"preview": preview, "generated_count": len(results)},
        )
        return {**preview, "applied": True, "generated": results, "message": "Pending compaction candidates created; approve them to archive their source memories."}

    def propose_from_user_text(self, text: str, *, session_id: str, turn_id: str, message_id: str = "", actor: str = "user") -> Optional[CoreMemoryWriteResult]:
        extracted = extract_explicit_memory_candidate(text, workspace_id=self.workspace_id)
        if extracted is None:
            return None
        source = CoreMemorySource(session_id=session_id, turn_id=turn_id, message_id=message_id or None)
        return self.propose(
            extracted,
            actor=actor,
            reason="explicit_user_memory",
            source=source,
            explicit_user_memory=True,
        )

    def _candidate_with_defaults(
        self,
        candidate: CoreMemoryCandidate,
        *,
        source: Optional[CoreMemorySource],
        reason: str,
        explicit_user_memory: bool,
    ) -> CoreMemoryCandidate:
        metadata = dict(candidate.metadata)
        if reason:
            metadata["reason"] = reason
        if explicit_user_memory:
            metadata["explicit_user_memory"] = True
        workspace_id = candidate.workspace_id
        if candidate.scope == "workspace" and not workspace_id:
            workspace_id = self.workspace_id
        if candidate.scope == "global":
            workspace_id = None
        return candidate.model_copy(update={"workspace_id": workspace_id, "source": source or candidate.source, "metadata": metadata}, deep=True)

    def _initial_status(self, *, safety: SafetyScanResult, explicit_user_memory: bool) -> str:
        if not safety.allowed:
            return "rejected"
        core = self.settings.memory.core_memory
        if explicit_user_memory and core.auto_approve_explicit_user_memory:
            return "active"
        if not core.require_approval:
            return "active"
        return "pending"

    def _safety(self, candidate: CoreMemoryCandidate | CoreMemory) -> SafetyScanResult:
        if not self.settings.memory.core_memory.safety.enabled:
            return SafetyScanResult(allowed=True, reasons=["safety_disabled"], risk="disabled")
        return scan_memory_candidate(candidate)

    def _duplicate(self, candidate: CoreMemoryCandidate, existing: list[CoreMemory]) -> Optional[CoreMemory]:
        if not self.settings.memory.core_memory.dedupe.enabled:
            return None
        return find_duplicate(candidate, existing) or find_near_duplicate(candidate, existing)

    def _conflicts(self, memory: CoreMemory, existing: list[CoreMemory]) -> list[str]:
        if not self.settings.memory.core_memory.conflict_detection.enabled:
            return []
        return detect_conflicts(memory, existing)

    def _budget_for_candidate(self, candidate: CoreMemory) -> CoreMemoryBudgetReport:
        active = [memory for memory in self.store.list_active(workspace_id=candidate.workspace_id or self.workspace_id) if memory.id != candidate.id]
        current_text = self.renderer.render(active)
        projected_text, projected_budget = self.renderer.render_with_report([*active, candidate.model_copy(update={"status": "active"}, deep=True)])
        projected_budget.current_chars = len(current_text)
        projected_budget.projected_chars = len(projected_text)
        projected_budget.needs_compaction = projected_budget.needs_compaction or len(projected_text) > self.renderer.budget.total_chars
        projected_budget.budget_status = "over_budget" if projected_budget.needs_compaction else "ok"
        return projected_budget

    def _status_transition(self, memory_id: str, status: str, action: str, *, actor: str, reason: str) -> CoreMemoryWriteResult:
        before = self.store.get(memory_id)
        if before is None:
            raise KeyError(memory_id)
        after = self.store.update(memory_id, {"status": status})
        audit = self._audit(
            memory_id,
            action,
            actor=actor,
            before_status=before.status,
            after_status=after.status,
            reason=reason,
            source=after.source,
            metadata={},
        )
        self.provider.mirror_core_write(memory=after, action=action)
        return CoreMemoryWriteResult(memory=after, audit=[audit.model_dump(mode="python")])

    def _archive_sources_on_approve(self, memory: CoreMemory, *, actor: str, reason: str) -> list[CoreMemoryAuditRecord]:
        source_ids = [str(item) for item in memory.metadata.get("auto_archive_on_approve_ids", []) if str(item) != memory.id]
        audits: list[CoreMemoryAuditRecord] = []
        for source_id in source_ids:
            source = self.store.get(source_id)
            if source is None or source.status == "archived":
                continue
            archived = self.store.update(source_id, {"status": "archived", "metadata": {**source.metadata, "archived_by_replacement": memory.id}})
            audits.append(
                self._audit(
                    source_id,
                    "auto_archive_source",
                    actor=actor,
                    before_status=source.status,
                    after_status=archived.status,
                    reason=reason,
                    source=archived.source,
                    metadata={"replacement_id": memory.id},
                )
            )
            self.provider.mirror_core_write(memory=archived, action="auto_archive_source")
        return audits

    def _merge_groups(self, memories: list[CoreMemory]) -> list[list[CoreMemory]]:
        buckets: dict[tuple[object, ...], list[CoreMemory]] = {}
        for memory in memories:
            if memory.metadata.get("conflicts_with"):
                continue
            key = (memory.scope, memory.workspace_id, memory.section, memory.type, normalize_memory_content(memory.content))
            buckets.setdefault(key, []).append(memory)
        limit = int(self.settings.memory.core_memory.automation.max_merge_group_size)
        return [sorted(group, key=lambda item: item.updated_at, reverse=True)[:limit] for group in buckets.values() if len(group) > 1]

    def _compaction_groups(self, memories: list[CoreMemory], skipped_ids: list[str]) -> list[list[CoreMemory]]:
        skipped = set(skipped_ids)
        if not skipped:
            return []
        buckets: dict[tuple[object, ...], list[CoreMemory]] = {}
        for memory in memories:
            if memory.id not in skipped and memory.confidence >= 0.85:
                continue
            key = (memory.scope, memory.workspace_id, memory.section)
            buckets.setdefault(key, []).append(memory)
        limit = int(self.settings.memory.core_memory.automation.max_compaction_group_size)
        return [sorted(group, key=lambda item: (item.id not in skipped, item.confidence, item.updated_at))[:limit] for group in buckets.values() if len(group) > 1]

    def _automation_group_payload(self, group: list[CoreMemory], *, action: str) -> dict[str, object]:
        content, metadata = self._summarize_memories(group, action=action)
        return {
            "ids": [memory.id for memory in group],
            "scope": group[0].scope,
            "workspace_id": group[0].workspace_id,
            "section": group[0].section,
            "type": self._dominant_type(group),
            "content": content,
            "metadata": metadata,
        }

    def _create_automation_candidate(self, group: list[CoreMemory], *, action: str, actor: str, reason: str) -> CoreMemoryWriteResult:
        content, summary_metadata = self._summarize_memories(group, action=action)
        source_hash = self._source_hash(group)
        existing = self._existing_automation_candidate(group, action=action, source_hash=source_hash)
        if existing is not None:
            audit = self._audit(
                existing.id,
                f"{action}_candidate_duplicate",
                actor=actor,
                before_status=existing.status,
                after_status=existing.status,
                reason=reason,
                source=existing.source,
                metadata={"source_ids": [item.id for item in group], "source_hash": source_hash},
            )
            return CoreMemoryWriteResult(memory=existing, duplicate_of=existing.id, warnings=["duplicate_automation_candidate"], audit=[audit.model_dump(mode="python")])
        candidate = CoreMemoryCandidate(
            scope=group[0].scope,
            workspace_id=group[0].workspace_id,
            section=group[0].section,
            type=self._dominant_type(group),  # type: ignore[arg-type]
            content=content,
            confidence=min(0.82, max(memory.confidence for memory in group)),
            source=CoreMemorySource(),
            metadata={
                **summary_metadata,
                "automation_action": action,
                "auto_archive_on_approve_ids": [memory.id for memory in group],
                "source_hash": source_hash,
                "reason": reason,
            },
        )
        safety = self._safety(candidate)
        status = "pending" if safety.allowed else "rejected"
        memory = candidate.to_memory(status=status)
        self.store.add_memory(memory)
        audit = self._audit(
            memory.id,
            f"{action}_candidate_created",
            actor=actor,
            before_status=None,
            after_status=memory.status,
            reason=reason,
            source=memory.source,
            metadata={"source_ids": [item.id for item in group], "safety": safety.to_dict(), **summary_metadata},
        )
        self.provider.mirror_core_write(memory=memory, action=f"{action}_candidate_created")
        warnings = [] if safety.allowed else ["rejected_by_safety_scan"]
        return CoreMemoryWriteResult(memory=memory, warnings=warnings, safety=safety.to_dict(), audit=[audit.model_dump(mode="python")])

    def _existing_automation_candidate(self, group: list[CoreMemory], *, action: str, source_hash: str) -> Optional[CoreMemory]:
        for memory in self.store.list_all(workspace_id=group[0].workspace_id or self.workspace_id):
            if memory.status not in {"pending", "active"}:
                continue
            if memory.metadata.get("automation_action") == action and memory.metadata.get("source_hash") == source_hash:
                return memory
        return None

    def _summarize_memories(self, group: list[CoreMemory], *, action: str) -> tuple[str, dict[str, object]]:
        automation = self.settings.memory.core_memory.automation
        summarizer = getattr(self, "llm_summarizer", None)
        if automation.use_llm_summary and callable(summarizer):
            content = str(summarizer(group=group, action=action)).strip()
            if content:
                return content, {"summary_method": "llm", "llm_summary_model": automation.llm_summary_model}
        lines = []
        seen: set[str] = set()
        for memory in sorted(group, key=lambda item: (item.confidence, item.updated_at), reverse=True):
            normalized = normalize_memory_content(memory.content)
            if normalized in seen:
                continue
            seen.add(normalized)
            lines.append(memory.content.rstrip(".。"))
            if len("; ".join(lines)) >= self.renderer.budget.section_limit(memory.section) // 2:
                break
        prefix = "Merged memory" if action == "merge" else "Compacted memory"
        content = f"{prefix}: " + "; ".join(lines)
        method = "deterministic"
        if automation.use_llm_summary:
            method = "llm_unavailable_deterministic_fallback"
        return content[: self.renderer.budget.section_limit(group[0].section)], {"summary_method": method, "source_count": len(group)}

    @staticmethod
    def _dominant_type(group: list[CoreMemory]) -> str:
        counts: dict[str, int] = {}
        for memory in group:
            counts[memory.type] = counts.get(memory.type, 0) + 1
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]

    @staticmethod
    def _source_hash(group: list[CoreMemory]) -> str:
        payload = "|".join(sorted(memory.id for memory in group))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _audit(
        self,
        memory_id: str,
        action: str,
        *,
        actor: str,
        before_status: Optional[str],
        after_status: Optional[str],
        reason: str,
        source: CoreMemorySource,
        metadata: dict[str, object],
    ) -> CoreMemoryAuditRecord:
        return self.store.record_audit(
            CoreMemoryAuditRecord(
                memory_id=memory_id,
                action=action,
                actor=actor,
                source=source,
                before_status=before_status,
                after_status=after_status,
                reason=reason,
                metadata=metadata,
            )
        )


def service_for_workspace(workspace: Path, settings: object) -> CoreMemoryService:
    store = CoreMemoryStore(settings.core_memory_db_path(), busy_timeout_ms=settings.memory.sqlite_busy_timeout_ms)
    provider_settings = settings.memory.core_memory.provider
    provider: MemoryProviderPlugin
    if provider_settings.enabled and provider_settings.backend == "local":
        provider = LocalMemoryProviderPlugin(settings.core_memory_provider_db_path(), busy_timeout_ms=settings.memory.sqlite_busy_timeout_ms)
    else:
        provider = NoopMemoryProviderPlugin()
    return CoreMemoryService(store=store, settings=settings, workspace=workspace.resolve(), provider=provider)


def extract_explicit_memory_candidate(text: str, *, workspace_id: str) -> Optional[CoreMemoryCandidate]:
    """Classify direct user memory instructions into bounded core sections."""
    raw = text.strip()
    if not raw:
        return None
    if not re.search(r"(?i)(记住|以后|remember|from now on)", raw):
        return None
    content = _strip_memory_intent(raw)
    lowered = content.lower()
    if any(token in lowered for token in ("prefer", "preference", "answer", "language", "中文", "英文", "偏好", "回答")):
        return CoreMemoryCandidate(scope="global", section="user_profile", type="preference", content=content, confidence=0.72)
    if any(token in lowered for token in ("bug", "fix", "error", "traceback", "修复", "错误")):
        return CoreMemoryCandidate(scope="workspace", workspace_id=workspace_id, section="agent_notes", type="error_fix", content=content, confidence=0.68)
    if any(token in lowered for token in ("workflow", "run", "test", "pytest", "npm", "pnpm", "流程", "测试", "命令")):
        return CoreMemoryCandidate(scope="workspace", workspace_id=workspace_id, section="project_profile", type="workflow", content=content, confidence=0.7)
    return CoreMemoryCandidate(scope="workspace", workspace_id=workspace_id, section="project_profile", type="general", content=content, confidence=0.55)


def _strip_memory_intent(text: str) -> str:
    replacements = [
        r"(?i)^\s*remember\s+(that\s+|to\s+)?",
        r"(?i)^\s*from now on,?\s*",
        r"^\s*请?记住[:：]?\s*",
        r"^\s*以后[:：]?\s*",
    ]
    result = text
    for pattern in replacements:
        result = re.sub(pattern, "", result).strip()
    return result or text.strip()
