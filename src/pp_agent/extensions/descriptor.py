from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class ExtensionDescriptor(BaseModel):
    name: str
    description: str
    path: Optional[Path] = None
    entrypoint: Optional[str] = None
    provides: list[str] = Field(default_factory=list)
    origin_type: str = "project"
    root_name: Optional[str] = None
    precedence: int = 0
    declared_by_manifest: bool = False
