# pp-Echo 的教学定位

pp-Echo 是一个教学向 Agent 工程项目。它的重点不是证明“模型很聪明”，而是把一个本地编程 Agent 需要的工程骨架拆开：runtime、tool registry、审批、安全回退、记忆、MCP、Browser、SubAgent，以及它们之间的边界。

## 为什么 pp-Echo 是教学向项目

pp-Echo 适合教学，是因为它同时保留了两层材料：

- `mini-pp-echo/`：用 FakeLLM 和独立脚本演示最小机制，不依赖真实 API。
- 完整工程：把同样的机制落到真实 CLI、TUI、Web UI、会话存储、checkpoint、memory、MCP 和 SubAgent 中。

这让学习者可以先理解“概念怎么跑起来”，再理解“真实工程为什么要多这些边界条件”。

## 和普通 Prompt Demo 的区别

普通 Prompt Demo 往往把重点放在 system prompt、few-shot、输出格式和一次性工具调用上。它们适合展示效果，但不适合解释一个 Agent 工程如何长期运行。

pp-Echo 关注的是 Prompt 之外的部分：

- 一轮对话如何进入 `AgentRuntime`。
- 工具如何在 `ToolRegistry` 中声明、筛选、执行。
- 高风险动作如何进入 Approval Gate。
- 文件修改如何被预览、执行、记录和回退。
- 会话如何持久化、分支和恢复。
- 记忆如何被检索并注入上下文。
- MCP、Browser、SubAgent 如何作为受控扩展接入。

## 和 LangChain / AutoGen 教程的区别

LangChain / AutoGen 很适合快速组合应用，但它们会把很多工程细节封装在框架层。学习者能很快搭出 demo，却不一定看清楚底层机制。

pp-Echo 刻意不把这些机制藏起来：

- 你可以直接读 `src/pp_agent/runtime/runtime.py` 看 turn loop。
- 你可以直接读 `src/pp_agent/tools/registry.py` 看工具注册和 allowlist。
- 你可以直接读 `src/pp_agent/tools/policy.py` 和 `src/pp_agent/storage/approvals.py` 看审批模型。
- 你可以直接读 `src/pp_agent/runtime/git_checkpoint.py` 和 `src/pp_agent/runtime/safe_rewind.py` 看回退链路。

这不是说 pp-Echo 比框架更适合所有生产场景，而是说它更适合学习“如果自己实现，需要写哪些层”。

## 和 Claude Code / Cursor 的关系

pp-Echo 不是 Claude Code / Cursor 的商业替代品，也不试图复刻它们的产品体验、模型能力或安全体系。

它更像一个可读的工程骨架：

- Claude Code / Cursor 会规划任务，pp-Echo 展示一个本地 runtime 如何组织 turn。
- Claude Code / Cursor 会调用工具，pp-Echo 展示工具注册、策略和执行边界。
- Claude Code / Cursor 会修改代码，pp-Echo 展示文件工具、效果摘要和 checkpoint。
- Claude Code / Cursor 会保留上下文，pp-Echo 展示 session、timeline 和 memory 的组合。
- Claude Code / Cursor 可能有多 Agent 或扩展能力，pp-Echo 展示受控 SubAgent 与 MCP 接入。

学习 pp-Echo 的目标，是理解这些产品背后的工程问题，而不是替代它们。

## 学习者应该如何阅读这个仓库

建议按三层阅读：

1. 先跑 `mini-pp-echo/`：每天一个脚本，把核心机制用最小代码跑通。
2. 再读 [tutorials/README.md](../tutorials/README.md)：按 7 天路线把教学脚本映射到真实源码。
3. 最后读完整工程：优先抓 `SessionHost`、`AgentRuntime`、`ToolRegistry` 三个中枢，再向 memory、MCP、Browser、SubAgent 展开。

不要一开始就从所有 CLI 命令、Web UI 组件或测试文件读起。先抓主链路，再看边界条件，pp-Echo 会更像一门课，而不是一团源码。
