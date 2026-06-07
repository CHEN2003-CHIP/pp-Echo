from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

TraceStatus = Literal["running", "ok", "error", "blocked", "pending", "cancelled"]
SpanType = Literal[
    "run",
    "turn",
    "context",
    "llm",
    "tool",
    "policy",
    "approval",
    "memory",
    "checkpoint",
    "subagent",
    "eval",
    "system",
]


class TraceRun(BaseModel):
    """
    表示一次完整 Agent 执行的审计入口。

    TraceRun 是 Trace 文件里的顶层运行记录，用于把一次用户 prompt、continue
    或审批恢复流程关联到同一个 run_id。它只保存可展示、可索引的摘要信息，
    不保存完整 prompt、隐藏推理链、密钥或环境变量内容。

    字段语义：
    - run_id 是全局唯一运行标识，也是 JSONL 文件名的一部分。
    - session_id / turn_id 关联 pp-Echo 既有会话与轮次。
    - workspace 用于标记运行发生的工作区。
    - user_goal_preview 是脱敏和截断后的用户目标预览。
    - status / started_at / ended_at / duration_ms 描述运行生命周期。
    - provider / model 用于后续按模型供应商筛选和统计。
    - attributes 保存兼容未来扩展的结构化元数据。
    """

    schema_version: str = "1.0"
    run_id: str
    session_id: Optional[str] = None
    turn_id: Optional[Union[str, int]] = None
    workspace: str
    user_goal_preview: str = ""
    status: TraceStatus = "running"
    started_at: float
    ended_at: Optional[float] = None
    duration_ms: Optional[int] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)


class TraceSpan(BaseModel):
    """
    表示一次 Agent 运行中的一个可审计步骤。

    TraceSpan 是 TraceInspect 渲染时间线的核心数据结构。它通常对应一个有
    明确开始和结束的动作，例如上下文构建、一次 LLM 调用、一次工具调用、
    一次审批决策、一次 memory 召回或一次 checkpoint 操作。

    字段设计目标：
    - run_id 用于把 span 归属到一次完整 Agent 运行。
    - span_id / parent_span_id 用于构建父子调用树。
    - span_type 用于前端分组展示，例如 llm/tool/approval/memory。
    - input/output 只保存脱敏后的摘要，不保存 API key、私钥或隐藏推理链。
    - attributes 保存可筛选、可统计的结构化元数据。
    - error_kind / error_message 保存可审计错误，而不会吞掉业务异常。
    """

    schema_version: str = "1.0"
    run_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    session_id: Optional[str] = None
    turn_id: Optional[Union[str, int]] = None
    name: str
    span_type: SpanType
    status: TraceStatus = "running"
    started_at: float
    ended_at: Optional[float] = None
    duration_ms: Optional[int] = None
    input: Dict[str, Any] = Field(default_factory=dict)
    output: Dict[str, Any] = Field(default_factory=dict)
    attributes: Dict[str, Any] = Field(default_factory=dict)
    error_kind: Optional[str] = None
    error_message: Optional[str] = None
    redaction_applied: bool = False


class TraceEvent(BaseModel):
    """
    表示没有持续时间、但需要审计留痕的运行事件。

    TraceEvent 用于记录生命周期状态变化、审批状态、策略决策、原始 runtime
    event 摘要等瞬时信息。它与 TraceSpan 的区别是没有开始/结束边界，适合
    保存运行过程中的补充证据。
    """

    schema_version: str = "1.0"
    run_id: str
    event_id: str
    name: str
    timestamp: float
    session_id: Optional[str] = None
    turn_id: Optional[Union[str, int]] = None
    span_id: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)
    payload: Dict[str, Any] = Field(default_factory=dict)
    redaction_applied: bool = False


class TraceArtifact(BaseModel):
    """
    表示 Trace 关联的外部产物摘要。

    TraceArtifact 不直接嵌入大文件内容，只记录 artifact_token、路径、摘要和
    类型信息，供 TraceInspect 展示 changed files、patch artifact 或其它可回放
    线索。这样可以避免 trace 文件无限膨胀。
    """

    schema_version: str = "1.0"
    run_id: str
    artifact_id: str
    artifact_type: str
    path: Optional[str] = None
    token: Optional[str] = None
    preview: str = ""
    attributes: Dict[str, Any] = Field(default_factory=dict)


class TraceRunSummary(BaseModel):
    """
    Trace 列表页使用的运行摘要。

    TraceRunSummary 来源于 TraceDetail 聚合或运行结束时的 index 记录。它用于
    快速展示最近运行、风险等级、调用次数和诊断概况，不要求读取完整 trace
    文件即可完成列表渲染。
    """

    schema_version: str = "1.0"
    run_id: str
    session_id: Optional[str] = None
    turn_id: Optional[Union[str, int]] = None
    workspace: str = ""
    user_goal_preview: str = ""
    status: TraceStatus = "running"
    started_at: float = 0.0
    ended_at: Optional[float] = None
    duration_ms: Optional[int] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    llm_calls: int = 0
    tool_calls: int = 0
    approval_count: int = 0
    memory_recall_count: int = 0
    checkpoint_count: int = 0
    subagent_count: int = 0
    error_count: int = 0
    blocked_count: int = 0
    pending_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    risk_level: Literal["low", "medium", "high"] = "low"
    changed_path_count: int = 0
    attributes: Dict[str, Any] = Field(default_factory=dict)


class TraceDiagnosis(BaseModel):
    """
    Trace 自动诊断结果。

    TraceDiagnosis 是面向用户的解释层，用来把错误 span、等待审批、digest
    mismatch、上下文膨胀等结构化迹象转换成可读提示。诊断仅基于 trace 数据
    做启发式判断，不替代真实业务状态。
    """

    code: str
    severity: Literal["info", "warning", "error"]
    title: str
    message: str
    span_id: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)


class TraceDetail(BaseModel):
    """
    TraceInspect 详情页的完整数据包。

    TraceDetail 聚合 run、summary、spans、events、artifacts、diagnosis 和 warnings。
    后端 API 直接返回这个结构，前端无需理解 JSONL 文件布局。warnings 主要用于
    暴露损坏 JSONL 行、缺失 index 或读取降级等问题。
    """

    run: Optional[TraceRun] = None
    summary: Optional[TraceRunSummary] = None
    spans: List[TraceSpan] = Field(default_factory=list)
    events: List[TraceEvent] = Field(default_factory=list)
    artifacts: List[TraceArtifact] = Field(default_factory=list)
    diagnosis: List[TraceDiagnosis] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
