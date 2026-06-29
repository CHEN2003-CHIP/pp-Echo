# 安全边界与审批机制

本文说明 pp-Echo 当前已经实现的安全边界。它强调的是“教学向、可观察、可审批”的本地 Agent Runtime，而不是完整系统级沙箱。

## 总体边界

pp-Echo 对高风险动作使用执行期 policy gate。模型可以提出计划或 staged effect，但敏感动作必须经过宿主侧或用户侧确认后才能执行。

当前策略结果包括：

- `allow`：低风险动作可以执行。
- `ask`：动作需要进入审批流程。
- `deny`：动作被策略拒绝。

受保护路径包括：

- `.pp-agent/**`
- `.git/**`
- `.env`
- `.env.*`
- `*.pem`
- `*.key`

重要限制：`.pp-agent/**` 会从模型可见工具中逻辑隔离，但这不等同于物理隔离或完整 sandbox。

## Exact-Effect Approval

敏感文件和 shell 动作会先生成 effect record，再等待审批。审批绑定的是具体 effect，而不是宽泛的“允许执行”。

关键点：

- `payload_digest` 是主要审批绑定。
- 人类可读摘要用于审阅，不是主要安全锚点。
- 文件 effect 会记录目标文件在 staging 时是否存在。
- shell effect 只做窄归一化：空白差异可归一，但命令内容、重定向、引号、参数顺序、timeout 等变化都视为实质变化。
- planner approval 不等于 execution approval。

## Shell 风险分类

shell effect 会补充结构化字段，帮助用户理解风险：

- `command_head`
- `risk_class`
- `writes_workspace_files`
- `touches_external_paths`
- `requests_network`
- `destructive_hint`

常见分类包括：

- `inspect`
- `workspace_mutation`
- `external_mutation`
- `networked`
- `destructive`

这些分类用于更清晰的预览和审批，不会绕过 host-side approval。

## 常用检查命令

```powershell
python -m pp_agent.cli.main approvals list
python -m pp_agent.cli.main approvals summary
python -m pp_agent.cli.main workflow doctor --json
```

release 前检查请参考 [release-checklist.md](release-checklist.md)。

Shell sandbox executor 的当前语义见 [sandbox.md](sandbox.md)。其中 `LocalSandboxExecutor` 只是兼容旧行为，不是安全 sandbox；`DockerSandboxExecutor` 当前只返回 patch candidate，不会自动写回真实 workspace。

`apply_patch_candidate` 在写入真实 workspace 前会获取 `.pp-agent/locks/apply.lock`，用于串行化 pp-Echo 内部的 patch candidate apply。该锁不会阻止外部编辑器、git、用户手动 shell 命令或其他进程并发修改文件；进程异常退出后也不会自动清理 stale lock。
