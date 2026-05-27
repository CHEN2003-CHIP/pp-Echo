# 7 天读懂 pp-Echo

这份路线把 pp-Echo 当作一门 Agent 工程课来读。每天先运行 `mini-pp-echo/` 里的小脚本，再回到完整工程看真实实现。

## 学习方式

每天建议按同一个节奏走：

1. 先运行当天的 mini 示例，确认机制能跑起来。
2. 再读完整工程源码，找到真实项目中对应的边界条件。
3. 对照流程图，把“模型决定”和“工程约束”分开看。
4. 最后做一个小作业，把机制改一点点。

## 文章目录

| Day | 主题 | 文章 |
| --- | --- | --- |
| Day 1 | Agent Loop 是怎么跑起来的 | [day01-agent-loop.md](day01-agent-loop.md) |
| Day 2 | Tool Registry 与工具调用 | [day02-tool-registry.md](day02-tool-registry.md) |
| Day 3 | 文件读写、Patch 与代码修改 | [day03-file-edit.md](day03-file-edit.md) |
| Day 4 | Approval Gate 与安全策略 | [day04-approval-gate.md](day04-approval-gate.md) |
| Day 5 | Session、Timeline 与 Checkpoint | [day05-session-checkpoint.md](day05-session-checkpoint.md) |
| Day 6 | Memory 检索与上下文注入 | [day06-memory.md](day06-memory.md) |
| Day 7 | MCP、Browser 与 SubAgent 扩展 | [day07-mcp-browser-subagent.md](day07-mcp-browser-subagent.md) |

## 推荐前置准备

教学最小版不需要真实 LLM API：

```powershell
python mini-pp-echo/01_loop.py
```

完整工程建议先确认 CLI 可以加载：

```powershell
set PYTHONPATH=src
python -m pp_agent.cli.main --help
```

如果要真实对话，再配置模型 key：

```powershell
set PP_AGENT_API_KEY=your_api_key
python -m pp_agent.cli.main chat
```

## 阅读主线

这 7 天不是按功能菜单组织，而是按一个本地编程 Agent 从小到大的工程演化组织：

- Day 1 先有 loop。
- Day 2 把能力封装成工具。
- Day 3 让工具能改文件。
- Day 4 给高风险动作加审批。
- Day 5 给会话和代码状态加回退。
- Day 6 给 Agent 加记忆。
- Day 7 接入外部能力和受控子任务。

读完后，你应该能说清楚：一个 Claude Code / Cursor 式本地 Agent，除了 LLM 调用之外，还需要哪些工程层。
