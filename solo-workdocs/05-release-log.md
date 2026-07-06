# 05 Release Log

## v0.2.0-draft

日期：2026-07-05

当前目标：

完成 Mission 02B 的最小单文件安全文件编辑闭环，为后续 Coding Agent MVP 提供可预览、可批准、可校验、可 checkpoint、可手动 rollback 的写盘基础。

新增：

- `write_file` / `edit_file` staged action 前安全 guard。
- `patch_proposal` 与 `diff_preview` canonical flow。
- approval 绑定 `proposal_digest`。
- apply 前 proposal digest 和 baseline 校验。
- 写盘前单文件 checkpoint。
- checkpoint 存储位置：`.pp-agent/pending-edits/file-checkpoints/`。
- host-only 工具 `rollback_file_checkpoint`。
- `rollback_file_checkpoint` 的 `restored` / `restored_absent` / `already_absent` 状态。
- ToolRegistry / capability / host-only 暴露边界检查。
- 最小 e2e 验证：stage、preview、approve、checkpoint、write、rollback。

变更：

- `rollback_file_checkpoint` 归入 approval execute/control capability，不进入模型普通 tool list。
- Windows newline 使用保真写读，避免平台自动换行转换影响 digest/baseline。
- `patch_proposal` 继续使用轻量 dict，暂不抽 dataclass / domain model。

验证：

- 02B-7 e2e tests：`3 passed`。
- 02B-1/2/3/4/5/6/7 focused 集合：`40 passed, 3 skipped`。
- worktree guard 独立测试：`1 passed`。
- skipped 原因：Windows symlink 创建权限/环境限制。
- pytest cache warning 不影响结果。

已知问题：

- 尚未跑全量测试。
- rollback 目前没有完整 audit log。
- checkpoint content 依赖 pending-edits 下文件存在。
- patch candidate 多文件路径仍使用原有写入方式。
- 动态 extension 直接写盘仍属于后续治理范围。
- 未来可能需要正式 `PatchProposal` contract / dataclass。
- 未来需要 checkpoint retention / cleanup policy。

下一步：

- Mission 03 前先做 git diff review。
- 人工确认 02B 范围和验收结果。
- 按主题拆分提交。
- 补一次全量或更大范围回归测试。

发布日志用于记录阶段成果、已知问题和下一步，不追求正式 changelog 的复杂格式。

## Release 模板

```markdown
## vX.Y.Z

日期：

当前目标：

新增：

变更：

已知问题：

下一步：
```

## v0.1.0-draft

日期：2026-07-04

当前目标：

建立 Solo AI-native 工作流，让 pp-Echo 从学习型 Agent 项目进入可持续产品化推进状态。

新增：

- 根目录 `AGENTS.md` 协作规则。
- 根目录 `BOARD.md` 轻量看板。
- 根目录 `PROMPTS.md` 可复用 Prompt 模板。
- `solo-workdocs/00-vision.md` 项目愿景。
- `solo-workdocs/01-roadmap.md` 12 周路线图。
- `solo-workdocs/02-missions.md` Mission 管理方法与 Mission 01。
- `solo-workdocs/03-decisions.md` Solo AI-native 决策记录。
- `solo-workdocs/04-risks.md` 风险清单。
- `solo-workdocs/05-release-log.md` 发布日志模板。

变更：

- 明确 `solo-workdocs/` 用于个人研发管理。
- 明确 `docs/` 继续用于传统技术文档和架构资料。
- 明确当前阶段不开发新 Agent 功能、不重构核心代码。

已知问题：

- 目前只有治理脚手架，还没有安全文件编辑闭环。
- Roadmap 需要每周根据实际推进修正。
- Prompt 模板需要在真实任务中继续打磨。

下一步：

- Mission 02：安全文件编辑闭环。
- 明确文件修改范围、diff 摘要、人工确认和失败处理方式。
