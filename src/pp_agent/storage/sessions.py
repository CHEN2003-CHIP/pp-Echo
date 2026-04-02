from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from pp_agent.llm.models import ModelConfig
from pp_agent.storage.migrations import load_legacy_session_payloads

from pp_agent.domain import QueuedMessage
from pp_agent.domain import ChatMessage, CompactionState, TextPart, ToolCall


class SessionTurnNode(BaseModel):
    id: str
    parent_id: Optional[str] = None
    start_message_index: int = 0
    end_message_index: int = 0
    created_at: float
    status: str = "committed"
    entry_type: Literal["turn", "compaction"] = "turn"
    summary: str = ""
    summarized_message_count: int = 0


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
    active_head_id: Optional[str] = None
    turn_nodes: list[SessionTurnNode] = Field(default_factory=list)


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

    @property
    def active_head_id(self) -> Optional[str]:
        return self.metadata.active_head_id

    @property
    def turn_nodes(self) -> list[SessionTurnNode]:
        return self.metadata.turn_nodes


class SessionTreeEntry(BaseModel):
    id: str
    parent_id: Optional[str] = None
    updated_at: float
    model: str
    message_count: int
    turn_count: int
    pending_plan_token: Optional[str] = None
    active_head_id: Optional[str] = None
    summary_preview: str = ""
    last_user_preview: str = ""
    last_assistant_preview: str = ""


class SessionTurnEntry(BaseModel):
    id: str
    parent_id: Optional[str] = None
    status: str = "committed"
    created_at: float
    entry_type: Literal["turn", "compaction"] = "turn"
    turn_number: int
    message_count: int
    total_message_count: int
    summarized_message_count: int = 0
    user_preview: str = ""
    assistant_preview: str = ""
    summary_preview: str = ""


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
        record = self._prepare_record_for_save(record)
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
        return self.fork_from_head(session_id, source.active_head_id)

    def fork_from_head(self, session_id: str, head_id: Optional[str]) -> SessionRecord:
        source = self.load(session_id)
        if head_id is not None and self.turn_node(source, head_id) is None:
            raise FileNotFoundError(f"Turn not found: {head_id}")
        forked = self.create(source.system_prompt, source.model)
        forked.metadata.parent_id = source.id
        forked.metadata.compaction = self._compaction_state_for_head(source, head_id)
        forked.metadata.pending_tool_calls = []
        forked.metadata.pending_plan_token = None
        forked.metadata.queued_messages = []
        branch_messages = self.branch_messages(source, head_id)
        forked.messages = [message.model_copy(deep=True) for message in branch_messages]
        return self._normalized_record(forked)

    def rewind(self, session_id: str, message_count: int) -> SessionRecord:
        source = self.load(session_id)
        branch_messages = self.branch_messages(source, source.active_head_id)
        if message_count < 0 or message_count > len(branch_messages):
            raise ValueError(f"message_count must be between 0 and {len(branch_messages)}")
        rewound = self.create(source.system_prompt, source.model)
        rewound.metadata.parent_id = source.id
        rewound.metadata.compaction = CompactionState()
        rewound.metadata.pending_tool_calls = []
        rewound.metadata.pending_plan_token = None
        rewound.metadata.queued_messages = []
        rewound.messages = [message.model_copy(deep=True) for message in branch_messages[:message_count]]
        return self._normalized_record(rewound)

    def rewind_turns(self, session_id: str, turn_count: int) -> SessionRecord:
        source = self.load(session_id)
        active_entries = [entry for entry in self.turn_entries(session_id, head_id=source.active_head_id) if entry.entry_type == "turn"]
        total_turns = len(active_entries)
        if turn_count < 0 or turn_count > total_turns:
            raise ValueError(f"turn_count must be between 0 and {total_turns}")
        if turn_count == total_turns:
            message_count = len(self.branch_messages(source, source.active_head_id))
        elif turn_count == 0:
            message_count = 0
        else:
            message_count = active_entries[turn_count - 1].total_message_count
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
        focus_turn_id = record.active_head_id
        turns = [entry.model_dump(mode="json") for entry in self.turn_entries(session_id, head_id=focus_turn_id)]
        turn_focus = self.describe_turn(session_id, focus_turn_id) if focus_turn_id else None
        return {
            "current": self._entry_for_record(record).model_dump(mode="json"),
            "parent": self._entry_for_record(parent).model_dump(mode="json") if parent is not None else None,
            "children": [self._entry_for_record(child).model_dump(mode="json") for child in sorted(children, key=lambda item: item.metadata.updated_at, reverse=True)],
            "turns": turns,
            "turn_focus": turn_focus,
        }

    def turn_entries(self, session_id: str, head_id: Optional[str] = None) -> list[SessionTurnEntry]:
        record = self.load(session_id)
        normalized = self._normalized_record(record)
        path = self.turn_path(normalized, head_id)
        entries: list[SessionTurnEntry] = []
        total_message_count = 0
        turn_number = 0
        for node in path:
            message_count = node.end_message_index - node.start_message_index if node.entry_type == "turn" else 0
            total_message_count += message_count
            if node.entry_type == "turn":
                turn_number += 1
            node_messages = normalized.messages[node.start_message_index:node.end_message_index] if node.entry_type == "turn" else []
            entries.append(
                SessionTurnEntry(
                    id=node.id,
                    parent_id=node.parent_id,
                    status=node.status,
                    created_at=node.created_at,
                    entry_type=node.entry_type,
                    turn_number=turn_number,
                    message_count=message_count,
                    total_message_count=total_message_count,
                    summarized_message_count=node.summarized_message_count,
                    user_preview=self._first_role_preview(node_messages, "user"),
                    assistant_preview=self._last_role_preview_from_messages(node_messages, "assistant"),
                    summary_preview=node.summary if node.entry_type == "compaction" else self._turn_summary_preview(node_messages),
                )
            )
        return entries

    def turn_tree(self, session_id: str) -> list[SessionTurnEntry]:
        record = self.load(session_id)
        normalized = self._normalized_record(record)
        return [self._turn_entry_for_node(normalized, node) for node in sorted(normalized.turn_nodes, key=lambda item: (item.created_at, item.id))]

    def describe_turn(self, session_id: str, turn_id: Optional[str]) -> Optional[dict[str, object]]:
        if not turn_id:
            return None
        record = self.load(session_id)
        normalized = self._normalized_record(record)
        current = self.turn_node(normalized, turn_id)
        if current is None:
            raise FileNotFoundError(f"Turn not found: {turn_id}")
        parent = self.turn_node(normalized, current.parent_id) if current.parent_id else None
        children = [node for node in normalized.turn_nodes if node.parent_id == current.id]
        return {
            "current": self._turn_entry_for_node(normalized, current).model_dump(mode="json"),
            "parent": self._turn_entry_for_node(normalized, parent).model_dump(mode="json") if parent is not None else None,
            "children": [self._turn_entry_for_node(normalized, child).model_dump(mode="json") for child in sorted(children, key=lambda item: item.created_at, reverse=True)],
        }

    def set_active_head(self, session_id: str, head_id: Optional[str]) -> SessionRecord:
        record = self.load(session_id)
        normalized = self._normalized_record(record)
        if head_id is not None and self.turn_node(normalized, head_id) is None:
            raise FileNotFoundError(f"Turn not found: {head_id}")
        normalized.metadata.active_head_id = head_id
        self.save(normalized)
        return normalized

    def branch_messages(self, record: SessionRecord, head_id: Optional[str] = None) -> list[ChatMessage]:
        normalized = self._normalized_record(record)
        path = self.turn_path(normalized, head_id)
        branch: list[ChatMessage] = []
        for node in path:
            if node.entry_type != "turn":
                continue
            branch.extend(message.model_copy(deep=True) for message in normalized.messages[node.start_message_index:node.end_message_index])
        return branch

    def turn_path(self, record: SessionRecord, head_id: Optional[str] = None) -> list[SessionTurnNode]:
        normalized = self._normalized_record(record)
        target_id = head_id if head_id is not None else normalized.active_head_id
        if not target_id:
            return []
        index = {node.id: node for node in normalized.turn_nodes}
        path: list[SessionTurnNode] = []
        current_id: Optional[str] = target_id
        while current_id:
            node = index.get(current_id)
            if node is None:
                break
            path.append(node)
            current_id = node.parent_id
        return list(reversed(path))

    def turn_node(self, record: SessionRecord, turn_id: Optional[str]) -> Optional[SessionTurnNode]:
        if turn_id is None:
            return None
        normalized = self._normalized_record(record)
        return next((node.model_copy(deep=True) for node in normalized.turn_nodes if node.id == turn_id), None)

    def sync_branch_state(
        self,
        record: SessionRecord,
        *,
        base_head_id: Optional[str],
        branch_messages: list[ChatMessage],
        pending_plan_token: Optional[str],
        pending_tool_calls: list[ToolCall],
    ) -> SessionRecord:
        normalized = self._normalized_record(record)
        base_messages = self.branch_messages(normalized, base_head_id) if base_head_id is not None else []
        if [message.model_dump(mode="json") for message in branch_messages[: len(base_messages)]] != [message.model_dump(mode="json") for message in base_messages]:
            raise ValueError("branch_messages do not match the selected active head")
        tail_messages = [message.model_copy(deep=True) for message in branch_messages[len(base_messages) :]]
        normalized.metadata.turn_nodes = [
            node.model_copy(deep=True)
            for node in normalized.turn_nodes
            if not (node.status == "draft" and self._is_descendant(normalized.turn_nodes, node.id, base_head_id))
        ]
        if not tail_messages:
            normalized.metadata.active_head_id = base_head_id
            return self._normalized_record(normalized)

        appended_start = len(normalized.messages)
        normalized.messages.extend(message.model_copy(deep=True) for message in tail_messages)
        segments = self._turn_segments(tail_messages)
        parent_id = base_head_id
        has_pending_tail = bool(pending_plan_token) or bool(pending_tool_calls)
        for index, (start, end) in enumerate(segments):
            parent_id = self._append_turn_node(
                normalized,
                parent_id=parent_id,
                start_message_index=appended_start + start,
                end_message_index=appended_start + end,
                status="draft" if has_pending_tail and index == len(segments) - 1 else "committed",
            )
        normalized.metadata.active_head_id = parent_id
        return self._normalized_record(normalized)

    def _prepare_record_for_save(self, record: SessionRecord) -> SessionRecord:
        target_compaction = record.metadata.compaction.model_copy(deep=True)
        normalized = self._normalized_record(record)
        covered_indices: set[int] = set()
        for node in normalized.turn_nodes:
            if node.entry_type != "turn":
                continue
            covered_indices.update(range(node.start_message_index, node.end_message_index))
        uncovered = [index for index in range(len(normalized.messages)) if index not in covered_indices]
        if uncovered:
            max_covered = max(covered_indices) if covered_indices else -1
            if uncovered == list(range(max_covered + 1, len(normalized.messages))):
                normalized = self.sync_branch_state(
                    normalized,
                    base_head_id=normalized.active_head_id,
                    branch_messages=normalized.messages,
                    pending_plan_token=normalized.pending_plan_token,
                    pending_tool_calls=normalized.pending_tool_calls,
                )
        normalized.metadata.compaction = target_compaction
        return self._sync_compaction_to_entries(normalized)

    def _entry_for_record(self, record: SessionRecord) -> SessionTreeEntry:
        normalized = self._normalized_record(record)
        branch_messages = self.branch_messages(normalized, normalized.active_head_id)
        active_path = self.turn_path(normalized, normalized.active_head_id)
        return SessionTreeEntry(
            id=normalized.id,
            parent_id=normalized.parent_id,
            updated_at=normalized.metadata.updated_at,
            model=normalized.model.model,
            message_count=len(branch_messages),
            turn_count=sum(1 for node in active_path if node.entry_type == "turn"),
            pending_plan_token=normalized.pending_plan_token,
            active_head_id=normalized.active_head_id,
            summary_preview=self._summary_preview(branch_messages, normalized.compaction.summary),
            last_user_preview=self._last_role_preview_from_messages(branch_messages, "user"),
            last_assistant_preview=self._last_role_preview_from_messages(branch_messages, "assistant"),
        )

    def _turn_entry_for_node(self, record: SessionRecord, node: SessionTurnNode) -> SessionTurnEntry:
        path = self.turn_path(record, node.id)
        turn_number = sum(1 for item in path if item.entry_type == "turn")
        total_message_count = sum(item.end_message_index - item.start_message_index for item in path if item.entry_type == "turn")
        node_messages = record.messages[node.start_message_index:node.end_message_index] if node.entry_type == "turn" else []
        return SessionTurnEntry(
            id=node.id,
            parent_id=node.parent_id,
            status=node.status,
            created_at=node.created_at,
            entry_type=node.entry_type,
            turn_number=turn_number,
            message_count=node.end_message_index - node.start_message_index if node.entry_type == "turn" else 0,
            total_message_count=total_message_count,
            summarized_message_count=node.summarized_message_count,
            user_preview=self._first_role_preview(node_messages, "user"),
            assistant_preview=self._last_role_preview_from_messages(node_messages, "assistant"),
            summary_preview=node.summary if node.entry_type == "compaction" else self._turn_summary_preview(node_messages),
        )

    def _normalized_record(self, record: SessionRecord) -> SessionRecord:
        normalized = record.model_copy(deep=True)
        if not normalized.turn_nodes and normalized.messages:
            parent_id: Optional[str] = None
            for start, end in self._turn_segments(normalized.messages):
                parent_id = self._append_turn_node(
                    normalized,
                    parent_id=parent_id,
                    start_message_index=start,
                    end_message_index=end,
                    status="committed",
                )
            normalized.metadata.active_head_id = parent_id
        elif normalized.turn_nodes and normalized.metadata.active_head_id is None:
            normalized.metadata.active_head_id = normalized.turn_nodes[-1].id
        if normalized.metadata.compaction.summary and normalized.turn_nodes and not any(node.entry_type == "compaction" for node in normalized.turn_nodes):
            normalized = self._append_compaction_node(normalized, normalized.metadata.compaction)
        if normalized.turn_nodes:
            normalized.metadata.compaction = self._compaction_state_for_head(normalized, normalized.metadata.active_head_id)
        if normalized.metadata.active_head_id and not any(node.id == normalized.metadata.active_head_id for node in normalized.turn_nodes):
            normalized.metadata.active_head_id = normalized.turn_nodes[-1].id if normalized.turn_nodes else None
        return normalized

    def _sync_compaction_to_entries(self, record: SessionRecord) -> SessionRecord:
        normalized = record.model_copy(deep=True)
        latest = self._compaction_node_for_head(normalized, normalized.active_head_id)
        target = normalized.metadata.compaction
        if not target.summary:
            normalized.metadata.compaction = self._compaction_state_for_head(normalized, normalized.active_head_id)
            return normalized
        if latest is not None and latest.summary == target.summary and latest.summarized_message_count == target.summarized_message_count:
            normalized.metadata.compaction = self._compaction_state_for_head(normalized, normalized.active_head_id)
            return normalized
        return self._append_compaction_node(normalized, target)

    def _append_compaction_node(self, record: SessionRecord, state: CompactionState) -> SessionRecord:
        normalized = record.model_copy(deep=True)
        node = SessionTurnNode(
            id=str(uuid.uuid4()),
            parent_id=normalized.metadata.active_head_id,
            created_at=time.time(),
            status="committed",
            entry_type="compaction",
            summary=state.summary,
            summarized_message_count=state.summarized_message_count,
        )
        normalized.metadata.turn_nodes.append(node)
        normalized.metadata.active_head_id = node.id
        normalized.metadata.compaction = CompactionState(summary=state.summary, summarized_message_count=state.summarized_message_count)
        return normalized

    def _compaction_node_for_head(self, record: SessionRecord, head_id: Optional[str]) -> Optional[SessionTurnNode]:
        index = {node.id: node for node in record.turn_nodes}
        current_id = head_id
        while current_id:
            node = index.get(current_id)
            if node is None:
                return None
            if node.entry_type == "compaction":
                return node
            current_id = node.parent_id
        return None

    def _compaction_state_for_head(self, record: SessionRecord, head_id: Optional[str]) -> CompactionState:
        node = self._compaction_node_for_head(record, head_id)
        if node is None:
            return CompactionState()
        return CompactionState(summary=node.summary, summarized_message_count=node.summarized_message_count)

    def _append_turn_node(
        self,
        record: SessionRecord,
        *,
        parent_id: Optional[str],
        start_message_index: int,
        end_message_index: int,
        status: str,
    ) -> str:
        node = SessionTurnNode(
            id=str(uuid.uuid4()),
            parent_id=parent_id,
            start_message_index=start_message_index,
            end_message_index=end_message_index,
            created_at=time.time(),
            status=status,
        )
        record.metadata.turn_nodes.append(node)
        return node.id

    @staticmethod
    def _turn_segments(messages: list[ChatMessage]) -> list[tuple[int, int]]:
        if not messages:
            return []
        starts = [index for index, message in enumerate(messages) if message.role == "user"]
        if not starts:
            return [(0, len(messages))]
        segments: list[tuple[int, int]] = []
        for offset, start in enumerate(starts):
            end = starts[offset + 1] if offset + 1 < len(starts) else len(messages)
            segments.append((start, end))
        return segments

    @staticmethod
    def _is_descendant(nodes: list[SessionTurnNode], node_id: str, ancestor_id: Optional[str]) -> bool:
        if ancestor_id is None:
            return True
        index = {node.id: node for node in nodes}
        current_id: Optional[str] = node_id
        while current_id:
            if current_id == ancestor_id:
                return True
            node = index.get(current_id)
            if node is None:
                return False
            current_id = node.parent_id
        return False

    @staticmethod
    def _first_role_preview(messages: list[ChatMessage], role: str, limit: int = 96) -> str:
        for message in messages:
            if message.role == role:
                return SessionStore._preview_text(SessionStore._message_text(message), limit=limit)
        return ""

    @staticmethod
    def _last_role_preview_from_messages(messages: list[ChatMessage], role: str, limit: int = 96) -> str:
        for message in reversed(messages):
            if message.role == role:
                return SessionStore._preview_text(SessionStore._message_text(message), limit=limit)
        return ""

    @staticmethod
    def _turn_summary_preview(messages: list[ChatMessage], limit: int = 96) -> str:
        if not messages:
            return ""
        assistant = SessionStore._last_role_preview_from_messages(messages, "assistant", limit=limit)
        if assistant:
            return assistant
        user = SessionStore._first_role_preview(messages, "user", limit=limit)
        if user:
            return user
        return SessionStore._preview_text(SessionStore._message_text(messages[-1]), limit=limit)

    @staticmethod
    def _summary_preview(messages: list[ChatMessage], compaction_summary: str, limit: int = 96) -> str:
        if compaction_summary:
            return SessionStore._preview_text(compaction_summary, limit=limit)
        if not messages:
            return ""
        return SessionStore._preview_text(SessionStore._message_text(messages[-1]), limit=limit)

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
            record = self._normalized_record(SessionRecord.model_validate(item["data"]))
            sessions[record.id] = record
        return sessions

    def _write_all_records(self, sessions: dict[str, SessionRecord]) -> None:
        ordered = sorted(sessions.values(), key=lambda item: (item.metadata.created_at, item.id))
        lines = [json.dumps({"type": "session", "data": self._normalized_record(record).model_dump(mode="json")}, ensure_ascii=False) for record in ordered]
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
                sessions[metadata.id] = self._normalized_record(SessionRecord(metadata=metadata, messages=messages))
        if sessions:
            self._write_all_records(sessions)



