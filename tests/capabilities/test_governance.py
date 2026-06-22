from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from pp_agent.capabilities import (
    CapabilityBinding,
    CapabilityCatalog,
    CapabilityDescriptor,
    CapabilityPolicy,
    CapabilityRouteContext,
    CapabilityRouter,
)
from pp_agent.capabilities.discovery import BuiltinToolCapabilityDiscoveryProvider
from pp_agent.capabilities import discovery as discovery_module
from pp_agent.capabilities.trace import build_capability_selected_event_payload
from pp_agent.tools.registry import ToolRegistry


class StaticProvider:
    def __init__(self, descriptors: list[CapabilityDescriptor]) -> None:
        self._descriptors = descriptors

    def discover(self) -> list[CapabilityDescriptor]:
        return [item.model_copy(deep=True) for item in self._descriptors]


def test_capability_descriptor_secret_rejection() -> None:
    with pytest.raises(ValueError, match="sensitive key"):
        CapabilityDescriptor(
            id="demo",
            kind="builtin_tool",
            name="demo",
            description="demo",
            source="builtin:demo",
            metadata={"nested": {"api_key": "secret"}},
        )


def test_capability_descriptor_v3_rejects_legacy_aliases_and_risk() -> None:
    with pytest.raises(ValueError):
        CapabilityDescriptor(
            id="legacy.path",
            kind="builtin_tool",
            name="legacy.path",
            description="legacy",
            source="builtin:legacy.path",
            path="/tmp/legacy",
        )

    with pytest.raises(ValueError):
        CapabilityDescriptor(
            id="legacy.risk",
            kind="builtin_tool",
            name="legacy.risk",
            description="legacy",
            source="builtin:legacy.risk",
            risk_level="low",
        )


def test_capability_catalog_lists_builtin_tools(tmp_path: Path) -> None:
    catalog = CapabilityCatalog([BuiltinToolCapabilityDiscoveryProvider(ToolRegistry(tmp_path))])

    run_shell = catalog.get("builtin_tool", "run_shell")

    assert run_shell.kind == "builtin_tool"
    assert run_shell.id == "run_shell"
    assert run_shell.input_schema is not None
    assert run_shell.risk_level == "shell"


def test_capability_binding_denies_shell_for_qq_group() -> None:
    descriptor = CapabilityDescriptor(
        id="shell.exec",
        kind="builtin_tool",
        name="shell.exec",
        description="shell",
        source="builtin:shell.exec",
        risk_level="shell",
    )
    binding = CapabilityBinding(
        id="deny-shell-group",
        capability_id="shell.exec",
        scope_type="connector",
        scope_id="qqbot",
        enabled=True,
        approval_policy="deny",
        denied_trust_levels=["group"],
        reason="denied_by_trust_level",
    )

    reason = CapabilityPolicy().block_reason(
        descriptor,
        [binding],
        CapabilityRouteContext(connector_id="qqbot", trust_level="group"),
    )

    assert reason == "denied_by_trust_level"


def test_capability_policy_prefers_more_specific_binding() -> None:
    descriptor = CapabilityDescriptor(
        id="tool.read",
        kind="builtin_tool",
        name="tool.read",
        description="read",
        source="builtin:tool.read",
        risk_level="read",
    )
    bindings = [
        CapabilityBinding(
            id="global-deny",
            capability_id="tool.read",
            scope_type="global",
            approval_policy="deny",
            reason="global_denied",
        ),
        CapabilityBinding(
            id="session-allow",
            capability_id="tool.read",
            scope_type="session",
            scope_id="s1",
            approval_policy="never",
            reason="session_allowed",
        ),
    ]

    reason = CapabilityPolicy().block_reason(
        descriptor,
        bindings,
        CapabilityRouteContext(session_id="s1"),
    )

    assert reason is None


def test_v3_discovery_uses_native_descriptor_fields() -> None:
    source = inspect.getsource(discovery_module)

    assert "legacy_descriptor_metadata" not in source
    assert "normalize_legacy_risk" not in source
    assert "pp_agent.capabilities.compatibility" not in source
    assert "path=str(" not in source
    assert "origin_type=" not in source


def test_capability_router_prioritizes_safe_read() -> None:
    catalog = CapabilityCatalog(
        [
            StaticProvider(
                [
                    CapabilityDescriptor(id="write.file", kind="builtin_tool", name="write.file", description="file", source="builtin:write", risk_level="write"),
                    CapabilityDescriptor(id="read.file", kind="builtin_tool", name="read.file", description="file", source="builtin:read", risk_level="read"),
                    CapabilityDescriptor(id="safe.inspect", kind="builtin_tool", name="safe.inspect", description="file", source="builtin:safe", risk_level="safe"),
                    CapabilityDescriptor(id="shell.exec", kind="builtin_tool", name="shell.exec", description="file", source="builtin:shell", risk_level="shell"),
                ]
            )
        ]
    )

    selection = CapabilityRouter().select("file", catalog, [], CapabilityRouteContext())

    assert [item.id for item in selection.selected] == ["safe.inspect", "read.file", "write.file", "shell.exec"]


def test_capability_router_respects_max_capabilities() -> None:
    catalog = CapabilityCatalog(
        [
            StaticProvider(
                [
                    CapabilityDescriptor(id=f"read.{index}", kind="builtin_tool", name=f"read.{index}", description="read", source=f"builtin:{index}", risk_level="read")
                    for index in range(5)
                ]
            )
        ]
    )

    selection = CapabilityRouter().select("read", catalog, [], CapabilityRouteContext(), max_capabilities=2)

    assert len(selection.selected) == 2


def test_capability_selected_trace_event_shape() -> None:
    catalog = CapabilityCatalog(
        [
            StaticProvider(
                [
                    CapabilityDescriptor(id="attachment.search", kind="builtin_tool", name="attachment.search", description="search", source="builtin:attachment", risk_level="read"),
                    CapabilityDescriptor(id="shell.exec", kind="builtin_tool", name="shell.exec", description="shell", source="builtin:shell", risk_level="shell"),
                ]
            )
        ]
    )
    binding = CapabilityBinding(
        id="deny-shell",
        capability_id="shell.exec",
        scope_type="connector",
        scope_id="qqbot",
        approval_policy="deny",
    )
    context = CapabilityRouteContext(bot_id="qq-main", connector_id="qqbot", trust_level="group", workspace_id="demo")

    selection = CapabilityRouter().select("search shell", catalog, [binding], context, max_capabilities=8)
    payload = build_capability_selected_event_payload(selection, context, max_capabilities=8)

    assert payload["type"] == "capability_selected"
    assert payload["selected"] == [{"id": "attachment.search", "kind": "builtin_tool", "risk_level": "read"}]
    assert payload["blocked"][0]["id"] == "shell.exec"
    assert payload["policy_context"]["bot_id"] == "qq-main"
    assert payload["policy_context"]["trust_level"] == "group"
