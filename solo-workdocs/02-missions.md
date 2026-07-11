# 02 Missions

## Mission 05: Repository Summary Integration with Existing ContextPipeline

Status: Ratified / 05A completed / design ready

Details:

- `solo-workdocs/mission-docs/12-mission-05-repository-summary-context-pipeline-design.md`

Goal:

Integrate selected `RepositorySummary` content into the existing runtime/context path by adapting it into multiple `ContextItem(section="project_context")` entries.

Official direction:

- Mission 05 comes first: repository summary integration into the existing `ContextPipeline`.
- Mission 06 comes second: scoped repository instructions.
- Reuse `ContextPipeline`, `ContextPack`, `final_messages`, `context_built`, `ContextBudgeter`, and `SourceRef`.
- Keep `project_context` as the canonical section.
- Convert only approved project instructions and relevant module guidance into model-facing context.
- Keep warnings trace-only by default.
- Use a minimal `RepositorySummarySource -> SourceRef` adapter.

Completed:

- 05A: codebase reconnaissance, OpenCode comparison, and scope ratification.

Planned tasks:

- 05B: implement the minimal `RepositorySummary -> ContextItem` adapter for selected instructions/module guidance.
- 05C: integrate the adapter into the existing context build path and run release-gate verification.

Future boundary:

- Mission 06 candidate: scoped repository instructions.
- Mission 06 should research nearby instruction resolution, ancestor-chain behavior, scoped relevance, lazy activation, duplicate suppression, and OpenCode source-level behavior.
- Mission 06 must not use generic recursive repository scans as the default approach.

Not done:

- No new `CodingContextBundle`.
- No new `RepositoryContextBundle`.
- No new canonical section such as `repository_summary`, `repository_context`, or `coding_context`.
- No new `ContextPipeline`.
- No new budget engine.
- No new renderer.
- No new trace schema.
- No new provider message path.
- No raw `RepositorySummary.to_dict()` JSON injection into prompts.
- No dynamic nearby `AGENTS.md` / `CLAUDE.md` discovery.
- No automatic ancestor instruction lookup.
- No recursive scans.
- No repository file rereads in the adapter.
- No runtime execution, provider, tool, approval, or policy semantic changes.
- No Mission 05B implementation in this ratification step.
- No Mission 06 implementation or research in this ratification step.

Checks:

- Mission 05 is formally defined.
- 05A is marked completed.
- The human decision `A first, B second` is recorded.
- OpenCode scoped-instruction direction is preserved for future Mission 06.
- Scope remains docs-only for this ratification step.

## Mission 03: Safe Tool Execution Loop

Status: Ready for human review

Details:

- `solo-workdocs/mission-docs/08-mission-03-tool-execution-design.md`
- `solo-workdocs/mission-docs/09-mission-03-tool-execution-closeout.md`
- `solo-workdocs/mission-docs/10-mission-04-bounded-repository-summary-design.md`

Goal:

Build the smallest safe command/test execution loop:

`stage -> preview -> approve -> proposal digest check -> execute -> bounded result`

Completed:

- 03A: reference research and current-state design.
- 03B: `CommandProposal` / `CommandPreview` convergence.
- 03C: approval-bound command proposal digest verification.
- 03D: bounded stdout/stderr execution result contract.
- 03E: `stage_test_command` pytest helper.
- 03F: registry / capability integration and worktree direct shell result contract check.
- 03G: e2e demo, release gate, and docs closeout.

Not done:

- No new shell executor.
- No auto-run tests.
- No auto retry or auto repair.
- No CI / GitHub Actions.
- No package install automation.
- No remote execution.
- No multi-command transaction.
- No background tasks.

## Mission 04: Bounded Repository Scan and Deterministic Project Summary

Status: Ratified / design ready

Details:

- `solo-workdocs/mission-docs/10-mission-04-bounded-repository-summary-design.md`

Goal:

Build a bounded, deterministic, traceable, JSON-friendly repository summary for the existing coding runtime/context layer.

Approved scope:

- Aggregates existing `ProjectContext` and `RepositoryAnalysis`.
- Reads only approved project instruction and map documents:
  - repository-root `AGENTS.md` or equivalent project instruction file;
  - known project-map document;
  - relevant `MODULE` documents for the target module.
- Includes language/framework signals, known entrypoints, test commands, shallow module information, instruction sources, protected areas, key risks, source citations, and explicit skipped/truncated metadata.
- Serves only runtime/context in the first version.
- Does not provide standalone CLI/Web display in the first version.
- Does not perform generic unbounded recursive repository scanning.

Planned tasks:

- 04B: `RepositorySummary` contract.
- 04C: bounded source collection.
- 04D: context integration and release gate.

Not done:

- No Mission 04 implementation in this ratification step.
- No runtime execution loop rewrite.
- No `AgentRuntime` rewrite.
- No Mission 03 tool execution semantic changes.
- No agent mode framework.
- No permission DSL.
- No child-session system.
- No generic code index.
- No embeddings or vector database.
- No model-driven repository summary.
- No background scan.
- No filesystem watcher.
- No full CLI/Web repo browser.
- No MCP/LSP/ACP expansion.
- No complex config merge system.
- No automatic repository modification.

## Mission 02B：安全文件编辑闭环最小实现

状态：Completed / 待人工最终 review

详情文档：

- `solo-workdocs/mission-docs/07-mission-02B-safe-file-edit-closeout.md`

目标：

形成最小单文件安全文件编辑闭环：

`stage -> preview -> approve -> digest/baseline check -> checkpoint -> write -> rollback`

已完成：

- 02B-1：`write_file` / `edit_file` 安全 guard。
- 02B-2：`patch_proposal` / `diff_preview` 收敛。
- 02B-3：approval digest / baseline 校验。
- 02B-4：checkpoint before edit。
- 02B-4.5：focused test 独立收集循环导入修复。
- 02B-5：`rollback_file_checkpoint` 单文件 rollback。
- 02B-6：ToolRegistry / capability / host-only 边界检查。
- 02B-7：最小 e2e 验证。

验收结果：

- 02B-7 e2e tests：`3 passed`。
- 02B-1/2/3/4/5/6/7 focused 集合：`40 passed, 3 skipped`。
- worktree guard 独立测试：`1 passed`。

不做：

- 多文件事务。
- Git rollback。
- 自动 rollback。
- 完整 audit log 重构。
- checkpoint 存储位置重构。
- AST 编辑。
- 自动 commit。
- 三方 API。
- IDE。
- GitHub PR。
- Mission 03。

Mission 是一段时间内最重要的推进目标。每个 Mission 使用 Mission -> Task -> Check。

`solo-workdocs/02-missions.md` 只作为 Mission 索引、模板和状态总览。

`solo-workdocs/mission-docs/` 用于保存每个 Mission 的详细调研、设计、执行和复盘文档。

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

调研 pp-Echo 当前文件编辑相关能力，并对标 OpenCode、Cline、Aider、OpenHands、SWE-agent 等成熟项目，提炼适合 pp-Echo 当前阶段的安全文件编辑闭环设计。

范围：

- 阅读 `AGENTS.md`、`.pp-echo/project-map.json` 和相关 `MODULE.md`、查看参考项目相关docs、repo和相关代码。
- 梳理当前已有文件编辑、工具调用、审批、trace 或 coding workflow 能力。
- 定义一次安全文件编辑任务的输入、边界、步骤和输出。
- 定义 diff 摘要、验证结果、失败反馈、人工确认点。
- 判断 Mission 02B 是否需要代码修改，以及可能涉及哪些模块。

交付物：

`solo-workdocs/mission-docs/06-mission-02A-safe-file-edit-research-and-design.md`

不做什么：

- 不直接开发文件编辑功能。
- 不修改 runtime/tooling 核心代码。
- 不添加依赖。
- 不接入三方 API。
- 不运行安装命令。
- 不提交 commit。

验收标准：

- 完成本项目现状调研；
- 完成成熟项目对标矩阵；
- 明确 Mission 02B 最小实现范围；
- 明确本阶段不做什么；
- 明确安全边界；
- 明确测试计划；
- 拆出后续实现任务；
- 不修改核心源码；
- 不添加依赖；
- 不运行安装命令；
- 不提交 commit。

完成定义：

用户确认 Mission 02A 的设计后，才进入 Mission 02B 的实现规划或代码开发。
