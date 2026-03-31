from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from agent_core.types import ChatMessage, CompactionState, ModelConfig


class SessionMetadata(BaseModel):
    id: str
    parent_id: Optional[str] = None
    created_at: float
    updated_at: float
    model: ModelConfig = Field(default_factory=ModelConfig)
    system_prompt: str
    compaction: CompactionState = Field(default_factory=CompactionState)


class SessionRecord(BaseModel):
    metadata: SessionMetadata
    messages: list[ChatMessage] = Field(default_factory=list)

    @property
    def id(self) -> str:
        return self.metadata.id

    @property
    def parent_id(self) -> Optional[str]:
        return self.metadata.parent_id

    @property
    def model(self) -> ModelConfig:
        return self.metadata.model

    @property
    def system_prompt(self) -> str:
        return self.metadata.system_prompt

    @property
    def compaction(self) -> CompactionState:
        return self.metadata.compaction


class SessionStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, system_prompt: str, model: ModelConfig) -> SessionRecord:
        now = time.time()
        return SessionRecord(
            metadata=SessionMetadata(
                id=str(uuid.uuid4()),
                created_at=now,
                updated_at=now,
                model=model.model_copy(deep=True),
                system_prompt=system_prompt,
            ),
            messages=[],
        )

    def save(self, record: SessionRecord) -> Path:
        record.metadata.updated_at = time.time()
        path = self.root / f"{record.id}.jsonl"
        lines = [
            json.dumps({"type": "metadata", "data": record.metadata.model_dump(mode="json")}, ensure_ascii=False),
            *[
                json.dumps({"type": "message", "data": message.model_dump(mode="json")}, ensure_ascii=False)
                for message in record.messages
            ],
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def load(self, session_id: str) -> SessionRecord:
        path = self.root / f"{session_id}.jsonl"
        metadata: Optional[SessionMetadata] = None
        messages: list[ChatMessage] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            if item["type"] == "metadata":
                metadata = SessionMetadata.model_validate(item["data"])
            elif item["type"] == "message":
                messages.append(ChatMessage.model_validate(item["data"]))
        if metadata is None:
            raise ValueError(f"Session metadata missing for {session_id}")
        return SessionRecord(metadata=metadata, messages=messages)

    def list(self) -> list[SessionMetadata]:
        sessions: list[SessionMetadata] = []
        for path in sorted(self.root.glob("*.jsonl")):
            try:
                first_line = path.read_text(encoding="utf-8").splitlines()[0]
                item = json.loads(first_line)
                if item["type"] == "metadata":
                    sessions.append(SessionMetadata.model_validate(item["data"]))
            except (IndexError, json.JSONDecodeError, KeyError, ValueError):
                continue
        return sessions

    def fork(self, session_id: str) -> SessionRecord:
        source = self.load(session_id)
        forked = self.create(source.system_prompt, source.model)
        forked.metadata.parent_id = source.id
        forked.metadata.compaction = source.compaction.model_copy(deep=True)
        forked.messages = list(source.messages)
        return forked