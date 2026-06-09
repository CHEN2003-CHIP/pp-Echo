# pp-Echo 架构导引

这套文档用于系统解释 pp-Echo 的 Agent 工程架构。它不是 API 手册，也不是简单功能列表，而是把 pp-Echo 中的 AgentRuntime、Turn Loop、Context、Model Provider、Memory、ToolRegistry、Safety、TraceInspect、Eval、Onboarding、Storage 等关键模块拆开讲清楚。

pp-Echo 的定位是教学向本地 Agent Runtime：它关注“一个 Claude Code / Cursor 式本地编程 Agent 背后到底需要哪些工程机制”。这些机制包括：规划、工具调用、审批、回退、记忆、MCP、Browser、SubAgent、Eval、TraceInspect 和启动引导。本文档希望让读者既能理解架构图，也能沿着源码路径读懂真实实现。

## 推荐阅读路线

### 新手路线

如果你刚接触 pp-Echo，建议按下面顺序读：

1. `00-overview.md`：先建立整体架构图。
2. `11-typical-workflow.md`：看一次任务从输入到 TraceInspect 的完整链路。
3. `02-turn-loop.md`：理解 Agent 为什么不是一次 LLM 调用。
4. `06-tool-system.md`：理解模型意图如何变成真实工具动作。
5. `07-safety-approval-rewind.md`：理解为什么要审批和回退。

### 源码路线

如果你已经跑通过 Web 或 CLI，建议按主链路读：

1. `01-runtime-core.md`：读 `AgentRuntime` 和 `SessionHost`。
2. `03-context-and-state.md`：读上下文、状态、目标和会话变量。
3. `04-model-provider.md`：读 LLM provider 和 usage 统计。
4. `06-tool-system.md`：读工具注册和执行。
5. `08-observability-traceinspect.md`：读 TraceRecorder 和 TraceInspect。

### 面试路线

如果你想把 pp-Echo 写进简历或用于 Agent 基建面试，优先读：

1. `01-runtime-core.md`
2. `06-tool-system.md`
3. `07-safety-approval-rewind.md`
4. `08-observability-traceinspect.md`
5. `09-eval-onboarding-doctor.md`

这几篇能覆盖 Agent Runtime、工具系统、安全控制、可观测性和工程稳定性，是最容易体现项目含金量的部分。

### 二次开发路线

如果你想扩展 pp-Echo，建议先读：

1. `06-tool-system.md`：新增工具、MCP、SKILL。
2. `05-memory.md`：扩展记忆检索和注入。
3. `08-observability-traceinspect.md`：给新模块补 Trace。
4. `09-eval-onboarding-doctor.md`：给新能力补 Eval 和 Doctor 检查。
5. `10-storage-and-artifacts.md`：确认新增状态如何落盘和回放。

## 文档索引

| 文档 | 主题 | 适合读者 | 建议前置知识 |
|---|---|---|---|
| `00-overview.md` | 总体架构 | 所有人 | Agent 基础概念 |
| `01-runtime-core.md` | AgentRuntime / SessionHost | 想读主流程的人 | 会话、运行时、事件 |
| `02-turn-loop.md` | Observe-Think-Act-Reflect | 想理解 Agent Loop 的人 | LLM 调用、工具调用 |
| `03-context-and-state.md` | Context / State / Goal | 想理解上下文构造的人 | prompt、context window |
| `04-model-provider.md` | Model / Provider / Usage | 想接模型或看用量的人 | OpenAI-compatible API、token |
| `05-memory.md` | Memory / Retrieval / Injection | 想理解长期记忆的人 | 检索、召回、上下文注入 |
| `06-tool-system.md` | ToolRegistry / SKILL / MCP / Browser | 想扩展工具的人 | tool calling、schema |
| `07-safety-approval-rewind.md` | Approval / Policy / Checkpoint / Rewind | 关注安全的人 | 风险动作、审批、Git |
| `08-observability-traceinspect.md` | TraceInspect / Observability | 关注调试和审计的人 | tracing、span、event |
| `09-eval-onboarding-doctor.md` | Eval / Onboarding / Doctor | 关注稳定性和易用性的人 | 测试、诊断、CI |
| `10-storage-and-artifacts.md` | TraceStore / ApprovalRecords / Artifacts | 关注持久化的人 | JSONL、Git、文件系统 |
| `11-typical-workflow.md` | 端到端任务流程 | 所有人 | 读完 overview 更好 |
| `12-attachments-and-large-files.md` | Session attachments / Large files / Import / Memory ingest | 想扩展文件分析的人 | ToolRegistry、Approval、Memory、TraceInspect |

## 和项目其他文档的关系

- `README.md`：适合快速了解项目定位、快速开始和亮点。
- `tutorials/README.md`：适合按 7 天路线学习。
- `docs/source-reading-roadmap.md`：适合闯关式读源码。
- `docs/safety.md`：适合详细理解安全边界。
- `docs/architecture/`：适合按模块系统理解 pp-Echo 架构。

## 总体建议

读 pp-Echo 不要只看某个函数，而要按“请求如何进入、上下文如何构造、模型如何决策、工具如何执行、风险如何审批、状态如何保存、Trace 如何复盘”的链路理解。这样你看到的就不只是一个工具调用 Demo，而是一个教学向本地 Agent Runtime。
