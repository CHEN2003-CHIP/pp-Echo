from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class AgentStepManifest(BaseModel):
    agent: str
    status: str
    summary: str
    findings: list[str] = Field(default_factory=list)
    inspected_paths: list[str] = Field(default_factory=list)
    staged_actions: list[dict[str, str]] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence: str = "unknown"
    error_message: Optional[str] = None
    failure_kind: Optional[str] = None

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: str) -> str:
        normalized = (value or "unknown").strip().lower()
        if normalized not in {"high", "medium", "low", "unknown"}:
            return "unknown"
        return normalized

    @model_validator(mode="after")
    def _validate_required_fields(self) -> "AgentStepManifest":
        if not self.summary.strip():
            raise ValueError("AgentStepManifest.summary is required")
        for action in self.staged_actions:
            missing = [key for key in ("token", "path", "action_type") if not str(action.get(key) or "").strip()]
            if missing:
                raise ValueError(f"staged_actions must include token/path/action_type; missing {missing}")
        return self


def validate_manifest(manifest) -> AgentStepManifest:
    if isinstance(manifest, AgentStepManifest):
        return manifest
    return AgentStepManifest.model_validate(manifest)


class Blackboard:
    def __init__(self) -> None:
        self._manifests: dict[str, AgentStepManifest] = {}

    def put(self, node_id: str, manifest: AgentStepManifest) -> None:
        self._manifests[node_id] = validate_manifest(manifest)

    def get(self, node_id: str) -> Optional[AgentStepManifest]:
        return self._manifests.get(node_id)

    def for_dependencies(self, depends_on: list[str]) -> list[AgentStepManifest]:
        return [manifest for node_id in depends_on if (manifest := self._manifests.get(node_id)) is not None]


__all__ = ["AgentStepManifest", "Blackboard", "validate_manifest"]
