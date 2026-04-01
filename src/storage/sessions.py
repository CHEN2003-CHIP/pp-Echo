from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from agent_core.runtime.types import QueuedMessage
from agent_core.types import ChatMessage, CompactionState, ModelConfig, TextPart, ToolCall


class SessionMetadata(BaseModel):
    id: str
    parent_id: Optional[str] = None
    created_at: float
    updated_at: float
    model: ModelConfig = Field(default_factory=ModelConfig)
    system_prompt: str
    compaction: CompactionState = Field(default_factory=CompactionState)
    pending_tool_calls: list[ToolCall] = Field(default_factory=list)
    pending_plan_token: Optional[str] = None
    queued_messages: list[QueuedMessage] = Field(default_factory=list)


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

    @property
    def pending_tool_calls(self) -> list[ToolCall]:
        return self.metadata.pending_tool_calls

    @property
    def pending_plan_token(self) -> Optional[str]:
        return self.metadata.pending_plan_token

    @property
    def queued_messages(self) -> list[QueuedMessage]:
        return self.metadata.queued_messages


class SessionTreeEntry(BaseModel):
    id: str
    parent_id: Optional[str] = None
    updated_at: float
    model: str
    message_count: int
    turn_count: int
    pending_plan_token: Optional[str] = None
    summary_preview: str = ""
    last_user_preview: str = ""
    last_assistant_preview: str = ""


class SessionStore:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self.tree_path = self.root / "session-tree.jsonl"
        self._migrate_legacy_files()

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
        sessions = self._load_all_records()
        sessions[record.id] = record.model_copy(deep=True)
        self._write_all_records(sessions)
        return self.tree_path

    def load(self, session_id: str) -> SessionRecord:
        sessions = self._load_all_records()
        if session_id not in sessions:
            raise FileNotFoundError(f"Session not found: {session_id}")
        return sessions[session_id].model_copy(deep=True)

    def list(self) -> list[SessionMetadata]:
        sessions = self._load_all_records()
        return [record.metadata.model_copy(deep=True) for record in sorted(sessions.values(), key=lambda item: item.metadata.updated_at, reverse=True)]

    def fork(self, session_id: str) -> SessionRecord:
        source = self.load(session_id)
        forked = self.create(source.system_prompt, source.model)
        forked.metadata.parent_id = source.id
        forked.metadata.compaction = source.compaction.model_copy(deep=True)
        forked.metadata.pending_tool_calls = [call.model_copy(deep=True) for call in source.pending_tool_calls]
        forked.metadata.pending_plan_token = source.pending_plan_token
        forked.metadata.queued_messages = [item.model_copy(deep=True) for item in source.queued_messages]
        forked.messages = list(source.messages)
        return forked

    def rewind(self, session_id: str, message_count: int) -> SessionRecord:
        source = self.load(session_id)
        if message_count < 0 or message_count > len(source.messages):
            raise ValueError(f"message_count must be between 0 and {len(source.messages)}")
        rewound = self.create(source.system_prompt, source.model)
        rewound.metadata.parent_id = source.id
        rewound.metadata.compaction = CompactionState()
        rewound.metadata.pending_tool_calls = []
        rewound.metadata.pending_plan_token = None
        rewound.metadata.queued_messages = []
        rewound.messages = [message.model_copy(deep=True) for message in source.messages[:message_count]]
        return rewound

    def rewind_turns(self, session_id: str, turn_count: int) -> SessionRecord:
        source = self.load(session_id)
        total_turns = self._turn_count(source)
        if turn_count < 0 or turn_count > total_turns:
            raise ValueError(f"turn_count must be between 0 and {total_turns}")
        if turn_count == total_turns:
            message_count = len(source.messages)
        else:
            seen_turns = 0
            message_count = len(source.messages)
            for index, message in enumerate(source.messages):
                if message.role == "user":
                    seen_turns += 1
                    if seen_turns == turn_count + 1:
                        message_count = index
                        break
        return self.rewind(session_id, message_count)

    def tree(self) -> list[SessionTreeEntry]:
        sessions = self._load_all_records()
        entries = [self._entry_for_record(record) for record in sessions.values()]
        return sorted(entries, key=lambda item: (item.parent_id or "", item.updated_at, item.id))

    def children_of(self, session_id: str) -> list[SessionTreeEntry]:
        return [entry for entry in self.tree() if entry.parent_id == session_id]

    def describe(self, session_id: str) -> dict[str, object]:
        sessions = self._load_all_records()
        if session_id not in sessions:
            raise FileNotFoundError(f"Session not found: {session_id}")
        record = sessions[session_id]
        parent = sessions.get(record.parent_id) if record.parent_id else None
        children = [child for child in sessions.values() if child.parent_id == session_id]
        return {
            "current": self._entry_for_record(record).model_dump(mode="json"),
            "parent": self._entry_for_record(parent).model_dump(mode="json") if parent is not None else None,
            "children": [self._entry_for_record(child).model_dump(mode="json") for child in sorted(children, key=lambda item: item.metadata.updated_at, reverse=True)],
        }

    def _entry_for_record(self, record: SessionRecord) -> SessionTreeEntry:
        return SessionTreeEntry(
            id=record.id,
            parent_id=record.parent_id,
            updated_at=record.metadata.updated_at,
            model=record.model.model,
            message_count=len(record.messages),
            turn_count=self._turn_count(record),
            pending_plan_token=record.pending_plan_token,
            summary_preview=self._summary_preview(record),
            last_user_preview=self._last_role_preview(record, "user"),
            last_assistant_preview=self._last_role_preview(record, "assistant"),
        )

    @staticmethod
    def _last_role_preview(record: SessionRecord, role: str, limit: int = 96) -> str:
        for message in reversed(record.messages):
            if message.role == role:
                return SessionStore._preview_text(SessionStore._message_text(message), limit=limit)
        return ""

    @staticmethod
    def _summary_preview(record: SessionRecord, limit: int = 96) -> str:
        if record.compaction.summary:
            return SessionStore._preview_text(record.compaction.summary, limit=limit)
        if not record.messages:
            return ""
        return SessionStore._preview_text(SessionStore._message_text(record.messages[-1]), limit=limit)

    @staticmethod
    def _message_text(message: ChatMessage) -> str:
        parts: list[str] = []
        for part in message.content:
            if isinstance(part, TextPart):
                parts.append(part.text)
        return " ".join(item.strip() for item in parts if item.strip())

    @staticmethod
    def _preview_text(value: str, limit: int = 96) -> str:
        clean = " ".join(value.replace("\r", " ").replace("\n", " ").split())
        if len(clean) <= limit:
            return clean
        return clean[: limit - 3] + "..."


    @staticmethod
    def _turn_count(record: SessionRecord) -> int:
        return sum(1 for message in record.messages if message.role == "user")

    def _load_all_records(self) -> dict[str, SessionRecord]:
        if not self.tree_path.exists():
            return {}
        sessions: dict[str, SessionRecord] = {}
        for line in self.tree_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("type") != "session":
                continue
            record = SessionRecord.model_validate(item["data"])
            sessions[record.id] = record
        return sessions

    def _write_all_records(self, sessions: dict[str, SessionRecord]) -> None:
        ordered = sorted(sessions.values(), key=lambda item: (item.metadata.created_at, item.id))
        lines = [json.dumps({"type": "session", "data": record.model_dump(mode="json")}, ensure_ascii=False) for record in ordered]
        self.tree_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    def _migrate_legacy_files(self) -> None:
        if self.tree_path.exists():
            return
        legacy_paths = sorted(path for path in self.root.glob("*.jsonl") if path.name != self.tree_path.name)
        if not legacy_paths:
            return
        sessions: dict[str, SessionRecord] = {}
        for path in legacy_paths:
            metadata: Optional[SessionMetadata] = None
            messages: list[ChatMessage] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                if item.get("type") == "metadata":
                    metadata = SessionMetadata.model_validate(item["data"])
                elif item.get("type") == "message":
                    messages.append(ChatMessage.model_validate(item["data"]))
            if metadata is not None:
                sessions[metadata.id] = SessionRecord(metadata=metadata, messages=messages)
        if sessions:
            self._write_all_records(sessions)
