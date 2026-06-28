from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from pp_agent.tools.effects import CONFIDENCE_HIGH, CONFIDENCE_LOW, CONFIDENCE_UNKNOWN, is_protected_path


ALLOW = "allow"
ASK = "ask"
DENY = "deny"


class PermissionDomain:
    READ = "read"
    EDIT = "edit"
    BASH = "bash"
    EXTERNAL_DIRECTORY = "external_directory"
    APPROVAL = "approval"
    REPO = "repo"


@dataclass(frozen=True)
class PolicyDecision:
    action: str
    permission_domain: str
    reason: str
    target: str | None = None
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class ApprovalScope:
    profile_id: str = "default"
    session_id: str | None = None
    run_id: str | None = None
    tool_call_id: str | None = None
    effect_id: str | None = None
    payload_digest: str | None = None


@dataclass(frozen=True)
class ToolPolicyDecision:
    tool_name: str
    tool_call_id: str | None
    run_id: str | None
    session_id: str | None
    read_only: bool
    requires_approval: bool
    risk_level: str
    side_effect_type: str | None
    allowed: bool
    blocked_reason: str | None
    budget_cost: int
    approval_scope: ApprovalScope
    policy_action: str
    permission_domain: str

    @classmethod
    def from_policy_decision(
        cls,
        decision: PolicyDecision,
        *,
        tool_name: str,
        tool_call_id: str | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
        permission_mode: str = "workspace-write",
        budget_cost: int = 1,
        approval_scope: ApprovalScope | None = None,
    ) -> "ToolPolicyDecision":
        details = decision.details or {}
        return cls(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            run_id=run_id,
            session_id=session_id,
            read_only=permission_mode == "read-only",
            requires_approval=decision.action == ASK,
            risk_level=_risk_level(details),
            side_effect_type=_side_effect_type(decision.permission_domain, details),
            allowed=decision.action != DENY,
            blocked_reason=decision.reason if decision.action == DENY else None,
            budget_cost=int(budget_cost),
            approval_scope=approval_scope or ApprovalScope(session_id=session_id, run_id=run_id, tool_call_id=tool_call_id),
            policy_action=decision.action,
            permission_domain=decision.permission_domain,
        )

    def to_trace_attributes(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "read_only": self.read_only,
            "requires_approval": self.requires_approval,
            "risk_level": self.risk_level,
            "side_effect_type": self.side_effect_type,
            "allowed": self.allowed,
            "blocked_reason": self.blocked_reason,
            "budget_cost": self.budget_cost,
            "approval_scope": self.approval_scope.__dict__,
            "policy_action": self.policy_action,
            "permission_domain": self.permission_domain,
        }


def _risk_level(details: dict[str, Any]) -> str:
    if details.get("destructive_hint") or details.get("touches_external") or details.get("protected_path_hint"):
        return "high"
    if details.get("requests_network") or details.get("risk_class") not in {None, "inspect"}:
        return "medium"
    return "low"


def _side_effect_type(permission_domain: str, details: dict[str, Any]) -> str | None:
    if details.get("writes_workspace_files") or permission_domain == PermissionDomain.EDIT:
        return "write"
    if permission_domain == PermissionDomain.BASH:
        return "shell"
    if details.get("requests_network"):
        return "network"
    if permission_domain in {PermissionDomain.READ, PermissionDomain.REPO}:
        return "read"
    return permission_domain or None


class ToolPolicyEvaluator:
    """
    ToolPolicyEvaluator 是工具执行前的策略判断层。
    
    它根据工具调用的 effect analysis 和当前 ToolPolicy，
    判断本次工具调用应该 allow、ask 还是 deny。
    
    - allow：低风险操作，允许直接执行；
    - ask：有副作用或风险，需要进入用户审批；
    - deny：违反安全策略，直接拒绝。
    
    它主要用于保护 workspace 边界、敏感路径、危险 shell 命令、
    写文件/编辑文件等有副作用操作，并为 Runtime 的 approval gate
    提供决策依据。
    
    注意：
    ToolPolicyEvaluator 不执行工具；
    它只决定“这次工具调用能不能执行、要不要审批、为什么”。
    """
    def __init__(
        self,
        workspace: Path,
        *,
        permission_mode: str = "workspace-write",
        allowed_tools: list[str] | None = None,
        denied_tools: list[str] | None = None,
        ask_tools: list[str] | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.permission_mode = permission_mode
        self.allowed_tools = list(allowed_tools or [])
        self.denied_tools = list(denied_tools or [])
        self.ask_tools = list(ask_tools or [])

    def evaluate(
        self,
        *,
        permission_domain: str,
        tool_name: Optional[str] = None,
        tool_family: Optional[str] = None,
        target_path: Optional[Path] = None,
        command: Optional[str] = None,
        analysis: Optional[dict[str, Any]] = None,
    ) -> PolicyDecision:
        target = str(target_path) if target_path is not None else command or None
        details = self._details(permission_domain=permission_domain, analysis=analysis)
        if tool_name is not None:
            details["tool_name"] = tool_name
        if tool_family is not None:
            details["tool_family"] = tool_family

        if permission_domain == PermissionDomain.EXTERNAL_DIRECTORY:
            return PolicyDecision(
                action=DENY,
                permission_domain=permission_domain,
                reason="External directory access is denied by default.",
                target=target,
                details=details,
            )

        if target_path is not None and not self._is_within_workspace(target_path):
            return PolicyDecision(
                action=DENY,
                permission_domain=PermissionDomain.EXTERNAL_DIRECTORY,
                reason="External directory access is denied by default.",
                target=str(target_path),
                details=details,
            )

        if analysis and analysis.get("protected_path_hint"):
            return PolicyDecision(
                action=DENY,
                permission_domain=permission_domain,
                reason="Protected paths and secret-like files are denied by policy.",
                target=target,
                details=details,
            )

        if tool_name is not None:
            rule_decision = self._evaluate_tool_name_rules(
                tool_name=tool_name,
                permission_domain=permission_domain,
                target=target,
                details=details,
            )
            if rule_decision is not None:
                return rule_decision

        mode_decision = self._evaluate_permission_mode(
            permission_domain=permission_domain,
            target=target,
            details=details,
        )
        if mode_decision is not None:
            return mode_decision

        if tool_family in {"browser", "web"}:
            return PolicyDecision(
                action=ALLOW,
                permission_domain=permission_domain,
                reason=f"{tool_family} tool execution is allowed by current policy.",
                target=target,
                details=details,
            )

        if permission_domain == PermissionDomain.EDIT:
            return PolicyDecision(
                action=ASK,
                permission_domain=permission_domain,
                reason="Workspace edits require host-side approval after policy gating.",
                target=target,
                details=details,
            )

        if analysis:
            decision = self._evaluate_analysis(permission_domain=permission_domain, analysis=analysis, target=target, details=details)
            if decision is not None:
                return decision

        return PolicyDecision(
            action=ALLOW,
            permission_domain=permission_domain,
            reason="Allowed by current policy.",
            target=target,
            details=details,
        )

    def _evaluate_analysis(self, *, permission_domain: str, analysis: dict[str, Any], target: str | None, details: dict[str, Any]) -> PolicyDecision | None:
        family = analysis.get("family")
        risk_class = analysis.get("risk_class", "unknown")
        confidence_band = analysis.get("confidence_band", CONFIDENCE_UNKNOWN)
        touches_external = bool(analysis.get("touches_external"))
        requests_network = bool(analysis.get("requests_network"))
        destructive_hint = bool(analysis.get("destructive_hint"))
        known_safe_inspect = bool(analysis.get("known_safe_inspect"))
        non_side_effectful = bool(analysis.get("non_side_effectful"))

        if touches_external:
            return PolicyDecision(
                action=DENY,
                permission_domain=PermissionDomain.EXTERNAL_DIRECTORY,
                reason="External directory access is denied by default.",
                target=target,
                details=details,
            )

        if family in {"extension", "mcp"}:
            if (
                risk_class == "inspect"
                and confidence_band == CONFIDENCE_HIGH
                and known_safe_inspect
                and non_side_effectful
                and not requests_network
                and not destructive_hint
                and not touches_external
            ):
                return PolicyDecision(
                    action=ALLOW,
                    permission_domain=permission_domain,
                    reason=f"Known-safe {family.upper()} inspect call allowed by current policy.",
                    target=target,
                    details=details,
                )
            if destructive_hint:
                reason = f"{family.upper()} tool with destructive hints requires host-side approval after policy gating."
            elif requests_network:
                reason = f"{family.upper()} tool with network semantics requires host-side approval after policy gating."
            else:
                reason = f"{family.upper()} tool semantics are not staged for exact-effect approval and require host-side review."
            return PolicyDecision(action=ASK, permission_domain=permission_domain, reason=reason, target=target, details=details)

        if family == "shell":
            if confidence_band in {CONFIDENCE_UNKNOWN, CONFIDENCE_LOW}:
                return PolicyDecision(
                    action=ASK,
                    permission_domain=permission_domain,
                    reason="Low-confidence shell semantics require host-side approval after policy gating.",
                    target=target,
                    details=details,
                )
            if requests_network:
                return PolicyDecision(
                    action=ASK,
                    permission_domain=permission_domain,
                    reason="Networked shell command requires host-side approval after policy gating.",
                    target=target,
                    details=details,
                )
            if destructive_hint:
                return PolicyDecision(
                    action=ASK,
                    permission_domain=permission_domain,
                    reason="Destructive shell command requires host-side approval after policy gating.",
                    target=target,
                    details=details,
                )
            if risk_class == "inspect" and confidence_band == CONFIDENCE_HIGH and known_safe_inspect:
                return PolicyDecision(
                    action=ALLOW,
                    permission_domain=permission_domain,
                    reason="Known-safe inspect shell command allowed by current policy.",
                    target=target,
                    details=details,
                )
            if risk_class == "inspect":
                reason = "Inspect shell command requires host-side approval after policy gating."
            else:
                reason = "Workspace-mutating shell command requires host-side approval after policy gating."
            return PolicyDecision(action=ASK, permission_domain=permission_domain, reason=reason, target=target, details=details)

        if family == "file":
            if permission_domain == PermissionDomain.READ and confidence_band == CONFIDENCE_HIGH:
                return PolicyDecision(
                    action=ALLOW,
                    permission_domain=permission_domain,
                    reason="High-confidence workspace file read allowed by current policy.",
                    target=target,
                    details=details,
                )
            if permission_domain == PermissionDomain.READ:
                return PolicyDecision(
                    action=ASK,
                    permission_domain=permission_domain,
                    reason="Low-confidence file read requires host-side approval after policy gating.",
                    target=target,
                    details=details,
                )

        return None

    def _evaluate_tool_name_rules(
        self,
        *,
        tool_name: str,
        permission_domain: str,
        target: str | None,
        details: dict[str, Any],
    ) -> PolicyDecision | None:
        if self._matches_any(tool_name, self.denied_tools):
            return PolicyDecision(
                action=DENY,
                permission_domain=permission_domain,
                reason=f"Tool '{tool_name}' is denied by tool policy.",
                target=target,
                details=details,
            )
        if self._matches_any(tool_name, self.ask_tools):
            return PolicyDecision(
                action=ASK,
                permission_domain=permission_domain,
                reason=f"Tool '{tool_name}' requires host-side approval by tool policy.",
                target=target,
                details=details,
            )
        if self._matches_any(tool_name, self.allowed_tools):
            return PolicyDecision(
                action=ALLOW,
                permission_domain=permission_domain,
                reason=f"Tool '{tool_name}' is allowed by tool policy.",
                target=target,
                details=details,
            )
        return None

    def _evaluate_permission_mode(
        self,
        *,
        permission_domain: str,
        target: str | None,
        details: dict[str, Any],
    ) -> PolicyDecision | None:
        mode = self.permission_mode
        if mode == "workspace-write":
            return None
        if mode == "danger-full-access":
            return PolicyDecision(
                action=ALLOW,
                permission_domain=permission_domain,
                reason="Allowed by danger-full-access permission mode.",
                target=target,
                details=details,
            )
        if mode == "prompt":
            if self._is_high_confidence_inspect(permission_domain=permission_domain, details=details):
                return PolicyDecision(
                    action=ALLOW,
                    permission_domain=permission_domain,
                    reason="High-confidence inspect call allowed by prompt permission mode.",
                    target=target,
                    details=details,
                )
            return PolicyDecision(
                action=ASK,
                permission_domain=permission_domain,
                reason="Tool call requires host-side approval by prompt permission mode.",
                target=target,
                details=details,
            )
        if mode == "read-only":
            if self._is_read_only_allowed(permission_domain=permission_domain, details=details):
                return PolicyDecision(
                    action=ALLOW,
                    permission_domain=permission_domain,
                    reason="Read-only permission mode allows this inspect call.",
                    target=target,
                    details=details,
                )
            return PolicyDecision(
                action=DENY,
                permission_domain=permission_domain,
                reason="Read-only permission mode denies this tool call.",
                target=target,
                details=details,
            )
        return None

    @staticmethod
    def _matches_any(tool_name: str, patterns: list[str]) -> bool:
        return any(fnmatch.fnmatch(tool_name, pattern) for pattern in patterns)

    @staticmethod
    def _is_high_confidence_inspect(*, permission_domain: str, details: dict[str, Any]) -> bool:
        return (
            permission_domain in {PermissionDomain.READ, PermissionDomain.REPO}
            and details.get("risk_class") == "inspect"
            and details.get("confidence_band") == CONFIDENCE_HIGH
            and not details.get("requests_network")
            and not details.get("destructive_hint")
            and not details.get("touches_external")
        )

    def _is_read_only_allowed(self, *, permission_domain: str, details: dict[str, Any]) -> bool:
        if details.get("requests_network") or details.get("destructive_hint") or details.get("touches_external"):
            return False
        if permission_domain == PermissionDomain.READ:
            risk_class = details.get("risk_class")
            return risk_class in {None, "inspect"}
        return self._is_high_confidence_inspect(permission_domain=permission_domain, details=details)

    def _details(self, *, permission_domain: str, analysis: dict[str, Any] | None) -> dict[str, Any]:
        if not analysis:
            return {"family": None, "risk_class": None, "confidence_band": CONFIDENCE_UNKNOWN}
        return {
            "family": analysis.get("family"),
            "risk_class": analysis.get("risk_class"),
            "confidence_band": analysis.get("confidence_band", CONFIDENCE_UNKNOWN),
            "declaration_strength": analysis.get("declaration_strength"),
            "touches_external": analysis.get("touches_external", False),
            "touches_workspace": analysis.get("touches_workspace", False),
            "requests_network": analysis.get("requests_network", False),
            "destructive_hint": analysis.get("destructive_hint", False),
            "protected_path_hint": analysis.get("protected_path_hint", False),
            "known_safe_inspect": analysis.get("known_safe_inspect", False),
            "non_side_effectful": analysis.get("non_side_effectful", False),
            "flags": analysis.get("flags", []),
            "writes_workspace_files": analysis.get("writes_workspace_files", False),
            "summary": analysis.get("summary"),
        }

    def _is_within_workspace(self, path: Path) -> bool:
        resolved = path.resolve()
        return resolved == self.workspace or self.workspace in resolved.parents

    def is_protected(self, path: Path) -> bool:
        return is_protected_path(self.workspace, path)

    def is_within_workspace(self, path: Path) -> bool:
        return self._is_within_workspace(path)
