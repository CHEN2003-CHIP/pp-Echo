# 7 天读懂 pp-Echo

这份路线把 pp-Echo 当作一门 Agent 工程课来读。每天先运行 `mini-pp-echo/` 里的小脚本，再回到完整工程看真实实现。

## Day 1：Agent Loop 是怎么跑起来的

学习目标：

- 理解一轮用户输入如何变成模型响应、工具调用和最终回答。
- 区分教学版 FakeLLM loop 与完整工程 `AgentRuntime`。

要看的源码路径：

- `mini-pp-echo/01_loop.py`
- `src/pp_agent/runtime/runtime.py`
- `src/pp_agent/runtime/turn_loop.py`
- `src/pp_agent/runtime/events.py`

要运行的命令或示例：

```powershell
python mini-pp-echo/01_loop.py
set PYTHONPATH=src
python -m pp_agent.cli.main chat
```

学完应该理解的问题：

- Agent Loop 为什么通常是“观察、决定、执行、记录”的循环？
- 为什么 runtime 需要事件和状态，而不是只返回一段文本？
- 哪些信息会被放进下一轮上下文？

## Day 2：Tool Registry 与工具调用

学习目标：

- 理解工具为什么要统一注册、描述和执行。
- 看懂工具名、参数、元数据、策略之间的关系。

要看的源码路径：

- `mini-pp-echo/02_tool_call.py`
- `src/pp_agent/tools/registry.py`
- `src/pp_agent/tools/base.py`
- `src/pp_agent/tools/metadata.py`

要运行的命令或示例：

```powershell
python mini-pp-echo/02_tool_call.py
set PYTHONPATH=src
python -m pp_agent.cli.main capabilities legacy-hints --json --workspace .
```

学完应该理解的问题：

- 为什么真实 Agent 不应该让模型直接调用任意 Python 函数？
- tool schema 对模型和安全策略分别有什么价值？
- allowlist / denylist 为什么要绑定真实工具名？

## Day 3：文件读写、Patch 与代码修改

学习目标：

- 理解本地编程 Agent 如何把“我要改代码”拆成读文件、生成 patch、应用修改。
- 理解效果摘要和可审查修改的重要性。

要看的源码路径：

- `mini-pp-echo/03_file_edit.py`
- `src/pp_agent/tools/file_tools.py`
- `src/pp_agent/tools/pending_edits.py`
- `src/pp_agent/tools/effects.py`

要运行的命令或示例：

```powershell
python mini-pp-echo/03_file_edit.py
set PYTHONPATH=src
python -m pp_agent.cli.main run "read README.md and summarize the first section"
```

学完应该理解的问题：

- 读文件、生成修改、执行修改为什么要分层？
- patch 比直接覆盖文件更适合教学和审查在哪里？
- Agent 修改代码时，哪些信息应该进入日志或 timeline？

## Day 4：Approval Gate 与安全策略

学习目标：

- 理解高风险动作为什么要先变成 pending action。
- 看懂 allow / ask / deny 的基本策略模型。

要看的源码路径：

- `mini-pp-echo/04_approval.py`
- `src/pp_agent/tools/policy.py`
- `src/pp_agent/tools/effects.py`
- `src/pp_agent/storage/approvals.py`
- `src/pp_agent/tools/pending_actions.py`

要运行的命令或示例：

```powershell
python mini-pp-echo/04_approval.py
set PYTHONPATH=src
python -m pp_agent.cli.main approvals summary
```

学完应该理解的问题：

- 为什么审批对象应该绑定精确效果，而不是只绑定一句自然语言？
- 哪些工具应该默认 ask？
- 用户拒绝后，Agent 下一步应该如何恢复对话？

## Day 5：Session、Timeline 与 Checkpoint

学习目标：

- 理解会话不是聊天数组，而是可恢复、可分支、可回退的状态树。
- 理解 checkpoint 与 safe rewind 在 Agent 编程场景中的价值。

要看的源码路径：

- `mini-pp-echo/06_checkpoint.py`
- `src/pp_agent/runtime/session_host.py`
- `src/pp_agent/storage/sessions.py`
- `src/pp_agent/storage/timeline.py`
- `src/pp_agent/runtime/git_checkpoint.py`
- `src/pp_agent/runtime/safe_rewind.py`

要运行的命令或示例：

```powershell
python mini-pp-echo/06_checkpoint.py
set PYTHONPATH=src
python -m pp_agent.cli.main sessions tree
python -m pp_agent.cli.main checkpoint list
```

学完应该理解的问题：

- 为什么会话恢复需要比“加载历史消息”更多的信息？
- checkpoint 记录代码状态，timeline 记录行为历史，二者如何互补？
- safe rewind 与普通 `git reset` 的差别是什么？

## Day 6：Memory 检索与上下文注入

学习目标：

- 理解 memory 不是“把所有历史塞进 prompt”。
- 理解检索、筛选、摘要、注入的最小链路。

要看的源码路径：

- `mini-pp-echo/05_memory.py`
- `MEMORY.md`
- `src/pp_agent/memory/retrieval.py`
- `src/pp_agent/memory/recall_builder.py`
- `src/pp_agent/learning/context.py`
- `src/pp_agent/learning/runtime.py`

要运行的命令或示例：

```powershell
python mini-pp-echo/05_memory.py
set PYTHONPATH=src
python -m pp_agent.cli.main memory search "AgentRuntime" --scope workspace
```

学完应该理解的问题：

- 什么样的信息值得进入长期记忆？
- 检索结果为什么需要排序和压缩？
- 记忆注入应该怎样避免污染当前任务？

## Day 7：MCP、Browser 与 SubAgent 扩展

学习目标：

- 理解 Agent 能力扩展的三条路径：外部 MCP、浏览器工具、受控 SubAgent。
- 看懂“扩展能力”为什么仍然要经过工具注册和策略边界。

要看的源码路径：

- `mini-pp-echo/07_mcp_mock.py`
- `src/pp_agent/mcp/*`
- `src/pp_agent/browser/*`
- `src/pp_agent/web_tools/*`
- `src/pp_agent/tools/subagent_tool.py`
- `src/pp_agent/subagents/*`

要运行的命令或示例：

```powershell
python mini-pp-echo/07_mcp_mock.py
set PYTHONPATH=src
python -m pp_agent.cli.main config show --workspace .
```

学完应该理解的问题：

- MCP 工具为什么要有发现、描述、调用、结果转换这几层？
- Browser 工具为什么需要额外策略，而不是普通 HTTP 请求？
- SubAgent 如何避免变成不可控的“另一个主 Agent”？
