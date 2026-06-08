# pp-Echo 完整工程源码阅读路线

这份路线面向已经跑过 `mini-pp-echo/`，但还不知道如何阅读完整工程源码的读者。它不要求你一次读完整个仓库，而是把 pp-Echo 拆成 7 个关卡：每一关只理解一个核心概念，跑一组最小命令，读一组真实文件，最后能把它讲成实习和面试里的工程表达。

建议阅读顺序是：先跑 mini，再读当前 Stage 的源码，再用问题检查自己是否真的理解。遇到不相关的模块先跳过，不要在第一遍阅读时追所有分支。

## Stage 0：只跑 mini，不看完整工程

### 这一关的目标

先建立 Agent 最小运行闭环：用户输入进入 loop，模型产出文本或工具调用，工具执行后把 observation 写回上下文。

### 需要掌握

- Agent Loop 不是一次性问答，而是“模型决策 -> 工具执行 -> observation 回写”的循环。
- Tool Call 至少需要解析、参数校验、执行和结果回填。
- Approval、Memory、Checkpoint、MCP 都是围绕 Runtime 增加的工程能力，不要一开始就混在一起看。

### 需要运行

```powershell
python mini-pp-echo/01_loop.py
python mini-pp-echo/02_tool_call.py
python mini-pp-echo/03_file_edit.py
python mini-pp-echo/04_approval.py
python mini-pp-echo/05_memory.py
python mini-pp-echo/06_checkpoint.py
python mini-pp-echo/07_mcp_mock.py
```

### 需要阅读

- `mini-pp-echo/README.md`
- `mini-pp-echo/01_loop.py`
- `mini-pp-echo/02_tool_call.py`
- `mini-pp-echo/03_file_edit.py`
- `mini-pp-echo/04_approval.py`
- `mini-pp-echo/05_memory.py`
- `mini-pp-echo/06_checkpoint.py`
- `mini-pp-echo/07_mcp_mock.py`

### 读代码时先看什么

先看每个脚本底部的主流程，再回头看类和函数。目标是看懂“输入在哪里进入、状态在哪里变、结果在哪里输出”。

### 暂时可以跳过什么

- 完整工程里的 CLI、TUI、Web UI。
- 真实 LLM provider。
- 持久化、并发、子代理和外部协议。

### 需要回答

1. 为什么 Agent Loop 需要把工具结果写回上下文？
2. `02_tool_call.py` 里工具调用和普通函数调用有什么不同？
3. `04_approval.py` 里审批发生在执行前还是执行后？
4. `06_checkpoint.py` 想解决哪类“改错了”的问题？

### 可以写进简历

- 通过最小 Agent 实现理解 ReAct/Tool-Use 风格 Agent 的基础闭环，包括模型输出解析、工具执行和 observation 回写。

## Stage 1：看 AgentRuntime，只理解一轮对话怎么跑

### 这一关的目标

理解用户输入如何进入 Runtime，Runtime 如何构造上下文、调用模型、处理工具调用，并把一轮对话的状态写回存储。

### 需要掌握

- `AgentRuntime` 是运行中枢，LLM client 只是模型调用适配层。
- 一轮 turn 有状态：开始、构造上下文、请求模型、处理输出、执行工具、持久化结果。
- observation 必须回写上下文，否则模型看不到工具执行结果。
- Runtime 通过事件和 store 让 CLI/TUI/Web 都能观察同一套执行过程。

### 需要运行

```powershell
set PYTHONPATH=src
python -m pp_agent.cli.main --help
python -m pp_agent.cli.main run "请用一句话介绍 pp-Echo"
python -m pytest tests/runtime/test_runtime.py tests/runtime/test_lifecycle.py
```

### 需要阅读

- `src/pp_agent/runtime/runtime.py`
- `src/pp_agent/runtime/turn_loop.py`
- `src/pp_agent/runtime/state.py`
- `src/pp_agent/runtime/events.py`
- `src/pp_agent/runtime/lifecycle.py`
- `src/pp_agent/llm/registry.py`
- `src/pp_agent/llm/provider/base.py`

### 读代码时先看什么

先从 `AgentRuntime.prompt()` 和 turn loop 的入口看起，再看上下文构建、模型调用、工具结果处理和事件发出的位置。

### 暂时可以跳过什么

- TUI 渲染细节。
- 复杂配置合并。
- MCP、SubAgent、Browser 等扩展能力。

### 需要回答

1. `AgentRuntime` 和 LLM client 的职责边界是什么？
2. 为什么 Runtime 需要 turn state？
3. observation 为什么必须进入后续上下文？
4. 一轮对话里，模型调用、工具调用、状态持久化的大致顺序是什么？

### 可以写进简历

- 阅读并理解本地 Coding Agent Runtime 主链路，掌握从用户输入、上下文构造、模型调用、工具调度到状态回写的一轮对话执行流程。

## Stage 2：看 ToolRegistry，只理解工具怎么注册和执行

### 这一关的目标

理解工具不是随便暴露的函数，而是统一注册、统一声明 schema、统一经过策略检查，并用结构化结果回写给 Runtime。

### 需要掌握

- `ToolRegistry` 是 Runtime 和外部动作之间的边界。
- 工具需要 spec、metadata、参数 schema、执行结果和错误返回。
- allowlist 决定“能不能被看见或调用”，policy gate 决定“这次调用是否安全”。
- 工具失败也要变成 observation，而不是让 Runtime 直接崩掉。

### 需要运行

```powershell
set PYTHONPATH=src
python -m pp_agent.cli.main capabilities list
python -m pp_agent.cli.main doctor --workspace .
python -m pytest tests/tools/test_tools.py tests/tools/test_subagent_tool.py
```

### 需要阅读

- `src/pp_agent/tools/registry.py`
- `src/pp_agent/tools/base.py`
- `src/pp_agent/tools/metadata.py`
- `src/pp_agent/tools/file_tools.py`
- `src/pp_agent/tools/search_tool.py`
- `src/pp_agent/tools/repo_tools.py`
- `src/pp_agent/tools/shell_tool.py`
- `src/pp_agent/runtime/tool_surface.py`

### 读代码时先看什么

先看 registry 如何收集内置工具，再看单个工具的 `ToolSpec`、参数处理和返回结构。最后再看 Runtime 如何从 registry 拿工具声明。

### 暂时可以跳过什么

- 每个工具内部的所有边界条件。
- MCP 动态工具接入。
- SubAgent 的 orchestration 细节。

### 需要回答

1. `ToolRegistry` 解决了什么问题？
2. 工具 metadata 对 Runtime、UI 和安全策略分别有什么作用？
3. allowlist 和 policy gate 有什么区别？
4. 工具执行失败后应该如何回写 observation？

### 可以写进简历

- 实现并理解统一工具注册与执行机制，支持工具元数据管理、调用参数解析、执行结果结构化回写和失败处理。

## Stage 3：看 policy/effects，只理解审批为什么发生

### 这一关的目标

理解安全执行链路：文件修改、shell、Git 等动作为什么不能只靠 prompt 控制，而要在工具执行前生成 effect summary 并进入审批。

### 需要掌握

- 高风险动作应该在执行前被识别和解释。
- policy 负责判断风险，effects 负责描述可能发生的变化。
- 审批拒绝后也要给 Runtime 一个可处理的结果。
- prompt 约束是软约束，工具策略是工程边界。

### 需要运行

```powershell
set PYTHONPATH=src
pytest -q tests/architecture
python -m pytest tests/test_approval_feedback_loop.py tests/cli/test_approvals_dynamic.py tests/cli/test_render_approvals.py
```

### 需要阅读

- `src/pp_agent/tools/policy.py`
- `src/pp_agent/tools/effects.py`
- `src/pp_agent/tools/pending_actions.py`
- `src/pp_agent/tools/pending_edits.py`
- `src/pp_agent/storage/approvals.py`
- `src/pp_agent/tools/file_tools.py`
- `src/pp_agent/tools/shell_tool.py`
- `docs/safety.md`

### 读代码时先看什么

先看 policy 如何给工具调用分类，再看 effects 如何描述文件或命令影响，最后看 pending approval 如何被保存、批准、拒绝。

### 暂时可以跳过什么

- Web UI 审批面板。
- release readiness 的历史迁移背景。
- 每一种工具的完整实现细节。

### 需要回答

1. 为什么不能只靠 prompt 控制危险操作？
2. approval gate 发生在工具执行前还是执行后？
3. effect summary 解决了什么问题？
4. 拒绝审批后，Agent 应该如何继续或终止？

### 可以写进简历

- 设计并理解 Agent 高风险操作审批链路，在文件修改和命令执行前生成 effect summary，支持审批、拒绝、失败 observation 回写和可控执行。

## Stage 4：看 SessionHost，只理解会话、分支、回退

### 这一关的目标

理解本地 Coding Agent 为什么需要 session tree、checkpoint、branch 和 safe rewind，而不是只保存一串聊天记录。

### 需要掌握

- session 是带状态和分支的工作上下文，不只是 chat history。
- checkpoint 记录可回退的工作区状态，undo 更偏单步操作撤销。
- rewind 要同时考虑会话状态和代码工作区状态。
- 分支会话适合尝试不同方案，避免污染主线。

### 需要运行

```powershell
set PYTHONPATH=src
python -m pp_agent.cli.main sessions list
python -m pp_agent.cli.main checkpoint --help
python -m pytest tests/runtime/test_session_host.py tests/runtime/test_checkpoints.py tests/runtime/test_safe_rewind.py tests/storage/test_session_store.py
```

### 需要阅读

- `src/pp_agent/runtime/session_host.py`
- `src/pp_agent/runtime/git_checkpoint.py`
- `src/pp_agent/runtime/safe_rewind.py`
- `src/pp_agent/storage/sessions.py`
- `src/pp_agent/storage/checkpoints.py`
- `src/pp_agent/storage/timeline.py`
- `src/pp_agent/domain/session.py`

### 读代码时先看什么

先看 `SessionHost` 如何创建、恢复和 fork session，再看 checkpoint metadata 如何保存，最后看 safe rewind 如何协调 workspace 和 conversation。

### 暂时可以跳过什么

- TUI tree 的渲染。
- Web session manager 的接口层。
- 具体 Git 命令的所有异常分支。

### 需要回答

1. session 和普通 chat history 有什么区别？
2. checkpoint 和 undo 有什么区别？
3. 为什么 Coding Agent 需要安全回退？
4. 分支会话适合解决什么问题？

### 可以写进简历

- 理解并实践本地 Agent 的会话持久化与安全回退机制，支持 session 管理、checkpoint 记录、分支探索和失败恢复。

## Stage 5：看 memory，只理解检索如何进入上下文

### 这一关的目标

理解 memory 不是把聊天历史全部塞回 prompt，而是把长期信息检索出来，压缩成当前 turn 能使用的上下文。

### 需要掌握

- conversation history 是当前会话记录，long-term memory 是可跨轮、跨会话检索的信息。
- memory 可以来自 SQLite、文件记忆、BM25、向量索引和 learning runtime。
- 检索结果要经过筛选和构建，才能注入 prompt/context。
- memory 失败需要可评估：召回不到、召回错、重复召回都是不同问题。

### 需要运行

```powershell
set PYTHONPATH=src
python -m pp_agent.cli.main memory search "AgentRuntime" --scope workspace
python -m pytest tests/test_memory_retrieval.py tests/test_memory_retrieval_hook.py tests/test_memory_bm25.py tests/learning/test_learning_runtime.py
```

### 需要阅读

- `src/pp_agent/memory/retrieval_hook.py`
- `src/pp_agent/memory/retrieval.py`
- `src/pp_agent/memory/recall_builder.py`
- `src/pp_agent/memory/file_memory_store.py`
- `src/pp_agent/memory/file_memory_search.py`
- `src/pp_agent/memory/file_memory_bm25.py`
- `src/pp_agent/memory/index_pipeline.py`
- `src/pp_agent/learning/context.py`
- `src/pp_agent/learning/runtime.py`
- `src/pp_agent/learning/store.py`

### 读代码时先看什么

先看 retrieval hook 什么时候被 Runtime 调用，再看 recall builder 如何把检索结果变成上下文片段，最后看 file memory 和 learning runtime 如何提供长期信息。

### 暂时可以跳过什么

- 向量库 provider 的全部细节。
- 自动索引调度的异常处理。
- learning extractor 的所有启发式规则。

### 需要回答

1. conversation history 和 long-term memory 有什么区别？
2. memory 是什么时候写入的？
3. memory 是什么时候检索的？
4. 检索结果如何进入 prompt/context？
5. memory 检索失败应该怎么评估？

### 可以写进简历

- 理解 Agent 长期记忆机制，掌握偏好、项目知识、调试记录等长期信息的存储、检索和上下文注入流程。

## Stage 6：看 MCP/SubAgent，只理解扩展边界

### 这一关的目标

理解 pp-Echo 如何从本地 Agent 扩展到外部工具协议和受控子 Agent，同时保持工具白名单、轮次限制和产物边界。

### 需要掌握

- MCP 解决外部工具、资源和 prompt 的协议化接入问题。
- SubAgent 是受控委派，不是无限自治团队。
- 子 Agent 也需要工具白名单、轮次限制、工作区边界和结果契约。
- Browser、MCP、SubAgent 都是能力边界，不应该绕过 Runtime 和 ToolRegistry。

### 需要运行

```powershell
set PYTHONPATH=src
python -m pytest tests/mcp/test_mcp_discovery.py tests/mcp/test_mcp_execution.py tests/subagents/test_manager.py tests/subagents/test_capability_isolation.py
```

### 需要阅读

- `src/pp_agent/mcp/manager.py`
- `src/pp_agent/mcp/discovery.py`
- `src/pp_agent/mcp/adapter.py`
- `src/pp_agent/mcp/descriptors.py`
- `src/pp_agent/tools/subagent_tool.py`
- `src/pp_agent/subagents/manager.py`
- `src/pp_agent/subagents/orchestrator.py`
- `src/pp_agent/subagents/capabilities.py`
- `src/pp_agent/subagents/specs.py`
- `src/pp_agent/browser/runtime.py`
- `src/pp_agent/web_tools/runtime.py`
- `docs/mcp-fetch-integration.md`
- `docs/multi_agent_demo.md`

### 读代码时先看什么

先看 MCP manager 如何发现外部能力，再看 `subagent_tool.py` 如何把子代理变成受控工具，最后看 subagent manager/orchestrator 如何限制角色、工具和产物。

### 暂时可以跳过什么

- Web UI 对 Browser 的展示。
- 多 agent 未来路线讨论。
- 第三方 MCP server 的复杂生态。

### 需要回答

1. MCP 解决了什么扩展问题？
2. SubAgent 和普通工具有什么区别？
3. 为什么子 Agent 也需要工具白名单和边界控制？
4. 受控 SubAgent 和完全自治 Multi-Agent 有什么区别？

### 可以写进简历

- 理解 Agent 扩展机制，掌握 MCP 工具接入、受控 SubAgent 调度、工具白名单和能力边界设计。
