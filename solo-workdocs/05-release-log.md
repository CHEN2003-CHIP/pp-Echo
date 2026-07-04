# 05 Release Log

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
