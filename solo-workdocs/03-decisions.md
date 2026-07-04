# 03 Decisions

本文件记录 Solo AI-native 项目治理决策。复杂技术架构 ADR 仍可放在 `docs/adr/`。

## ADR 模板

```markdown
## ADR-XXX：标题

状态：Proposed / Accepted / Superseded

日期：YYYY-MM-DD

背景：

决策：

原因：

影响：

后续检查点：
```

## ADR-001：采用 Solo AI-native 工作流，而不是重型企业流程

状态：Accepted

日期：2026-07-04

背景：

pp-Echo 是一人主导的 Agent 产品研发项目。它需要足够的管理结构来持续推进，但不能引入重型企业流程，否则会降低 Vibe Coding 和快速试错效率。

决策：

采用 Solo AI-native 工作流，以 Mission -> Task -> Check 为主线。项目管理文档放在 `solo-workdocs/`，根目录保留 `AGENTS.md`、`BOARD.md` 和 `PROMPTS.md` 作为日常入口。

原因：

- 一人团队需要低维护成本。
- AI 协作需要明确边界和验收。
- Mission 比长期大计划更容易驱动实际进展。
- 轻量 ADR 和风险清单足够支撑当前阶段。

影响：

- 后续任务必须先说明 Mission 和边界。
- AI Agent 不能在没有明确请求时擅自开发功能或重构。
- `docs/` 与 `solo-workdocs/` 职责分离，避免管理文档和技术文档混用。

后续检查点：

- Week 2 结束时检查工作流是否真的帮助文件编辑闭环。
- Week 5 结束时检查 Mission -> Task -> Check 是否能支撑 Coding Agent MVP。
- v0.3 Beta 前检查是否需要引入更正式的发布流程。
