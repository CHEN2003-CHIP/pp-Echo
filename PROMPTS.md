# PROMPTS.md

这些 Prompt 用于后续反复交给 Codex 或其他 AI 编程助手。使用时替换方括号内容，并要求助手先 summary，不直接 commit。

## Mission 拆解 Prompt

```text
项目背景：
pp-Echo 是本地优先 Coding Agent 与通用助手项目，当前采用 Solo AI-native 工作流。

当前任务：
请把 [Mission 名称] 拆成可执行 Task，并设计每个 Task 的 Check。

边界：
- 不扩大 Mission 范围。
- 不修改代码，除非我明确要求。
- 不添加依赖、不接入三方 API、不运行安装命令。
- 不直接 commit。

输出格式：
1. Mission Summary
2. Task List
3. Check List
4. Risks
5. Need Human Review
```

## 技术设计 Prompt

```text
项目背景：
pp-Echo 是一个 runtime platform，核心边界包括 AgentRuntime、ToolRegistry、MCP、skills、memory、capabilities、observability 和 evals。

当前任务：
请为 [功能/模块] 做轻量技术设计。

边界：
- 先读取 AGENTS.md、.pp-echo/project-map.json、相关 MODULE.md 和 ADR。
- 不重构无关代码。
- 不破坏 public API。
- 不新增依赖，除非我单独批准。
- 完成后先 summary，不直接 commit。

输出格式：
1. Problem
2. Proposed Design
3. Files To Touch
4. Tests
5. Risks
6. Open Questions
```

## 安全文件编辑闭环设计 Prompt

```text
项目背景：
pp-Echo 正在建立 Solo AI-native 工作流，下一步是 Mission 02：安全文件编辑闭环。当前只做 Mission 02A：设计与现状调研，不写功能代码。

当前任务：
请调研当前仓库中与文件读取、文件写入、工具执行、审批、安全边界、trace、coding workflow 相关的现状，并设计最小安全文件编辑闭环。

边界：
- 先读取 AGENTS.md、.pp-echo/project-map.json、相关 MODULE.md 和必要 ADR。
- 只做现状调研和设计文档。
- 不修改核心源码。
- 不添加依赖、不接入三方 API、不运行安装命令。
- 不直接实现文件编辑功能。
- 不扩大到 GitHub、Memory、多 Agent 或 UI。
- 完成后先 summary，不直接 commit。

输出格式：
1. Current State
2. Gap List
3. Proposed Safe Edit Loop
4. Human Confirmation Points
5. Files/Modules That May Be Touched Later
6. Tests Needed Later
7. Risks
8. Need Human Review
```

## 代码实现 Prompt

```text
项目背景：
pp-Echo 正在从学习型 Agent 项目推进为可管理中小型代码项目的 Coding Agent。

当前任务：
请实现 [具体任务]。

边界：
- 只修改完成任务所需的最小文件。
- 遵守 AGENTS.md、项目地图和相关 MODULE.md。
- 不添加依赖、不运行安装命令、不接入三方 API。
- 不做无关重构或格式化。
- 完成后先 summary，不直接 commit。

输出格式：
1. Summary
2. Files Changed
3. Verification
4. Risks
5. Need Human Review
```

## 代码审查 Prompt

```text
项目背景：
pp-Echo 是本地优先 Agent runtime 与 Coding Agent 工作台。

当前任务：
请审查 [分支/文件/变更范围]。

边界：
- 以 bug、回归风险、边界破坏、测试缺失为优先。
- 不直接修改代码，除非我明确要求。
- 不扩大到无关模块。
- 不直接 commit。

输出格式：
1. Findings
2. Questions
3. Test Gaps
4. Suggested Fix Order
5. Need Human Review
```

## 测试补全 Prompt

```text
项目背景：
pp-Echo 使用 focused tests 和 doctor/report 作为关键验收方式。

当前任务：
请为 [模块/功能] 补全必要测试。

边界：
- 只覆盖本次行为风险。
- 不做大范围测试重写。
- 不添加依赖。
- 不运行安装命令。
- 完成后先 summary，不直接 commit。

输出格式：
1. Test Scope
2. Files Changed
3. Commands Run
4. Failures
5. Remaining Risk
```

## 周复盘 Prompt

```text
项目背景：
pp-Echo 采用一人团队 + AI 协作开发 + Vibe Coding 的轻量管理方式。

当前任务：
请基于 BOARD.md、solo-workdocs/02-missions.md 和 solo-workdocs/05-release-log.md 做本周复盘。

边界：
- 不修改代码。
- 不粉饰进度。
- 不创建复杂流程。
- 不直接 commit。

输出格式：
1. 本周完成
2. 未完成原因
3. 风险变化
4. 下周 Mission
5. 需要人工决策
```

## 决策记录 Prompt

```text
项目背景：
pp-Echo 的项目治理记录放在 solo-workdocs/，传统技术 ADR 可继续放在 docs/adr/。

当前任务：
请为 [决策主题] 写一条轻量 ADR。

边界：
- 只记录真实需要保留的决策。
- 不引入企业化重流程。
- 不修改代码。
- 不直接 commit。

输出格式：
1. 背景
2. 决策
3. 原因
4. 影响
5. 后续检查点
```

## 风险分析 Prompt

```text
项目背景：
pp-Echo 正在产品化推进，当前需要控制范围、安全、测试和 AI 协作质量风险。

当前任务：
请分析 [Mission/功能/变更] 的风险。

边界：
- 聚焦可触发、可观察、可应对的风险。
- 不写空泛流程。
- 不修改代码。
- 不直接 commit。

输出格式：
1. Risk List
2. Trigger Signals
3. Mitigation
4. Review Timing
5. Need Human Review
```
