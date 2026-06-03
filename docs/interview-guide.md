# pp-Echo 实习与面试准备

这份文档是索引，不替代源码阅读。准备实习、项目面试或简历表达时，建议先按下面顺序读完，再挑 2 到 3 个模块讲深。

## 推荐阅读顺序

1. `mini-pp-echo/`
2. `tutorials/README.md`
3. `docs/source-reading-roadmap.md`
4. `docs/source-map.md`

## 你应该能讲清楚的 6 件事

1. Agent Runtime 如何跑一轮对话。
2. ToolRegistry 如何注册和执行工具。
3. Approval Gate 为什么必要。
4. Session / Checkpoint / Rewind 如何帮助 Coding Agent 安全修改代码。
5. Memory 如何检索并进入上下文。
6. MCP / SubAgent 如何扩展 Agent 能力边界。

## 简历表达可以怎么写

- 阅读并拆解本地 Coding Agent 工程链路，理解从用户输入、上下文构造、模型调用、工具执行、审批到状态持久化的一轮运行流程。
- 理解并实践 ToolRegistry、Approval Gate、Session Tree、Checkpoint/Rewind、Memory Retrieval 和受控 SubAgent 等 Agent 工程机制。

## 面试前自查

- 能不能不用源码，画出 `CLI/TUI -> SessionHost -> AgentRuntime -> ToolRegistry -> Storage` 主链路？
- 能不能说明“工具能被模型调用”和“工具这次允许执行”不是一回事？
- 能不能举一个需要 approval gate 的文件修改例子？
- 能不能说明 memory 检索结果为什么要先构造成 recall snippet，再进入上下文？
- 能不能讲清楚 SubAgent 为什么仍然需要工具白名单和产物边界？
