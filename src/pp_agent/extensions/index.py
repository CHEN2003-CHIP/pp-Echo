from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from pp_agent.extensions.descriptor import ExtensionDescriptor


BUILTIN_EXTENSIONS_DIR = Path(__file__).resolve().parent


class ExtensionSearchRoot(BaseModel):
    path: Path
    origin_type: str
    root_name: Optional[str] = None
    precedence: int = 0
    declared_by_manifest: bool = False


class _DefaultExtensionConfig:
    enable_project = True
    enable_user = True
    enable_builtin = False
    custom_directories: list[str] = []
    ignored: list[str] = []
    include: list[str] = []


DEFAULT_EXTENSION_CONFIG = _DefaultExtensionConfig()


class _ExtensionFilePayload(BaseModel):
    name: str
    description: str
    entrypoint: Optional[str] = None
    provides: list[str] = Field(default_factory=list)


def extension_search_roots(workspace: Path, user_root: Path, config: Any = None) -> list[ExtensionSearchRoot]:
    config = config or DEFAULT_EXTENSION_CONFIG
    roots: list[ExtensionSearchRoot] = []
    precedence = 0
    for value in getattr(config, "custom_directories", []):
        path = Path(value).expanduser()
        roots.append(ExtensionSearchRoot(path=path, origin_type="custom", root_name=path.name, precedence=precedence))
        precedence += 1
    if getattr(config, "enable_project", True):
        roots.append(
            ExtensionSearchRoot(
                path=_safe_resolve(workspace) / ".pp-agent" / "extensions",
                origin_type="project",
                root_name="project_extensions",
                precedence=precedence,
            )
        )
        precedence += 1
    if getattr(config, "enable_user", True):
        roots.append(
            ExtensionSearchRoot(
                path=_safe_resolve(user_root) / "extensions",
                origin_type="user",
                root_name="user_extensions",
                precedence=precedence,
            )
        )
        precedence += 1
    if getattr(config, "enable_builtin", False):
        roots.append(
            ExtensionSearchRoot(
                path=BUILTIN_EXTENSIONS_DIR,
                origin_type="builtin",
                root_name="builtin_extensions",
                precedence=precedence,
            )
        )
    return roots


def load_extensions(
    workspace: Path,
    user_root: Path,
    config: Any = None,
    search_roots: Optional[list[ExtensionSearchRoot]] = None,
) -> dict[str, ExtensionDescriptor]:
    config = config or DEFAULT_EXTENSION_CONFIG
    roots = search_roots or extension_search_roots(workspace, user_root, config=config)
    extensions: dict[str, ExtensionDescriptor] = {}
    for root in reversed(roots):
        if not root.path.exists():
            continue
        descriptor_files = list(_iter_extension_descriptor_files(root.path))
        for descriptor_path in descriptor_files:
            descriptor = _load_extension_descriptor(descriptor_path, root)
            if not _extension_is_enabled(descriptor.name, config):
                continue
            extensions[descriptor.name] = descriptor
    return extensions


def _iter_extension_descriptor_files(root: Path):
    if (root / "EXTENSION.json").exists():
        yield root / "EXTENSION.json"
        return
    for path in sorted(root.glob("**/EXTENSION.json")):
        yield path


def _load_extension_descriptor(path: Path, root: ExtensionSearchRoot) -> ExtensionDescriptor:
    payload = _ExtensionFilePayload(**json.loads(path.read_text(encoding="utf-8")))
    extension_dir = path.parent
    return ExtensionDescriptor(
        name=payload.name,
        description=payload.description,
        path=extension_dir,
        entrypoint=payload.entrypoint,
        provides=payload.provides,
        origin_type=root.origin_type,
        root_name=root.root_name,
        precedence=root.precedence,
        declared_by_manifest=root.declared_by_manifest,
    )


def _extension_is_enabled(name: str, config: Any) -> bool:
    include = getattr(config, "include", [])
    ignored = getattr(config, "ignored", [])
    if include and not any(fnmatch.fnmatch(name, pattern) for pattern in include):
        return False
    if any(fnmatch.fnmatch(name, pattern) for pattern in ignored):
        return False
    return True


def _safe_resolve(path: Path) -> Path:
    candidate = path.expanduser()
    try:
        return candidate.resolve()
    except (OSError, PermissionError):
        return candidate.absolute()
