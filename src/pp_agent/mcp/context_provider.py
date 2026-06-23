from __future__ import annotations

from importlib import import_module
import json
from typing import Any, Optional

from pp_agent.mcp.config import MCPServerConfig
from pp_agent.mcp.descriptors import MCPPromptDescriptor, MCPResourceDescriptor, MCPToolDescriptor
from pp_agent.mcp.manager import MCPManager
from pp_agent.mcp.security_scan import MCPMetadataScanResult, scan_mcp_metadata


class MCPContextProvider:
    """Build trace-safe MCP descriptor cards without executing MCP capabilities."""

    def __init__(self, manager: MCPManager) -> None:
        self.manager = manager
        self.dropped_items: list[Any] = []

    def tool_cards(self, server_name: str) -> list[Any]:
        """Return safe MCP tool descriptor cards for one server."""

        self.dropped_items = []
        server = self.manager.server_config(server_name)
        items: list[Any] = []
        for descriptor in self.manager.list_mcp_tools(server_name):
            card = self._tool_card(server, descriptor)
            if card is not None:
                items.append(card)
        return items

    def resource_cards(self, server_name: str) -> list[Any]:
        """Return safe MCP resource descriptor cards without reading resources."""

        self.dropped_items = []
        server = self.manager.server_config(server_name)
        items: list[Any] = []
        for descriptor in self.manager.list_mcp_resources(server_name):
            try:
                items.append(self._resource_card(server, descriptor))
            except MCPContextDrop:
                continue
        return items

    def prompt_cards(self, server_name: str) -> list[Any]:
        """Return safe MCP prompt descriptor cards without executing prompts."""

        self.dropped_items = []
        server = self.manager.server_config(server_name)
        items: list[Any] = []
        for descriptor in self.manager.list_mcp_prompts(server_name):
            try:
                items.append(self._prompt_card(server, descriptor))
            except MCPContextDrop:
                continue
        return items

    def _tool_card(self, server: MCPServerConfig, descriptor: MCPToolDescriptor) -> Optional[Any]:
        """Create one MCP tool ContextItem or record why it was dropped."""

        target_id = f"mcp:{server.name}:tool:{descriptor.name}"
        if self._tool_denied(server, descriptor.name):
            self._record_drop(target_id, "capability", descriptor.name, "mcp_tool_denied", descriptor.risk_level)
            return None
        risk_level = server.tool_risk_overrides.get(descriptor.name, descriptor.risk_level)
        approval_mode = server.tool_approval_overrides.get(descriptor.name, descriptor.approval_mode)
        scan = self._scan_descriptor(target_id, "mcp_tool", descriptor.description, descriptor.metadata, descriptor.input_schema)
        if not scan.safe_for_context:
            self._record_drop(target_id, "capability", descriptor.name, "mcp_metadata_scan_high_risk", risk_level, scan)
            return None
        content = self._card_content(
            server_name=server.name,
            kind="tool",
            name_or_uri=descriptor.name,
            description=descriptor.description,
            risk_level=risk_level,
            approval_mode=approval_mode,
            is_remote=descriptor.is_remote,
            requires_auth=descriptor.requires_auth,
            schema=descriptor.input_schema,
        )
        return self._context_item(target_id, descriptor.name, content, "mcp_tool", scan, risk_level, approval_mode)

    def _resource_card(self, server: MCPServerConfig, descriptor: MCPResourceDescriptor) -> Any:
        """Create one MCP resource descriptor ContextItem."""

        target_id = f"mcp:{server.name}:resource:{descriptor.uri}"
        scan = self._scan_descriptor(target_id, "mcp_resource", descriptor.description, descriptor.metadata, {"mime_type": descriptor.mime_type})
        if not scan.safe_for_context:
            self._record_drop(target_id, "capability", descriptor.name or descriptor.uri, "mcp_metadata_scan_high_risk", descriptor.risk_level, scan)
            raise MCPContextDrop("mcp_metadata_scan_high_risk")
        content = self._card_content(
            server_name=server.name,
            kind="resource",
            name_or_uri=descriptor.uri,
            description=descriptor.description,
            risk_level=descriptor.risk_level,
            approval_mode=descriptor.approval_mode,
            is_remote=descriptor.is_remote,
            requires_auth=descriptor.requires_auth,
            schema={"mime_type": descriptor.mime_type, "name": descriptor.name},
        )
        return self._context_item(target_id, descriptor.name or descriptor.uri, content, "mcp_resource", scan, descriptor.risk_level, descriptor.approval_mode)

    def _prompt_card(self, server: MCPServerConfig, descriptor: MCPPromptDescriptor) -> Any:
        """Create one MCP prompt descriptor ContextItem."""

        target_id = f"mcp:{server.name}:prompt:{descriptor.name}"
        scan = self._scan_descriptor(target_id, "mcp_prompt", descriptor.description, descriptor.metadata, descriptor.arguments_schema)
        if not scan.safe_for_context:
            self._record_drop(target_id, "capability", descriptor.name, "mcp_metadata_scan_high_risk", descriptor.risk_level, scan)
            raise MCPContextDrop("mcp_metadata_scan_high_risk")
        content = self._card_content(
            server_name=server.name,
            kind="prompt",
            name_or_uri=descriptor.name,
            description=descriptor.description,
            risk_level=descriptor.risk_level,
            approval_mode=descriptor.approval_mode,
            is_remote=descriptor.is_remote,
            requires_auth=descriptor.requires_auth,
            schema=descriptor.arguments_schema,
        )
        return self._context_item(target_id, descriptor.name, content, "mcp_prompt", scan, descriptor.risk_level, descriptor.approval_mode)

    def _tool_denied(self, server: MCPServerConfig, tool_name: str) -> bool:
        """Apply MCP permission overlay for context exposure."""

        if tool_name in set(server.denied_tools):
            return True
        allowed = set(server.allowed_tools)
        return bool(allowed) and tool_name not in allowed

    def _context_item(
        self,
        item_id: str,
        title: str,
        content: str,
        target_type: str,
        scan: MCPMetadataScanResult,
        risk_level: str,
        approval_mode: str,
    ) -> Any:
        """Build a safe ContextItem for an MCP descriptor card."""

        return _context_item(
            id=item_id,
            type="capability",
            title=title,
            content=content,
            source_ref=_source_ref(source_type="capability", source_id=item_id),
            priority=50,
            metadata={
                "context_provider": "mcp",
                "target_type": target_type,
                "risk_level": risk_level,
                "approval_mode": approval_mode,
                "scan": scan.model_dump(mode="json"),
            },
        )

    def _record_drop(
        self,
        item_id: str,
        item_type: str,
        title: str,
        reason: str,
        risk_level: str,
        scan: Optional[MCPMetadataScanResult] = None,
    ) -> None:
        """Record a dropped MCP card in BudgetReport-compatible form."""

        source_ref: dict[str, object] = {"source_type": "capability", "source_id": item_id, "risk_level": risk_level}
        if scan is not None:
            source_ref["scan"] = {
                "risk": scan.risk,
                "flags": list(scan.flags),
                "safe_for_context": scan.safe_for_context,
                "reason": scan.reason,
            }
        self.dropped_items.append(
            _context_item_summary(
                id=item_id,
                type=item_type,
                title=title,
                section="selected_capabilities",
                priority=50,
                estimated_chars=0,
                source_ref=source_ref,
                reason=reason,
            )
        )

    def _scan_descriptor(self, target_id: str, target_type: str, description: str, metadata: dict[str, Any], schema: dict[str, Any]) -> MCPMetadataScanResult:
        """Run deterministic safety scan over descriptor summary text."""

        text = "\n".join([description or "", _schema_summary(schema), _safe_metadata_text(metadata)])
        return scan_mcp_metadata(target_id=target_id, target_type=target_type, text=text)

    @staticmethod
    def _card_content(
        *,
        server_name: str,
        kind: str,
        name_or_uri: str,
        description: str,
        risk_level: str,
        approval_mode: str,
        is_remote: bool,
        requires_auth: bool,
        schema: dict[str, Any],
    ) -> str:
        """Render a compact MCP descriptor card for model context."""

        return (
            f"MCP {kind}: {name_or_uri}\n"
            f"Server: {server_name}\n"
            f"Description: {description or '-'}\n"
            f"Risk: {risk_level}\n"
            f"Approval: {approval_mode}\n"
            f"Remote: {is_remote}\n"
            f"Requires auth: {requires_auth}\n"
            f"Schema: {_schema_summary(schema)}"
        )


def _schema_summary(schema: dict[str, Any]) -> str:
    """Summarize schema keys without copying raw metadata wholesale."""

    if not schema:
        return "{}"
    keys = sorted(str(key) for key in schema.keys())[:12]
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    property_keys = sorted(str(key) for key in properties.keys())[:12]
    return json.dumps({"keys": keys, "properties": property_keys}, ensure_ascii=False, sort_keys=True)


def _safe_metadata_text(metadata: dict[str, Any]) -> str:
    """Extract short scalar metadata text for scanning only."""

    parts: list[str] = []
    for key, value in metadata.items():
        if any(marker in str(key).lower() for marker in ("secret", "token", "password", "api_key")):
            continue
        if isinstance(value, (str, int, float, bool)):
            parts.append(f"{key}: {value}")
    return "\n".join(parts)


class MCPContextDrop(ValueError):
    """Internal signal used to skip unsafe MCP descriptor cards."""


def _context_item(**kwargs: Any) -> Any:
    """Construct ContextItem lazily to preserve MCP module import boundaries."""

    return import_module("pp_agent.context.item").ContextItem(**kwargs)


def _source_ref(**kwargs: Any) -> Any:
    """Construct SourceRef lazily to preserve MCP module import boundaries."""

    return import_module("pp_agent.context.source_ref").SourceRef(**kwargs)


def _context_item_summary(**kwargs: Any) -> Any:
    """Construct ContextItemSummary lazily to preserve MCP module import boundaries."""

    return import_module("pp_agent.context.budget").ContextItemSummary(**kwargs)
