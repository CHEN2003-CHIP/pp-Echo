from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, PrivateAttr

from pp_agent.domain import ChatMessage, CompactionState, QueuedMessage, TextPart, ToolCall
from pp_agent.storage.models import StoredModelConfig


SNAPSHOT_EVENT = "session_snapshot"
SESSION_MESSAGE_ID_KEY = "session_message_id"
SESSION_CORRELATION_KEY = "session_correlation"
SESSION_CORRELATION_VERSION = 1
SESSION_CORRELATION_MAX_TEXT = 512
SESSION_CORRELATION_MAX_ID = 160
SESSION_CORRELATION_DIGEST_ALGORITHM = "sha256"
_SAFE_CORRELATION_ID_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,160}$")


class SessionCorrelationKind:
    EXTERNAL_TOOL_RESULT = "external_tool_result"
    MODEL_CONTINUATION_COMPLETION = "model_continuation_completion"


class SessionEvidenceLookupStatus:
    FOUND = "found"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    SESSION_MISSING = "session_missing"
    SESSION_CORRUPT = "session_corrupt"
    IDENTITY_MISMATCH = "identity_mismatch"
    LEGACY_INSUFFICIENT = "legacy_insufficient"


class SessionEvidenceReference(BaseModel):
    session_id: str
    message_id: str
    turn_id: Optional[str] = None
    correlation_kind: str
    correlation_id: str
    action_id: Optional[str] = None
    result_digest: Optional[str] = None
    tool_name: Optional[str] = None
    completed_at: float


class SessionEvidenceLookupResult(BaseModel):
    status: str
    evidence: Optional[SessionEvidenceReference] = None
    reason: str = ""

#数据面
class SessionTurnNode(BaseModel):
    """
    【数据模型】会话回合节点（核心版本节点，类比Git提交）
    作用：记录会话的每一个版本/回合/压缩点，实现会话回溯、分支
    """
    id: str
    parent_id: Optional[str] = None
    start_message_index: int = 0
    end_message_index: int = 0
    created_at: float
    status: str = "committed"
    entry_type: Literal["turn", "compaction"] = "turn"
    summary: str = ""
    summarized_message_count: int = 0

#控制面
class SessionMetadata(BaseModel):
    """
    【数据模型】会话元数据
    作用：存储会话的核心配置、状态、版本链信息，不包含原始消息
    """
    id: str
    parent_id: Optional[str] = None
    created_at: float
    updated_at: float
    model: StoredModelConfig = Field(default_factory=StoredModelConfig)
    system_prompt: str
    compaction: CompactionState = Field(default_factory=CompactionState)
    pending_tool_calls: list[ToolCall] = Field(default_factory=list)
    pending_plan_token: Optional[str] = None
    queued_messages: list[QueuedMessage] = Field(default_factory=list)
    active_head_id: Optional[str] = None
    turn_nodes: list[SessionTurnNode] = Field(default_factory=list)

#数据内容+控制内容
class SessionRecord(BaseModel):
    """
    【数据模型】完整会话记录
    作用：元数据 + 原始聊天消息 = 一个完整可恢复的会话
    """
    metadata: SessionMetadata
    messages: list[ChatMessage] = Field(default_factory=list)
    _turn_index: dict[str, SessionTurnNode] = PrivateAttr(default_factory=dict)

    @property
    def id(self) -> str:
        return self.metadata.id

    @property
    def parent_id(self) -> Optional[str]:
        return self.metadata.parent_id

    @property
    def model(self) -> StoredModelConfig:
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
    """
    【数据模型】会话树列表条目
    作用：会话列表展示用，精简信息（预览文本、统计数据）
    """
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
    """
    【数据模型】回合详情条目
    作用：回合历史展示用，包含回合统计、消息预览
    """
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
    """
    【核心类】会话存储器
    作用：本地文件系统会话管理，负责创建/保存/加载/分支/回滚会话
    存储格式：每个会话一个 JSONL 事件文件，路径：<session-id>.jsonl
    核心特性：版本控制（类Git）、数据持久化、旧版本迁移
    """
    def __init__(self, root: Path) -> None:
        """
        初始化会话存储器
        参数：root - 存储根目录
        逻辑：创建目录、初始化文件、迁移旧会话
        """
        self.root = root.expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, system_prompt: str, model: StoredModelConfig) -> SessionRecord:
        """
        【公共方法】创建新会话
        参数：system_prompt - 系统提示词；model - 模型配置
        返回：全新的会话记录
        """
        now = time.time()
        return self._normalized_record(
            SessionRecord(
                metadata=SessionMetadata(
                    id=str(uuid.uuid4()),
                    created_at=now,
                    updated_at=now,
                    model=model.model_copy(deep=True),
                    system_prompt=system_prompt,
                ),
                messages=[],
            )
        )

    def save(self, record: SessionRecord) -> Path:
        """
        【公共方法】保存会话到文件
        参数：record - 会话记录
        返回：存储文件路径
        逻辑：预处理→更新时间→加载所有会话→追加保存→写入文件
        """
        record = self._prepare_record_for_save(record)
        record.metadata.updated_at = time.time()
        normalized = self._normalized_record(record)
        latest = self._load_current_record(normalized.id)
        path = self._session_path(normalized.id)
        self._append_events(path, self._build_append_events(latest, normalized))
        return path

    def load(self, session_id: str) -> SessionRecord:
        """加载会话：优先新文件 → 兼容旧文件 → 自动迁移"""
        path = self._session_path(session_id)
        if path.exists():
            return self._load_from_session_file(path)
        raise FileNotFoundError(f"Session not found: {session_id}")

    def list(self) -> list[SessionMetadata]:
        sessions = self._all_latest_records()
        return [
            record.metadata.model_copy(deep=True)
            for record in sorted(sessions.values(), key=lambda item: item.metadata.updated_at, reverse=True)
        ]

    def fork(self, session_id: str) -> SessionRecord:
        """
        从当前最新版本分支会话（Git 分支逻辑）
        :param session_id: 源会话ID
        :return: 新分支会话对象
        """
        source = self.load(session_id)
        return self.fork_from_head(session_id, source.active_head_id)

    def fork_from_head(self, session_id: str, head_id: Optional[str]) -> SessionRecord:
        """
        从指定版本节点分支会话
        :param session_id: 源会话ID
        :param head_id: 分支起点节点ID
        :return: 新分支会话对象
        :raises FileNotFoundError: 节点不存在时抛出
        """
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
        """
        按消息数量回滚会话
        :param session_id: 会话ID
        :param message_count: 保留的消息条数
        :return: 回滚后的新会话
        :raises ValueError: 回滚条数越界时抛出
        """
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
        """
        按回合数量回滚会话
        :param session_id: 会话ID
        :param turn_count: 保留的回合数
        :return: 回滚后的新会话
        :raises ValueError: 回合数越界时抛出
        """
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
        """
        获取会话树列表
        :return: 会话树结构列表
        """
        entries = [self._entry_for_record(record) for record in self._all_latest_records().values()]
        return sorted(entries, key=lambda item: (item.parent_id or "", item.updated_at, item.id))

    def children_of(self, session_id: str) -> list[SessionTreeEntry]:
        """
        获取指定会话的所有子会话（分支）
        :param session_id: 父会话ID
        :return: 子会话列表
        """
        return [entry for entry in self.tree() if entry.parent_id == session_id]

    def describe(self, session_id: str) -> dict[str, object]:
        """
        获取会话完整详情（当前+父+子+回合链+焦点节点）
        :param session_id: 会话ID
        :return: 会话详情字典
        :raises FileNotFoundError: 会话不存在时抛出
        """
        sessions = self._all_latest_records()
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
        """
        获取会话回合历史链
        :param session_id: 会话ID
        :param head_id: 终点节点ID
        :return: 回合详情列表
        """
        record = self.load(session_id)
        path = self.turn_path(record, head_id)
        entries: list[SessionTurnEntry] = []
        total_message_count = 0
        turn_number = 0
        for node in path:
            message_count = node.end_message_index - node.start_message_index if node.entry_type == "turn" else 0
            total_message_count += message_count
            if node.entry_type == "turn":
                turn_number += 1
            node_messages = record.messages[node.start_message_index:node.end_message_index] if node.entry_type == "turn" else []
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
        """
        获取会话完整回合树（所有版本节点）
        :param session_id: 会话ID
        :return: 所有回合节点列表
        """
        record = self.load(session_id)
        return [self._turn_entry_for_node(record, node) for node in sorted(record.turn_nodes, key=lambda item: (item.created_at, item.id))]

    def describe_turn(self, session_id: str, turn_id: Optional[str]) -> Optional[dict[str, object]]:
        """
        获取单个回合详情
        :param session_id: 会话ID
        :param turn_id: 回合节点ID
        :return: 回合详情字典
        :raises FileNotFoundError: 回合不存在时抛出
        """
        if not turn_id:
            return None
        record = self.load(session_id)
        current = self.turn_node(record, turn_id)
        if current is None:
            raise FileNotFoundError(f"Turn not found: {turn_id}")
        parent = self.turn_node(record, current.parent_id) if current.parent_id else None
        children = [node for node in record.turn_nodes if node.parent_id == current.id]
        return {
            "current": self._turn_entry_for_node(record, current).model_dump(mode="json"),
            "parent": self._turn_entry_for_node(record, parent).model_dump(mode="json") if parent is not None else None,
            "children": [self._turn_entry_for_node(record, child).model_dump(mode="json") for child in sorted(children, key=lambda item: item.created_at, reverse=True)],
        }

    def lookup_external_tool_result_evidence(
        self,
        session_id: str,
        *,
        action_id: str,
        result_digest: str | None = None,
    ) -> SessionEvidenceLookupResult:
        action_id = _validate_correlation_id(action_id, field="action_id")
        if result_digest is not None:
            result_digest = _validate_result_digest(result_digest)
        return self._lookup_correlation_evidence(
            session_id,
            kind=SessionCorrelationKind.EXTERNAL_TOOL_RESULT,
            matcher=lambda payload: payload.get("action_id") == action_id
            and (result_digest is None or payload.get("result_digest") == result_digest),
            mismatch_detector=lambda payload: payload.get("action_id") == action_id
            and result_digest is not None
            and payload.get("result_digest") != result_digest,
        )

    def lookup_model_continuation_completion_evidence(
        self,
        session_id: str,
        *,
        continuation_id: str,
    ) -> SessionEvidenceLookupResult:
        continuation_id = _validate_correlation_id(continuation_id, field="continuation_id")
        return self._lookup_correlation_evidence(
            session_id,
            kind=SessionCorrelationKind.MODEL_CONTINUATION_COMPLETION,
            matcher=lambda payload: payload.get("continuation_id") == continuation_id,
            mismatch_detector=lambda _payload: False,
        )

    def set_active_head(self, session_id: str, head_id: Optional[str]) -> SessionRecord:
        """
        切换当前活跃版本节点（Git checkout 功能）
        :param session_id: 会话ID
        :param head_id: 目标节点ID
        :return: 更新后的会话对象
        :raises FileNotFoundError: 节点不存在时抛出
        """
        record = self.load(session_id)
        if head_id is not None and self.turn_node(record, head_id) is None:
            raise FileNotFoundError(f"Turn not found: {head_id}")
        record.metadata.active_head_id = head_id
        self.save(record)
        return self._normalized_record(record)

    def branch_messages(self, record: SessionRecord, head_id: Optional[str] = None) -> list[ChatMessage]:
        """
        获取指定版本节点的完整消息链
        :param record: 会话对象
        :param head_id: 版本节点ID
        :return: 消息列表
        """
        path = self.turn_path(record, head_id)
        branch: list[ChatMessage] = []
        for node in path:
            if node.entry_type != "turn":
                continue
            branch.extend(message.model_copy(deep=True) for message in record.messages[node.start_message_index:node.end_message_index])
        return branch

    def _lookup_correlation_evidence(
        self,
        session_id: str,
        *,
        kind: str,
        matcher,
        mismatch_detector,
    ) -> SessionEvidenceLookupResult:
        try:
            record = self.load(session_id)
        except FileNotFoundError:
            return SessionEvidenceLookupResult(status=SessionEvidenceLookupStatus.SESSION_MISSING, reason="session_missing")
        except (ValueError, TypeError) as exc:
            return SessionEvidenceLookupResult(status=SessionEvidenceLookupStatus.SESSION_CORRUPT, reason=str(exc))

        saw_kind = False
        saw_invalid = False
        saw_legacy_role = False
        saw_mismatch = False
        matches: list[SessionEvidenceReference] = []
        for message in record.messages:
            metadata = message.metadata if isinstance(message.metadata, dict) else {}
            if not metadata.get(SESSION_MESSAGE_ID_KEY):
                if message.role in {"assistant", "tool"}:
                    saw_legacy_role = True
                continue
            correlation = metadata.get(SESSION_CORRELATION_KEY)
            if not isinstance(correlation, dict):
                continue
            if correlation.get("kind") != kind:
                continue
            saw_kind = True
            if mismatch_detector(correlation):
                saw_mismatch = True
            if not matcher(correlation):
                continue
            evidence = self._evidence_reference_from_message(record, message, correlation)
            if evidence is None:
                saw_invalid = True
                continue
            matches.append(evidence)

        if len(matches) == 1:
            return SessionEvidenceLookupResult(status=SessionEvidenceLookupStatus.FOUND, evidence=matches[0])
        if len(matches) > 1:
            return SessionEvidenceLookupResult(status=SessionEvidenceLookupStatus.AMBIGUOUS, reason="multiple_matching_evidence_records")
        if saw_invalid:
            return SessionEvidenceLookupResult(status=SessionEvidenceLookupStatus.IDENTITY_MISMATCH, reason="invalid_matching_correlation_metadata")
        if saw_mismatch:
            return SessionEvidenceLookupResult(status=SessionEvidenceLookupStatus.IDENTITY_MISMATCH, reason="correlation_identity_mismatch")
        if saw_legacy_role and not saw_kind:
            return SessionEvidenceLookupResult(status=SessionEvidenceLookupStatus.LEGACY_INSUFFICIENT, reason="legacy_messages_without_correlation_metadata")
        return SessionEvidenceLookupResult(status=SessionEvidenceLookupStatus.NOT_FOUND, reason="no_matching_correlation_evidence")

    @staticmethod
    def _evidence_reference_from_message(
        record: SessionRecord,
        message: ChatMessage,
        correlation: dict[str, Any],
    ) -> SessionEvidenceReference | None:
        try:
            message_id = _validate_correlation_id(str(message.metadata.get(SESSION_MESSAGE_ID_KEY) or ""), field="message_id")
            kind = str(correlation.get("kind") or "")
            correlation_id = str(correlation.get("correlation_id") or correlation.get("continuation_id") or correlation.get("action_id") or "")
            correlation_id = _validate_correlation_id(correlation_id, field="correlation_id")
            completed_at = float(correlation.get("completed_at"))
        except (TypeError, ValueError):
            return None
        if kind not in {SessionCorrelationKind.EXTERNAL_TOOL_RESULT, SessionCorrelationKind.MODEL_CONTINUATION_COMPLETION}:
            return None
        turn_id = str(correlation.get("turn_id") or record.active_head_id or "").strip() or None
        action_id = correlation.get("action_id")
        result_digest = correlation.get("result_digest")
        tool_name = correlation.get("tool_name")
        return SessionEvidenceReference(
            session_id=record.id,
            message_id=message_id,
            turn_id=turn_id,
            correlation_kind=kind,
            correlation_id=correlation_id,
            action_id=str(action_id) if action_id else None,
            result_digest=str(result_digest) if result_digest else None,
            tool_name=str(tool_name)[:SESSION_CORRELATION_MAX_ID] if tool_name else None,
            completed_at=completed_at,
        )

    def turn_path(self, record: SessionRecord, head_id: Optional[str] = None) -> list[SessionTurnNode]:
        """
        获取从根节点到目标节点的完整版本链
        :param record: 会话对象
        :param head_id: 目标节点ID
        :return: 正序排列的节点链
        """
        normalized = self._normalized_record(record)
        target_id = head_id if head_id is not None else normalized.active_head_id
        if not target_id:
            return []
        path: list[SessionTurnNode] = []
        current_id: Optional[str] = target_id
        while current_id:
            node = normalized._turn_index.get(current_id)
            if node is None:
                break
            path.append(node.model_copy(deep=True))
            current_id = node.parent_id
        return list(reversed(path))

    def turn_node(self, record: SessionRecord, turn_id: Optional[str]) -> Optional[SessionTurnNode]:
        """
        根据节点ID快速查询节点（索引O(1)查询）
        :param record: 会话对象
        :param turn_id: 节点ID
        :return: 节点对象 / None
        """
        if turn_id is None:
            return None
        normalized = self._normalized_record(record)
        node = normalized._turn_index.get(turn_id)
        return node.model_copy(deep=True) if node is not None else None

    def sync_branch_state(
        self,
        record: SessionRecord,
        *,
        base_head_id: Optional[str],
        branch_messages: list[ChatMessage],
        pending_plan_token: Optional[str],
        pending_tool_calls: list[ToolCall],
    ) -> SessionRecord:
        """
        【核心方法】同步会话分支状态（Git式版本合并）
        【业务功能】基于基准节点，合并新消息、清理草稿节点、生成新版本节点链
        【设计模式】版本控制 + 状态机管理
        :param record: 原始会话对象
        :param base_head_id: 基准版本节点ID（合并起点）
        :param branch_messages: 期望同步后的完整消息列表
        :param pending_plan_token: 待执行计划令牌
        :param pending_tool_calls: 待执行工具调用列表
        :return: 同步并标准化后的会话对象
        :raises ValueError: 传入消息与基准节点不匹配时抛出
        """
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
        self._refresh_turn_index(normalized)
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

    def best_base_head_id(self, record: SessionRecord, branch_messages: list[ChatMessage]) -> Optional[str]:
        """
        【智能匹配】自动寻找最佳基准节点
        【业务功能】根据传入消息，寻找最长匹配的历史节点（用于异常恢复/自动对齐）
        :param record: 会话对象
        :param branch_messages: 待匹配消息列表
        :return: 最佳匹配节点ID，无匹配则返回None
        """
        normalized = self._normalized_record(record)
        if not branch_messages or not normalized.turn_nodes:
            return None

        target_dump = [message.model_dump(mode="json") for message in branch_messages]
        best_head_id: Optional[str] = None
        best_length = 0
        for node in normalized.turn_nodes:
            candidate = self.branch_messages(normalized, node.id)
            if not candidate or len(candidate) > len(branch_messages):
                continue
            candidate_dump = [message.model_dump(mode="json") for message in candidate]
            if target_dump[: len(candidate_dump)] != candidate_dump:
                continue
            if len(candidate_dump) > best_length:
                best_length = len(candidate_dump)
                best_head_id = node.id
        return best_head_id

    def _prepare_record_for_save(self, record: SessionRecord) -> SessionRecord:
        """
        【前置处理】保存会话前的数据校验与自动修复
        【业务功能】确保消息与节点索引一致，自动补全缺失的回合节点
        :param record: 待保存会话
        :return: 校验修复后的会话
        """
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
        """
        【视图转换】将会话记录转为列表展示对象
        【业务功能】用于会话列表页，提供精简信息、消息预览、统计数据
        :param record: 原始会话
        :return: 会话列表展示项
        """
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
        """
        【视图转换】将回合节点转为前端展示对象
        【业务功能】用于对话历史页，展示单轮对话信息
        :param record: 会话对象
        :param node: 回合节点
        :return: 回合展示项
        """
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
        """
        【标准化核心】会话状态标准化（必须调用）
        【业务功能】自动补全节点、修复索引、保证状态一致性
        【保障】任何修改后必须执行标准化
        :param record: 原始会话
        :return: 一致性保证的标准会话
        """
        normalized = record.model_copy(deep=True)
        #如果还没有 turn 节点，但已经有消息，就按消息自动切段补 turn 节点。
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
        #如果已有节点但没 active head，就默认把最后一个节点当 active head。
        elif normalized.turn_nodes and normalized.metadata.active_head_id is None:
            normalized.metadata.active_head_id = normalized.turn_nodes[-1].id
        #如果 metadata.compaction.summary 有内容，但 turn 树里还没有任何 compaction 节点
        if normalized.metadata.compaction.summary and normalized.turn_nodes and not any(node.entry_type == "compaction" for node in normalized.turn_nodes):
            normalized = self._append_compaction_node(normalized, normalized.metadata.compaction)
        if normalized.turn_nodes:
            normalized.metadata.compaction = self._compaction_state_for_head(normalized, normalized.metadata.active_head_id)
        if normalized.metadata.active_head_id and normalized.metadata.active_head_id not in {node.id for node in normalized.turn_nodes}:
            #如果 active_head_id 指向了一个不存在的节点，则回退到最后一个节点。
            normalized.metadata.active_head_id = normalized.turn_nodes[-1].id if normalized.turn_nodes else None
        self._refresh_turn_index(normalized)
        return normalized

    def _sync_compaction_to_entries(self, record: SessionRecord) -> SessionRecord:
        """
        【状态同步】同步上下文压缩状态到节点链
        【业务功能】确保压缩状态与最新节点一致
        """
        normalized = self._normalized_record(record)
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
        """
        【节点创建】追加上下文压缩节点
        【业务功能】长对话优化，将历史消息转为摘要，减少token消耗
        :param record: 会话
        :param state: 压缩状态（摘要+数量）
        :return: 更新后的会话
        """
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
        self._refresh_turn_index(normalized)
        return normalized

    def _compaction_node_for_head(self, record: SessionRecord, head_id: Optional[str]) -> Optional[SessionTurnNode]:
        """
        【节点查询】向上查找最新压缩节点
        """
        normalized = record.model_copy(deep=True)
        if len(normalized._turn_index) != len(normalized.turn_nodes):
            self._refresh_turn_index(normalized)
        current_id = head_id
        while current_id:
            node = normalized._turn_index.get(current_id)
            if node is None:
                return None
            if node.entry_type == "compaction":
                return node.model_copy(deep=True)
            current_id = node.parent_id
        return None

    def _compaction_state_for_head(self, record: SessionRecord, head_id: Optional[str]) -> CompactionState:
        """
        【状态查询】获取节点对应的压缩状态
        """
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
        """
        【节点创建】追加一个对话回合节点
        :return: 新节点ID
        """
        node = SessionTurnNode(
            id=str(uuid.uuid4()),
            parent_id=parent_id,
            start_message_index=start_message_index,
            end_message_index=end_message_index,
            created_at=time.time(),
            status=status,
        )
        record.metadata.turn_nodes.append(node)
        record._turn_index[node.id] = node
        return node.id

    @staticmethod
    def _turn_segments(messages: list[ChatMessage]) -> list[tuple[int, int]]:
        """
        【消息分片】按用户输入切分回合片段
        规则：以user消息为起点，划分一轮对话
        """
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
        """获取第一条指定角色的消息预览"""
        for message in messages:
            if message.role == role:
                return SessionStore._preview_text(SessionStore._message_text(message), limit=limit)
        return ""

    @staticmethod
    def _last_role_preview_from_messages(messages: list[ChatMessage], role: str, limit: int = 96) -> str:
        """获取最后一条指定角色的消息预览（倒序查找）"""
        for message in reversed(messages):
            if message.role == role:
                return SessionStore._preview_text(SessionStore._message_text(message), limit=limit)
        return ""

    @staticmethod
    def _turn_summary_preview(messages: list[ChatMessage], limit: int = 96) -> str:
        """单轮对话预览：优先助手，其次用户"""
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
        """会话预览：优先压缩摘要，其次最后一条消息"""
        if compaction_summary:
            return SessionStore._preview_text(compaction_summary, limit=limit)
        if not messages:
            return ""
        return SessionStore._preview_text(SessionStore._message_text(messages[-1]), limit=limit)

    @staticmethod
    def _message_text(message: ChatMessage) -> str:
        """提取消息中的纯文本内容（过滤非文本块）"""
        parts: list[str] = []
        for part in message.content:
            if isinstance(part, TextPart):
                parts.append(part.text)
        return " ".join(item.strip() for item in parts if item.strip())

    @staticmethod
    def _preview_text(value: str, limit: int = 96) -> str:
        """文本预览格式化：清理换行 + 长度限制 + 省略号"""
        clean = " ".join(value.replace("\r", " ").replace("\n", " ").split())
        if len(clean) <= limit:
            return clean
        return clean[: limit - 3] + "..."

    def _session_path(self, session_id: str) -> Path:
        """会话文件路径规则：{session_id}.jsonl"""
        return self.root / f"{session_id}.jsonl"

    def _session_files(self) -> list[Path]:
        """获取所有会话文件（排除旧版文件）"""
        return sorted(path for path in self.root.glob("*.jsonl"))

    def _load_current_record(self, session_id: str) -> Optional[SessionRecord]:
        """加载当前最新会话（兼容新旧存储）"""
        path = self._session_path(session_id)
        if path.exists():
            return self._load_from_session_file(path)
        return None

    def _load_from_session_file(self, path: Path) -> SessionRecord:
        """
        从事件文件加载会话：只读取最后一次快照
        【事件溯源】通过回放快照恢复最新状态
        """
        latest_snapshot: Optional[SessionRecord] = None
        for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw.strip():
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError as exc:
                session_id = path.stem
                raise ValueError(f"Invalid JSONL entry for session {session_id} at line {line_no}: {exc}") from exc
            if item.get("type") != SNAPSHOT_EVENT:
                continue
            latest_snapshot = SessionRecord.model_validate(item["data"])
        if latest_snapshot is None:
            raise ValueError(f"No {SNAPSHOT_EVENT!r} entry found for session {path.stem}")
        return self._normalized_record(latest_snapshot)

    def _append_events(self, path: Path, events: list[dict[str, Any]]) -> None:
        """追加写入事件（原子写入，保证并发安全）"""
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _build_append_events(self, previous: Optional[SessionRecord], current: SessionRecord) -> list[dict[str, Any]]:
        """
        【事件构建】生成增量变更事件（事件溯源核心）
        对比新旧状态，只生成变化的事件
        """
        previous = self._normalized_record(previous) if previous is not None else None
        current = self._normalized_record(current)
        events: list[dict[str, Any]] = []
        now = current.metadata.updated_at

        if previous is None:
            events.append(
                {
                    "type": "metadata_created",
                    "session_id": current.id,
                    "at": now,
                    "data": {
                        "id": current.id,
                        "parent_id": current.parent_id,
                        "created_at": current.metadata.created_at,
                        "system_prompt": current.system_prompt,
                        "model": current.model.model_dump(mode="json"),
                    },
                }
            )
        elif self._metadata_changed(previous, current):
            events.append(
                {
                    "type": "metadata_updated",
                    "session_id": current.id,
                    "at": now,
                    "data": {
                        "parent_id": current.parent_id,
                        "system_prompt": current.system_prompt,
                        "model": current.model.model_dump(mode="json"),
                    },
                }
            )

        message_event = self._messages_event(previous, current, now)
        if message_event is not None:
            events.append(message_event)

        events.extend(self._turn_node_events(previous, current, now))

        if previous is None or previous.active_head_id != current.active_head_id:
            events.append({"type": "head_updated", "session_id": current.id, "at": now, "data": {"active_head_id": current.active_head_id}})

        if previous is None or previous.compaction.model_dump(mode="json") != current.compaction.model_dump(mode="json"):
            events.append({"type": "compaction_recorded", "session_id": current.id, "at": now, "data": current.compaction.model_dump(mode="json")})

        if previous is None or self._pending_state_dump(previous) != self._pending_state_dump(current):
            events.append({"type": "pending_state_updated", "session_id": current.id, "at": now, "data": self._pending_state_dump(current)})

        events.append({"type": SNAPSHOT_EVENT, "session_id": current.id, "at": now, "data": current.model_dump(mode="json")})
        return events

    @staticmethod
    def _metadata_changed(previous: SessionRecord, current: SessionRecord) -> bool:
        """元数据是否变更"""
        return (
            previous.parent_id != current.parent_id
            or previous.system_prompt != current.system_prompt
            or previous.model.model_dump(mode="json") != current.model.model_dump(mode="json")
        )

    def _messages_event(self, previous: Optional[SessionRecord], current: SessionRecord, now: float) -> Optional[dict[str, Any]]:
        """生成消息增量事件"""
        if previous is None:
            if not current.messages:
                return None
            appended = [message.model_dump(mode="json") for message in current.messages]
            return {"type": "messages_appended", "session_id": current.id, "at": now, "data": {"count": len(appended), "messages": appended}}

        previous_dump = [message.model_dump(mode="json") for message in previous.messages]
        current_dump = [message.model_dump(mode="json") for message in current.messages]
        if current_dump[: len(previous_dump)] == previous_dump and len(current_dump) > len(previous_dump):
            appended = current_dump[len(previous_dump) :]
            return {"type": "messages_appended", "session_id": current.id, "at": now, "data": {"count": len(appended), "messages": appended}}
        if previous_dump != current_dump:
            return {"type": "messages_replaced", "session_id": current.id, "at": now, "data": {"count": len(current_dump)}}
        return None

    def _turn_node_events(self, previous: Optional[SessionRecord], current: SessionRecord, now: float) -> list[dict[str, Any]]:
        """生成回合节点增量事件"""
        if previous is None:
            return [{"type": "turn_node_added", "session_id": current.id, "at": now, "data": node.model_dump(mode="json")} for node in current.turn_nodes]

        previous_dump = [node.model_dump(mode="json") for node in previous.turn_nodes]
        current_dump = [node.model_dump(mode="json") for node in current.turn_nodes]
        if current_dump[: len(previous_dump)] == previous_dump and len(current_dump) > len(previous_dump):
            return [{"type": "turn_node_added", "session_id": current.id, "at": now, "data": node.model_dump(mode="json")} for node in current.turn_nodes[len(previous.turn_nodes) :]]
        if previous_dump != current_dump:
            return [{"type": "turn_nodes_replaced", "session_id": current.id, "at": now, "data": {"count": len(current_dump)}}]
        return []

    @staticmethod
    def _pending_state_dump(record: SessionRecord) -> dict[str, Any]:
        """待执行状态序列化"""
        return {
            "pending_plan_token": record.pending_plan_token,
            "pending_tool_calls": [call.model_dump(mode="json") for call in record.pending_tool_calls],
            "queued_messages": [message.model_dump(mode="json") for message in record.queued_messages],
        }

    def _all_latest_records(self) -> dict[str, SessionRecord]:
        """加载所有会话最新状态"""
        sessions: dict[str, SessionRecord] = {}
        for path in self._session_files():
            try:
                record = self._load_from_session_file(path)
            except ValueError:
                continue
            sessions[record.id] = record
        return sessions

    @staticmethod
    def _refresh_turn_index(record: SessionRecord) -> None:
        record._turn_index = {node.id: node for node in record.turn_nodes}


def ensure_session_message_id(message: ChatMessage) -> str:
    metadata = message.metadata if isinstance(message.metadata, dict) else {}
    existing = metadata.get(SESSION_MESSAGE_ID_KEY)
    if isinstance(existing, str) and _SAFE_CORRELATION_ID_RE.match(existing):
        return existing
    message_id = f"msg-{uuid.uuid4().hex}"
    metadata[SESSION_MESSAGE_ID_KEY] = message_id
    message.metadata = metadata
    return message_id


def build_external_tool_result_correlation(
    *,
    action_id: str,
    result_digest: str,
    tool_name: str | None,
    completed_at: float,
    turn_id: str | int | None = None,
) -> dict[str, Any]:
    action_id = _validate_correlation_id(action_id, field="action_id")
    result_digest = _validate_result_digest(result_digest)
    payload: dict[str, Any] = {
        "version": SESSION_CORRELATION_VERSION,
        "kind": SessionCorrelationKind.EXTERNAL_TOOL_RESULT,
        "correlation_id": action_id,
        "action_id": action_id,
        "result_digest": result_digest,
        "completed_at": float(completed_at),
    }
    if tool_name:
        payload["tool_name"] = _bounded_text(tool_name, limit=SESSION_CORRELATION_MAX_ID)
    if turn_id is not None:
        payload["turn_id"] = _bounded_text(str(turn_id), limit=SESSION_CORRELATION_MAX_ID)
    return payload


def build_model_continuation_completion_correlation(
    *,
    continuation_id: str,
    completed_at: float,
    source_action_id: str | None = None,
    source_result_digest: str | None = None,
    turn_id: str | int | None = None,
) -> dict[str, Any]:
    continuation_id = _validate_correlation_id(continuation_id, field="continuation_id")
    payload: dict[str, Any] = {
        "version": SESSION_CORRELATION_VERSION,
        "kind": SessionCorrelationKind.MODEL_CONTINUATION_COMPLETION,
        "correlation_id": continuation_id,
        "continuation_id": continuation_id,
        "completed_at": float(completed_at),
    }
    if source_action_id is not None:
        payload["source_action_id"] = _validate_correlation_id(source_action_id, field="source_action_id")
    if source_result_digest is not None:
        payload["source_result_digest"] = _validate_result_digest(source_result_digest)
    if turn_id is not None:
        payload["turn_id"] = _bounded_text(str(turn_id), limit=SESSION_CORRELATION_MAX_ID)
    return payload


def build_session_result_digest(value: object) -> str:
    canonical = _canonical_bounded_value(value)
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{SESSION_CORRELATION_DIGEST_ALGORITHM}:{hashlib.sha256(raw).hexdigest()}"


def _canonical_bounded_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _bounded_text(value)
    if isinstance(value, list):
        return [_canonical_bounded_value(item) for item in value[:20]]
    if isinstance(value, tuple):
        return [_canonical_bounded_value(item) for item in value[:20]]
    if isinstance(value, dict):
        blocked = {"token", "approval_token", "raw_approval_token", "secret", "api_key", "authorization"}
        result: dict[str, object] = {}
        for key in sorted(value):
            key_text = str(key)
            if key_text.lower() in blocked:
                continue
            result[_bounded_text(key_text, limit=SESSION_CORRELATION_MAX_ID)] = _canonical_bounded_value(value[key])
            if len(result) >= 40:
                break
        return result
    return _bounded_text(str(value))


def _bounded_text(value: str, *, limit: int = SESSION_CORRELATION_MAX_TEXT) -> str:
    clean = " ".join(str(value).replace("\r", " ").replace("\n", " ").split())
    return clean[:limit]


def _validate_correlation_id(value: str, *, field: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_CORRELATION_ID_RE.match(text):
        raise ValueError(f"Invalid {field}")
    return text


def _validate_result_digest(value: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", text):
        raise ValueError("Invalid result_digest")
    return text


__all__ = [
    "SESSION_CORRELATION_KEY",
    "SESSION_MESSAGE_ID_KEY",
    "SessionCorrelationKind",
    "SessionEvidenceLookupResult",
    "SessionEvidenceLookupStatus",
    "SessionEvidenceReference",
    "SessionMetadata",
    "SessionRecord",
    "SessionStore",
    "SessionTreeEntry",
    "SessionTurnEntry",
    "SessionTurnNode",
    "build_external_tool_result_correlation",
    "build_model_continuation_completion_correlation",
    "build_session_result_digest",
    "ensure_session_message_id",
]
