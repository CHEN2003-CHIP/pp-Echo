from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Union

from pp_agent.domain import ChatMessage, ToolCall, ToolResult, ToolSpec
from pp_agent.extensions.descriptor import ExtensionDescriptor
from pp_agent.runtime.hooks import AfterToolCallHook, BeforeToolCallHook, ToolErrorHook, TransformContextHook

ExtensionToolHandler = Callable[[Path, dict[str, Any]], Union[str, ToolResult]]
ExtensionCommandHandler = Callable[[Any, str, Path], Optional[str]]
ExtensionCleanupHandler = Callable[[], object]


@dataclass
class ExtensionToolDefinition:
    name: str
    spec: ToolSpec
    handler: ExtensionToolHandler
    category: str = "extension"


@dataclass
class ExtensionCommandDefinition:
    name: str
    handler: ExtensionCommandHandler
    description: str = ""


@dataclass
class LoadedExtension:
    descriptor: ExtensionDescriptor
    tools: list[ExtensionToolDefinition] = field(default_factory=list)
    commands: list[ExtensionCommandDefinition] = field(default_factory=list)
    transform_context_hooks: list[TransformContextHook] = field(default_factory=list)
    before_tool_call_hooks: list[BeforeToolCallHook] = field(default_factory=list)
    after_tool_call_hooks: list[AfterToolCallHook] = field(default_factory=list)
    tool_error_hooks: list[ToolErrorHook] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    cleanup_callbacks: list[ExtensionCleanupHandler] = field(default_factory=list)


@dataclass
class ExtensionCommandRegistry:
    commands: dict[str, ExtensionCommandDefinition] = field(default_factory=dict)

    def register(self, definition: ExtensionCommandDefinition, *, replace: bool = False) -> None:
        if not replace and definition.name in self.commands:
            raise ValueError(f"Duplicate extension command registered: {definition.name}")
        self.commands[definition.name] = definition

    def dispatch(self, raw: str, agent: Any, workspace: Path) -> Optional[str]:
        if not raw.startswith("/"):
            return None
        command, _, arg_text = raw[1:].partition(" ")
        definition = self.commands.get(command)
        if definition is None:
            return None
        result = definition.handler(agent, arg_text.strip(), workspace)
        return "handled" if result is None else result

    def list_names(self) -> list[str]:
        return sorted(self.commands)

    def clear(self) -> None:
        self.commands.clear()


class ExtensionAPI:
    def __init__(self, descriptor: ExtensionDescriptor) -> None:
        self._descriptor = descriptor
        self._loaded = LoadedExtension(descriptor=descriptor)

    @property
    def descriptor(self) -> ExtensionDescriptor:
        return self._descriptor

    def register_tool(
        self,
        *,
        name: str,
        description: str,
        handler: ExtensionToolHandler,
        parameters: Optional[dict[str, Any]] = None,
        requires_confirmation: bool = False,
        category: str = "extension",
    ) -> None:
        self._loaded.tools.append(
            ExtensionToolDefinition(
                name=name,
                spec=ToolSpec(
                    name=name,
                    description=description,
                    parameters=parameters or {"type": "object", "properties": {}},
                    requires_confirmation=requires_confirmation,
                ),
                handler=handler,
                category=category,
            )
        )

    def register_command(self, name: str, handler: ExtensionCommandHandler, *, description: str = "") -> None:
        self._loaded.commands.append(ExtensionCommandDefinition(name=name, handler=handler, description=description))

    def on_context_built(self, hook: TransformContextHook) -> None:
        self._loaded.transform_context_hooks.append(hook)

    def on_before_tool_call(self, hook: BeforeToolCallHook) -> None:
        self._loaded.before_tool_call_hooks.append(hook)

    def on_after_tool_call(self, hook: AfterToolCallHook) -> None:
        self._loaded.after_tool_call_hooks.append(hook)

    def on_tool_error(self, hook: ToolErrorHook) -> None:
        self._loaded.tool_error_hooks.append(hook)

    def register_resource(self, name: str) -> None:
        self._loaded.resources.append(name)

    def on_unload(self, callback: ExtensionCleanupHandler) -> None:
        self._loaded.cleanup_callbacks.append(callback)

    def build(self) -> LoadedExtension:
        return LoadedExtension(
            descriptor=self._loaded.descriptor,
            tools=list(self._loaded.tools),
            commands=list(self._loaded.commands),
            transform_context_hooks=list(self._loaded.transform_context_hooks),
            before_tool_call_hooks=list(self._loaded.before_tool_call_hooks),
            after_tool_call_hooks=list(self._loaded.after_tool_call_hooks),
            tool_error_hooks=list(self._loaded.tool_error_hooks),
            resources=list(self._loaded.resources),
            cleanup_callbacks=list(self._loaded.cleanup_callbacks),
        )


__all__ = [
    "ExtensionAPI",
    "ExtensionCommandDefinition",
    "ExtensionCommandHandler",
    "ExtensionCommandRegistry",
    "ExtensionCleanupHandler",
    "ExtensionToolDefinition",
    "ExtensionToolHandler",
    "LoadedExtension",
]

