from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field


class UserAgendaStep(BaseModel):
    kind: Literal["message", "approve_pending", "reject_pending"]
    text: str = ""
    tool: str = ""

    model_config = {"extra": "forbid"}


class SuccessCriteria(BaseModel):
    """
    评测任务的最终成功标准。

    SuccessCriteria 描述 Agent 完成任务后必须满足的结果条件。
    评分器会根据这些字段检查文件变化、文件内容、验证命令、
    最终回复，以及 memory recall、protected path block、checkpoint rewind
    等特殊行为是否符合预期。

    它关注的是“任务结束后的结果是否正确”。
    工具使用、审批要求、禁止工具等过程约束由 ActionConstraints 定义。
    """
    # 评测结束后需要执行的验证命令。
    # 例如：["python -m py_compile app.py", "python -c \"import app; assert app.add(2, 3) == 5\""]
    # 如果命令返回码不是 0，就认为 state 检查失败。
    verification_commands: list[str] = Field(default_factory=list)

    # 期望被修改的文件列表。
    # scorer 会比较 before_snapshot 和 after_snapshot。
    # 如果这里声明的文件没有变化，则判定失败。
    # 例如：["app.py"]
    expected_files_changed: list[str] = Field(default_factory=list)

    # 禁止被修改的文件列表。
    # 如果这些文件在评测后发生变化，则判定失败，并且会记为 safety violation。
    # 例如：["README.md", ".env"]
    forbidden_files_changed: list[str] = Field(default_factory=list)

    # 检查最终文件中必须包含哪些内容。
    # key 是文件路径，value 是该文件必须包含的字符串列表。
    # 例如：{"app.py": ["return a + b"]}
    final_files_contains: dict[str, list[str]] = Field(default_factory=dict)

    # 检查最终文件中不能包含哪些内容。
    # key 是文件路径，value 是该文件不能出现的字符串列表。
    # 例如：{"app.py": ["return 0"]}
    final_files_not_contains: dict[str, list[str]] = Field(default_factory=dict)

    # 检查 Agent 最终回复中必须包含的关键词或句子。
    # scorer 会把 trace.assistant_messages 拼起来，然后查找这些字符串。
    # 例如：["已完成", "没有修改 README"]
    required_communication: list[str] = Field(default_factory=list)

    # 是否要求触发 protected_path_blocked 事件。
    # 用于测试敏感路径保护，比如 Agent 试图访问 .env 时必须被拦截。
    protected_path_block_required: bool = False

    # 是否要求触发 memory_recall 事件。
    # 用于测试 Agent 是否真的调用了记忆召回，而不是凭空回答。
    memory_recall_required: bool = False

    # 是否要求 checkpoint rewind 成功恢复。
    # 如果为 True，scorer 会检查 trace.checkpoint_rewind_restored 是否为 True。
    checkpoint_rewind_restored: bool = False

    # 需要在 rewind 后恢复到原状态的文件。
    # scorer 会比较这些文件在 before_snapshot 和 after_snapshot 中的 hash。
    # 如果前后不一致，说明回滚没有恢复成功。
    rewind_files: list[str] = Field(default_factory=list)

    # 禁止 task json 里出现未声明字段。
    # 这样可以避免拼错字段名却静默通过。
    model_config = {"extra": "forbid"}


class ActionConstraints(BaseModel):
    """
    动作约束模型：定义 AI 执行工具/操作时的权限与限制规则
    用于控制 AI 可以做什么、必须做什么、禁止做什么、需要审批什么
    属于 AI 执行安全与流程控制核心配置
    """
    required_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    required_approvals: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class EvalTask(BaseModel):
    """
    评估任务模型
    定义一个完整的 AI Agent 自动化评测任务的所有配置与规则
    用于控制评测环境、目标、流程、限制条件
    """
    id: str
    name: str
    category: str
    workspace_fixture: str
    max_turns: int = 4
    user_agenda: list[UserAgendaStep]
    success_criteria: SuccessCriteria = Field(default_factory=SuccessCriteria)
    action_constraints: ActionConstraints = Field(default_factory=ActionConstraints)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class CommandResult(BaseModel):
    """
    命令执行结果模型
    用于统一封装 终端/Shell 命令执行后的返回结果
    """
    command: str
    returncode: int
    stdout: str = ""
    stderr: str = ""


class AgentTrace(BaseModel):
    """
    Agent 执行追踪记录模型。
     用于完整记录一次 AI Agent 任务执行的全过程：行为、调用、结果、错误、耗时等。
     常用于自动化评测、日志审计、问题排查、效果统计
    """
    task_id: str
    mode: str
    turns: int = 0
    session_id: str = ""
    assistant_messages: list[str] = Field(default_factory=list)
    tool_calls: list[str] = Field(default_factory=list)
    approvals: list[str] = Field(default_factory=list)
    rejected_approvals: list[str] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[bool] = Field(default_factory=list)
    pending_actions: list[str] = Field(default_factory=list)
    checkpoint_rewind_restored: bool = False
    infra_failed: bool = False
    failure_kind: str = ""
    duration_seconds: float = 0.0


class CaseScore(BaseModel):
    """
    单评测用例打分结果结构体
    归属评测结果层，由评测执行器运行用例后生成。
    汇总任务成败、多维度奖励分数、工具指标、安全违规、验收命令结果，用于汇总报表与模型效果统计。
    """
    task_id: str                          # 关联评测任务唯一ID
    category: str                         # 用例业务分类
    passed: bool                          # 用例最终验收是否通过
    pending: bool = False                 # 用例待执行标记
    infra_failed: bool = False            # 基础设施异常导致任务失败
    failure_reasons: list[str] = Field(default_factory=list)  # 任务失败原因清单
    safety_violations: list[str] = Field(default_factory=list) # 安全约束违规记录
    state_reward: float = 0.0             # 任务目标达成奖励分
    communication_reward: float = 0.0    # 对话交互质量奖励分
    action_reward: float = 0.0            # 工具调用动作合规奖励分
    approval_recall: float = 1.0          # 需审批动作的触发召回率
    tool_call_count: int = 0              # 全流程工具调用总次数
    tool_success_rate: float = 1.0        # 工具执行成功率
    turn_count: int = 0                   # Agent对话交互总轮数
    duration_seconds: float = 0.0         # 用例整体运行耗时(秒)
    verification_results: list[CommandResult] = Field(default_factory=list) # 验收脚本执行结果列表
    trace_events: list[dict[str, Any]] = Field(default_factory=list)        # 全链路事件日志，用于问题复盘


class EvalReport(BaseModel):
    """
    评测任务汇总报告实体。

    EvalReport 是整套自动化评测的顶层聚合输出结构：
    - 记录本次评测的版本、模型、运行环境等基础元信息；
    - 汇总全部评测用例的通过、失败、环境异常等统计数据；
    - 聚合任务成功率、多维度奖励分、安全指标、工具调用指标、耗时指标；
    - 提供按分类维度的统计摘要与单条用例全量详情。

    它根据所有 CaseScore 结果进行二次统计聚合，生成可用于展示、对比、归档的评测报表。
    支持模型效果对比、版本质量验收、评测看板可视化与问题复盘。

    它不负责执行评测用例、不负责打分计算，
    只负责最终数据的汇总、结构化、指标统计与结果承载。
    """
    commit_hash: str
    date: str
    provider: str
    model: str
    mode: str
    suite: str
    total_cases: int
    passed: int
    failed: int
    pending: int
    infra_failed: int
    task_success_rate: float
    state_reward: float
    communication_reward: float
    action_reward: float
    safety_violations: int
    safety_rate: float
    approval_recall: float
    tool_success_rate: float
    average_tool_calls: float
    average_turns: float
    average_duration: float
    category_summary: dict[str, dict[str, Union[float, int]]]
    chart_path: str = ""
    cases: list[dict[str, Any]]


class RunConfig(BaseModel):
    """
    评测任务运行配置实体。

    RunConfig 承载单次评测任务的全部运行控制参数：
    - 指定待运行的评测套件名称，限定本次执行用例范围；
    - 选择确定性复现/在线实测两种运行模式，控制随机与环境逻辑；
    - 配置目标评测模型、随机种子、最大执行超时；
    - 自定义结果输出目录，开关全量对话历史落地存储。

    评测启动时读取本配置，由执行引擎依据参数过滤用例、初始化运行环境、约束任务生命周期。
    所有参数可通过命令行、配置文件或代码入参灵活覆盖。

    它不包含单用例规则与打分逻辑，
    只管控评测整体的运行范围、环境参数与产物存储策略。
    """
    suite: str = "pp_echo_core"                    # 待执行评测套件名称，默认pp_echo_core
    mode: Literal["deterministic", "live"] = "deterministic"  # 运行模式：deterministic固定种子复现，live真实在线环境
    model: Optional[str] = None                    # 指定待评测大模型名称，为空使用系统默认模型
    case_count: Optional[int] = None               # 限定本轮执行用例总数，空则执行套件全部用例
    seed: int = 0                                  # 全局随机种子，用于确定性复现实验
    timeout_seconds: int = 120                     # 单个用例最大执行超时秒数
    output_dir: Optional[str] = None               # 评测报表、日志输出目录，为空使用默认路径
    save_history: bool = False                     # 是否落地存储全量对话与运行历史
