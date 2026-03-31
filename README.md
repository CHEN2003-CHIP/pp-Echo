# pp-agent

`pp-agent` is a Windows-first personal coding agent inspired by `pi-mono`.
`pp-agent` 是一个优先面向 Windows 的个人 coding agent，整体设计思路参考 `pi-mono`。

## Overview | 项目概览

- Model | 模型: `qwen3.5-plus`
- Transport | 接口: Alibaba Bailian OpenAI-compatible `chat/completions`
- Thinking | 思考模式: disabled by default, `enable_thinking=false`
- Runtime style | 运行时风格: session-based runtime, staged approvals, repo-aware workflow, planner -> executor split
- Safety style | 安全风格: high-risk plans pause for approval before executor continues
- CLI style | 命令行风格: chat-first, approval-first, Windows-friendly

## Architecture | 架构

```mermaid
flowchart LR
  U["User Prompt / 用户输入"] --> CLI["CLI or BAT / 终端入口"]
  CLI --> RT["Agent Runtime / Agent 运行时"]
  RT --> PLAN["Planner / 计划层"]
  PLAN --> CTX["System Prompt + Summary + Recent Messages / 系统提示 + 摘要 + 最近消息"]
  CTX --> LLM["Qwen3.5-Plus"]
  LLM --> DECIDE["Text Response or Tool Calls / 文本回复或工具调用"]
  DECIDE --> GATE{"High-risk plan? / 是否高风险计划?"}
  GATE -->|"No"| EXEC["Executor / 执行层"]
  GATE -->|"Yes"| APPROVALS["Planner Approval Queue / Planner 审批队列"]
  APPROVALS --> EXEC
  EXEC --> TOOLS["Read Search Grep Stage Edit Shell Git"]
  TOOLS --> REPO["Git Status + Diff / Git 状态与 Diff"]
  REPO --> CLI
```

## Planner -> Executor | 计划层与执行层

`pp-agent` now separates planning from execution in a way that is closer to `pi-mono`:
`pp-agent` 现在把计划和执行分层显示，更接近 `pi-mono` 的交互节奏：

- Planner: shows the intended steps before tools run.
- 计划层：先展示准备做什么。
- Executor: shows actual tool starts, results, and failures.
- 执行层：再展示工具真正开始执行、成功或失败。
- High-risk plans can now pause at the planner layer and wait for approval.
- 高风险计划现在可以在 planner 层暂停，等待批准后再进入 executor。

### Planner Approval Gate | Planner 审批门

When the model proposes a high-risk tool call such as `write_file`, `edit_file`, `run_shell`, or `approve_pending_action`, the planner can pause first.
当模型提出高风险工具调用，比如 `write_file`、`edit_file`、`run_shell` 或 `approve_pending_action` 时，planner 会先暂停。

In chat mode, you will see a planner token and can explicitly continue or stop:
在 chat 模式里，你会看到 planner token，可以显式继续或终止：

```text
=== Planner ===
Planned steps:
  [ ] Stage or execute write_file [write_file]
Planner update: [?] Stage or execute write_file [write_file]
Planner paused. Approve with /approve 1234... or reject with /reject 1234...
```

After approval, the same session resumes and the executor runs the pending tool calls.
批准后，会由同一个 session 恢复，并继续执行挂起的工具调用。

## Quick Start | 快速开始

### Fastest Way on Windows | Windows 最快启动方式

1. Set `PP_AGENT_API_KEY` in your terminal or system environment.
   在终端或系统环境变量中设置 `PP_AGENT_API_KEY`。
2. Double-click [start-agent.bat](/E:/Pycharm%20Project/pp-Echo/start-agent.bat).
   双击 [start-agent.bat](/E:/Pycharm%20Project/pp-Echo/start-agent.bat)。
3. Chat with the agent in the opened terminal.
   在打开的终端里直接和 agent 对话。

### Command Line | 命令行方式

```powershell
set PYTHONPATH=src
python -m agent_cli.main chat
python -m agent_cli.main run "请简要介绍你自己"
python -m agent_cli.main sessions list
python -m agent_cli.main config show
```

## Environment Variables | 环境变量

- `PP_AGENT_API_KEY`: Alibaba Bailian API key / 阿里百炼 API Key
- `PP_AGENT_BASE_URL`: optional base URL override / 可选接口地址覆盖
- `PP_AGENT_MODEL`: optional model override / 可选模型覆盖
- `PP_AGENT_ENABLE_THINKING`: optional thinking override / 可选 thinking 开关覆盖
- `PP_AGENT_HOME`: optional state directory override / 可选状态目录覆盖

## Project Config | 项目级配置

Create `.pp-agent/config.json` if you want project-level overrides.
如果你希望做项目级覆盖配置，可以创建 `.pp-agent/config.json`。

```json
{
  "model": "qwen3.5-plus",
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "enable_thinking": false,
  "shell_timeout_seconds": 30,
  "tool_confirmation": {
    "write_file": true,
    "edit_file": true,
    "run_shell": true,
    "high_risk_plan": true
  }
}
```

## Chat Commands | Chat 模式命令

- `/settings`: show active runtime settings / 查看当前运行配置
- `/session`: show current session id / 查看当前 session id
- `/approvals`: show a friendly approval queue panel / 查看友好的审批面板
- `/approve <token>`: approve a pending planner gate or staged action / 批准 planner gate 或 staged action
- `/reject <token>`: reject a pending planner gate or staged action / 拒绝 planner gate 或 staged action
- `/model <name>`: switch model / 切换模型
- `/new`: start a new session / 新建会话
- `/resume <id>`: resume a session / 恢复会话
- `/quit`: exit / 退出

## Approval Queue | 审批队列

The approval queue supports summary view, preview, planner gates, and batch actions.
审批队列支持摘要、预览、planner gate 和批量处理。

```powershell
set PYTHONPATH=src
python -m agent_cli.main approvals summary
python -m agent_cli.main approvals list
python -m agent_cli.main approvals show <token>
python -m agent_cli.main approvals approve <token>
python -m agent_cli.main approvals reject <token>
python -m agent_cli.main approvals approve-all
python -m agent_cli.main approvals reject-all
```

### What Goes Into the Queue | 哪些动作会进入审批队列

- planner approvals for high-risk plans / 高风险计划的 planner 审批
- staged file writes / staged 文件写入
- staged file edits / staged 文件编辑
- staged shell commands / staged shell 命令

### Approval Behavior | 审批行为

- Approving a `planner_approval` token resumes the original session and then runs the pending tool calls.
- 批准 `planner_approval` token 会恢复原始 session，并继续执行挂起的工具调用。
- Rejecting a `planner_approval` token clears the pending plan without executing it.
- 拒绝 `planner_approval` token 会清空挂起计划，不执行任何工具。
- Approving a staged file or shell token behaves the same as before.
- 批准普通 staged 文件或 shell token 的行为和之前一致。

## Repo-aware Workflow | 面向仓库的工作流

This command is designed to feel closer to a real coding-agent loop.
这个命令的目标是更接近真实 coding-agent 的工作闭环。

```powershell
set PYTHONPATH=src
python -m agent_cli.main workflow repo --query "AgentSession"
python -m agent_cli.main workflow repo --query "AgentSession" --path-filter src\agent_core
python -m agent_cli.main workflow repo --token <token>
python -m agent_cli.main workflow repo --token <token> --staged-only
python -m agent_cli.main workflow repo --token <token> --auto-apply --staged-only
```

### Repo Workflow Shape | 仓库工作流结构

The workflow output is split into three sections:
工作流输出分成三部分：

- `planner`: what the agent intends to do next
- `planner`：接下来准备做什么
- `executor`: what commands and tools actually ran
- `executor`：实际执行了哪些工具和命令
- `next_actions`: what a human should review or trigger next
- `next_actions`：接下来建议你审查或触发什么

### Filters | 过滤能力

- `--path-filter`: limit grep and git diff to a file or directory.
- `--path-filter`: 把 grep 和 git diff 限制到指定文件或目录。
- `--staged-only`: when a token points to a file action, show only the related file diff.
- `--staged-only`: 当 token 对应文件动作时，只看相关文件的 diff。

## Editing And Compaction | 编辑流与上下文压缩

- Old conversation turns are compacted into a summary plus recent raw messages.
  较老的对话会被压缩成摘要，最近消息保留原文。
- `write_file` and `edit_file` stage by default.
  `write_file` 和 `edit_file` 默认先进入 staged 状态。
- `preview_pending_action` lets you inspect the staged diff, shell command, or planner summary.
  `preview_pending_action` 用于预览 staged diff、shell 命令或 planner 摘要。
- `approve_pending_action` still applies file changes or shell commands after approval.
  `approve_pending_action` 仍负责在审批后真正应用文件修改或执行 shell 命令。

### Diff Format | Diff 编辑格式

```text
<<<<<<< SEARCH
old text
=======
new text
>>>>>>> REPLACE
```

## Validation Checklist | 首次验证清单

1. Run `python -m agent_cli.main config show`.
   运行 `python -m agent_cli.main config show`。
2. Confirm the model is `qwen3.5-plus` and `high_risk_plan` is enabled.
   确认模型是 `qwen3.5-plus`，并且 `high_risk_plan` 已启用。
3. Open chat and trigger a high-risk request.
   进入 chat 后触发一次高风险请求。
4. Confirm the planner pauses and shows `/approve <token>` or `/reject <token>`.
   确认 planner 会暂停，并显示 `/approve <token>` 或 `/reject <token>`。
5. Approve the token and verify the executor runs afterwards.
   批准 token，确认 executor 会在之后继续执行。
6. Run `workflow repo` with a query or token.
   用 query 或 token 跑一次 `workflow repo`。

## Test | 测试

### Quick Self-check | 快速自检

Double-click [run-tests.bat](/E:/Pycharm%20Project/pp-Echo/run-tests.bat).
双击 [run-tests.bat](/E:/Pycharm%20Project/pp-Echo/run-tests.bat)。

### Command Line Test | 命令行测试

```powershell
set PYTHONPATH=src
python -m pytest -q
python -m agent_cli.main --help
python -m agent_cli.main approvals summary
python -m agent_cli.main workflow repo --query "AgentSession"
python -m agent_cli.main config show
```

If `PP_AGENT_API_KEY` is missing or the network is blocked, the CLI should show a clear error instead of a Python stack trace.
如果缺少 `PP_AGENT_API_KEY` 或网络不可用，CLI 应输出清晰错误，而不是直接抛 Python 堆栈。
