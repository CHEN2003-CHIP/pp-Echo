# SubAgent 编排演示

pp-Echo 支持通过 `orchestrate_agents` 工具演示 OpenClaw-style subagent 编排。子 agent 会在受控子会话中运行，使用受限工具，并向父 agent 返回摘要。

## 研究型演示

在 Web chat 中输入：

```text
并行分析文件型长期记忆模块的调用链、风险和可优化点。
```

预期流程：

- `memory-scout`
- `repo-researcher`
- `api-scout`

这些 worker 会并行分析不同侧面，再由父 agent 汇总。

## 调试型演示

输入：

```text
并行定位为什么全量 pytest 在 test_catalog 冲突，并告诉我最小修复方案。
```

预期流程：

- `memory-scout`
- `test-investigator`
- `change-reviewer`

## Staged Edit 演示

输入：

```text
允许子 agent 生成 staged diff，但不要自动落盘。请修复 pytest test_catalog collection 冲突。
```

当 `allow_edits=true` 时，`code-worker` 只能通过 `edit_file` 或 `write_file` 生成 staged pending action，不能直接调用 approval 工具。用户需要用 `preview_pending_action` 审阅 token，再通过正常 host approval 流程选择性批准。

## 安全模型

- 子 agent 是 leaf worker，不能继续 spawn 子 agent。
- 默认 `allow_edits=false`。
- 编辑型子 agent 只能 staged pending action，不直接写盘。
- 父 agent 接收摘要、发现、检查路径和 staged token，不接收完整子会话 transcript。
