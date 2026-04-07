from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType
from pathlib import Path
from typing import Callable, Optional

from pp_agent.extensions.api import ExtensionAPI, LoadedExtension
from pp_agent.extensions.descriptor import ExtensionDescriptor


def load_extension_entrypoint(descriptor: ExtensionDescriptor) -> LoadedExtension:
    module, explicit_attr = _import_extension_module(descriptor)
    entrypoint = _resolve_entrypoint(module, explicit_attr)
    api = ExtensionAPI(descriptor)
    entrypoint(api)
    return api.build()


def _import_extension_module(descriptor: ExtensionDescriptor) -> tuple[ModuleType, Optional[str]]:
    """统一支持两种扩展加载模式，完美兼容本地文件扩展和第三方包扩展"""
    entrypoint = descriptor.entrypoint or "extension.py"
    if entrypoint.endswith(".py"):
        if descriptor.path is None:
            raise ValueError(f"Extension '{descriptor.name}' does not have a filesystem path for entrypoint {entrypoint!r}")
        module_path = (descriptor.path / entrypoint).resolve()
        if not module_path.exists():
            raise FileNotFoundError(f"Extension '{descriptor.name}' entrypoint not found: {module_path}")
        source = module_path.read_text(encoding="utf-8")
        module_name = f"pp_agent_extension_{descriptor.name}_{abs(hash(str(module_path)))}_{abs(hash(source))}"
        module = ModuleType(module_name)
        module.__file__ = str(module_path)
        exec(compile(source, str(module_path), "exec"), module.__dict__)
        return module, None

    module_name, explicit_attr = (entrypoint.split(":", 1) + [None])[:2] if ":" in entrypoint else (entrypoint, None)
    module = importlib.import_module(module_name)
    return module, explicit_attr


def _resolve_entrypoint(module: ModuleType, explicit_attr: Optional[str]) -> Callable[[ExtensionAPI], None]:
    """自动查找 / 定位扩展的初始化注册函数"""
    if explicit_attr:
        candidate = getattr(module, explicit_attr, None)
        if callable(candidate):
            return candidate
        raise AttributeError(f"Extension entrypoint {module.__name__}:{explicit_attr} is not callable")
    for name in ("register", "setup", "load_extension", "load"):
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate
    raise AttributeError(f"Extension module {module.__name__} must define a callable register(api) entrypoint")


__all__ = ["load_extension_entrypoint"]
