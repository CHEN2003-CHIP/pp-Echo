from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from pp_agent.extensions import ExtensionSearchRoot


class ResourceManifest(BaseModel):
    skills: list[str] = Field(default_factory=list)
    extensions: list[str] = Field(default_factory=list)
    prompts: list[str] = Field(default_factory=list)


class ManifestSkillRoot(BaseModel):
    path: Path
    origin_type: str
    root_name: Optional[str] = None
    precedence: int = 0
    declared_by_manifest: bool = False


def load_resource_manifest(project_dir: Path) -> ResourceManifest:
    manifest = ResourceManifest()
    resources_path = project_dir / "resources.json"
    package_path = project_dir / "package.json"
    if resources_path.exists():
        data = json.loads(resources_path.read_text(encoding="utf-8"))
        manifest = _merge_manifest(manifest, ResourceManifest(**data))
    if package_path.exists():
        data = json.loads(package_path.read_text(encoding="utf-8"))
        payload = data.get("pp-agent") or data.get("pp_agent") or data.get("pi") or {}
        manifest = _merge_manifest(manifest, ResourceManifest(**payload))
    return manifest


def manifest_skill_roots(project_dir: Path, entries: list[str], *, precedence_start: int = 0) -> list[ManifestSkillRoot]:
    return [
        ManifestSkillRoot(
            path=(project_dir / value).resolve(),
            origin_type="project",
            root_name=Path(value).name or value,
            precedence=precedence_start + index,
            declared_by_manifest=True,
        )
        for index, value in enumerate(entries)
    ]


def manifest_extension_roots(project_dir: Path, entries: list[str], *, precedence_start: int = 0) -> list[ExtensionSearchRoot]:
    return [
        ExtensionSearchRoot(
            path=(project_dir / value).resolve(),
            origin_type="project",
            root_name=Path(value).name or value,
            precedence=precedence_start + index,
            declared_by_manifest=True,
        )
        for index, value in enumerate(entries)
    ]


def _merge_manifest(base: ResourceManifest, override: ResourceManifest) -> ResourceManifest:
    merged = base.model_copy(deep=True)
    if override.skills:
        merged.skills = list(override.skills)
    if override.extensions:
        merged.extensions = list(override.extensions)
    if override.prompts:
        merged.prompts = list(override.prompts)
    return merged
