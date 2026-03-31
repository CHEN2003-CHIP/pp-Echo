# pp-agent

`pp-agent` is a Windows-first personal coding agent inspired by `pi-mono`.
`pp-agent` 是一个优先面向 Windows 的个人 coding agent，整体架构参考 `pi-mono`。

## Overview | 项目概览

- Model / 模型: `qwen3.5-plus`
- Transport / 接口: Alibaba Bailian OpenAI-compatible `chat/completions`
- Thinking / 思考模式: disabled by default / 默认关闭 `enable_thinking=false`
- Style / 风格: session-based runtime, staged approvals, repo-aware workflow / 会话式 runtime、审批队列、面向代码仓库的工作流

## Workflow | 工作流

```mermaid
flowchart LR
  U["User Prompt / 用户输入"] --> CLI["CLI or BAT / 终端入口"]
  CLI --> RT["Agent Runtime / Agent运行时"]
  RT --> CTX["System Prompt + Summary + Recent Messages / 系统提示 + 摘要 + 最近消息"]
  CTX --> LLM["Qwen3.5-Plus"]
  LLM --> DECIDE["Text Response or Tool Call / 文本回复或工具调用"]
  DECIDE -->|"Text"| CLI
  DECIDE -->|"Tool Call"| TOOLS["Read Search Grep Stage Edit Shell Git"]
  TOOLS --> APPROVALS["Pending Approvals / 待审批队列"]
  APPROVALS --> RT
  APPROVALS --> REPO["Git Status + Diff / Git状态与Diff"]
```

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
- `PP_AGENT_HOME`: optional agent state directory override / 可选 agent 状态目录覆盖

## Project Config | 项目级配置

Create `.pp-agent/config.json` if you want project-level overrides.
如果你想做项目级配置覆盖，可以创建 `.pp-agent/config.json`。

```json
{
  "model": "qwen3.5-plus",
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "enable_thinking": false,
  "shell_timeout_seconds": 30,
  "tool_confirmation": {
    "write_file": true,
    "edit_file": true,
    "run_shell": true
  }
}
```

## Chat Commands | Chat 模式命令

- `/settings`: show active model/runtime state / 查看当前模型与运行状态
- `/session`: show current session id / 查看当前 session id
- `/approvals`: show a friendly approval queue panel / 以更友好的面板形式查看待审批队列
- `/model <name>`: switch model / 切换模型
- `/new`: start a new session / 新建会话
- `/resume <id>`: resume a session / 恢复会话
- `/quit`: exit / 退出

## Approval Queue | 审批队列

The approval queue now supports summary view, preview, and batch actions.
审批队列现在支持摘要视图、预览、批量批准与批量拒绝。

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

- staged file writes / staged 文件写入
- staged file edits / staged 文件编辑
- staged shell commands / staged Shell 命令

## Repo-aware Workflow | 面向仓库的工作流

This command is meant to feel closer to a real coding-agent loop.
这个命令的目标是更接近真实 coding-agent 的工作流闭环。

```powershell
set PYTHONPATH=src
python -m agent_cli.main workflow repo --query "AgentSession"
python -m agent_cli.main workflow repo --query "AgentSession" --path-filter src\agent_core
python -m agent_cli.main workflow repo --token <token>
python -m agent_cli.main workflow repo --token <token> --staged-only
python -m agent_cli.main workflow repo --token <token> --auto-apply --staged-only
```

### Repo Workflow Steps | 仓库工作流步骤

1. `grep_code` searches the relevant code.
   `grep_code` 检索相关代码。
2. Approval summary shows queued actions.
   审批摘要展示当前待处理动作。
3. If a token is provided, the staged action is previewed.
   如果提供 token，会先预览对应的 staged action。
4. If `--auto-apply` is used, the action is applied.
   如果带 `--auto-apply`，会直接执行批准并应用。
5. `git_status` shows current worktree state.
   `git_status` 展示当前 worktree 状态。
6. `git_diff_worktree` shows resulting diff.
   `git_diff_worktree` 展示最终 diff。

### Filters | 过滤能力

- `--path-filter`: limit grep and git diff to a target file or directory.
  `--path-filter`: 将 grep 和 git diff 限制到指定文件或目录。
- `--staged-only`: when a token points to a file action, show only the related file diff.
  `--staged-only`: 当 token 对应文件动作时，只看该动作关联文件的 diff。

## Editing And Compaction | 编辑流与上下文压缩

- Old conversation turns are compacted into a summary plus recent raw messages.
  较老的对话会被压缩成摘要，保留最近消息原文。
- `write_file` and `edit_file` stage by default.
  `write_file` 和 `edit_file` 默认先进入 staged 状态。
- `preview_pending_action` lets you inspect the staged diff or command.
  `preview_pending_action` 用于预览 staged diff 或命令。
- `approve_pending_action` applies file changes or shell commands after approval.
  `approve_pending_action` 负责在审批后真正应用文件修改或执行 shell 命令。

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
2. Confirm the model is `qwen3.5-plus`.
   确认模型是 `qwen3.5-plus`。
3. Open chat and run `/approvals`.
   进入 chat 后运行 `/approvals`。
4. Stage a file edit, preview it, then approve it.
   先 stage 一个文件修改，再预览、再批准。
5. Run `workflow repo` with a query or token.
   用 query 或 token 跑一次 `workflow repo`。
6. Verify git status/diff output is understandable.
   确认 git status/diff 输出可读。

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
```

If `PP_AGENT_API_KEY` is missing or the network is blocked, the CLI should show a clear error instead of a Python stack trace.
如果缺少 `PP_AGENT_API_KEY` 或网络不可用，CLI 应该输出清晰错误，而不是直接抛 Python 堆栈。