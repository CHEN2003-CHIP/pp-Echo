# 02 Missions

Mission 是一段时间内最重要的推进目标。每个 Mission 使用 Mission -> Task -> Check。

## Mission 管理方法

### Mission

回答：这次要把项目推进到什么状态？

### Task

回答：为了完成 Mission，需要做哪些小步骤？

### Check

回答：怎样知道这一步真的完成了？

## Mission 模板

```markdown
## Mission XX：名称

目标：

背景：

Must Have：

Should Have：

Won't Have：

Tasks：

Checks：

验收标准：

风险：

完成定义：
```

## Mission 01：建立 Solo AI-native 工作流

目标：

建立一套适合一人团队、AI 协作开发和 Vibe Coding 的轻量项目治理脚手架。

背景：

pp-Echo 当前是学习型 Agent 项目，正在进入产品化推进状态。本阶段需要先建立项目工作流，让后续功能开发不再只依赖临时聊天上下文。

Must Have：

- 根目录 `AGENTS.md` 明确后续 AI Agent 协作规则。
- 根目录 `BOARD.md` 提供轻量看板。
- 根目录 `PROMPTS.md` 提供可复用 Prompt 模板。
- `solo-workdocs/` 保存 Vision、Roadmap、Mission、Decision、Risk、Release Log。
- 明确 `docs/` 与 `solo-workdocs/` 的职责边界。

Should Have：

- 文档短、清晰、可执行。
- 能直接指导 Week 2 的安全文件编辑闭环。
- 每个后续任务都能落到 Mission -> Task -> Check。

Won't Have：

- 不开发 Agent 新功能。
- 不重构核心代码。
- 不添加依赖。
- 不接入三方 API。
- 不提交 commit。

Tasks：

- 更新根目录 `AGENTS.md`。
- 创建 `BOARD.md`。
- 创建 `PROMPTS.md`。
- 创建 `solo-workdocs/00-vision.md`。
- 创建 `solo-workdocs/01-roadmap.md`。
- 创建 `solo-workdocs/02-missions.md`。
- 创建 `solo-workdocs/03-decisions.md`。
- 创建 `solo-workdocs/04-risks.md`。
- 创建 `solo-workdocs/05-release-log.md`。

Checks：

- 所有指定文件存在。
- 没有修改核心源代码。
- 没有新增依赖。
- 没有写入 `docs/`。
- 输出 summary 等待人工确认。

验收标准：

- 用户能通过这些文件知道当前项目定位、路线图、下一步任务和风险。
- 后续 AI Agent 能通过 `AGENTS.md` 明确不要擅自扩大范围。

风险：

- 文档变成空泛流程。
- 后续 Agent 忽略边界直接开发功能。
- Roadmap 过满，导致个人项目推进压力过大。

完成定义：

Mission 01 在用户人工确认文档内容后完成。

## Mission 02：安全文件编辑闭环

目标：

让 pp-Echo 的 AI 协作开发具备安全文件编辑闭环，包括范围确认、变更摘要、验证反馈、失败处理和人工确认。

当前拆分：

Mission 02 先拆成 Mission 02A：设计与现状调研。本阶段不直接开发功能代码。

## Mission 02A：安全文件编辑闭环设计与现状调研

目标：

调研当前仓库中与文件读取、文件写入、工具执行、审批、安全边界和变更摘要相关的现状，并设计一套最小可行的安全文件编辑闭环。

范围：

- 阅读 `AGENTS.md`、`.pp-echo/project-map.json` 和相关 `MODULE.md`。
- 梳理当前已有文件编辑、工具调用、审批、trace 或 coding workflow 能力。
- 定义一次安全文件编辑任务的输入、边界、步骤和输出。
- 定义 diff 摘要、验证结果、失败反馈、人工确认点。
- 判断 Mission 02B 是否需要代码修改，以及可能涉及哪些模块。

不做什么：

- 不直接开发文件编辑功能。
- 不修改 runtime/tooling 核心代码。
- 不添加依赖。
- 不接入三方 API。
- 不运行安装命令。
- 不提交 commit。

验收标准：

- 输出一份 Mission 02A 调研与设计 summary。
- 明确当前能力、缺口和风险。
- 明确安全文件编辑闭环的最小流程。
- 明确后续若要开发，应该触碰哪些模块、需要哪些测试。
- 明确哪些操作必须人工确认。

完成定义：

用户确认 Mission 02A 的设计后，才进入 Mission 02B 的实现规划或代码开发。
