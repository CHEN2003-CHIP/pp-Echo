# 02 Missions

## Mission 08: Durable Workflow Recovery and Idempotent Resume

Status: Planning / authoritative design ready for human review; 08B/08C/08D-P/08D-S/08D-R/08D-T/08E implemented

Details:

- `solo-workdocs/mission-docs/18-mission-08-durable-workflow-recovery-design.md`
- `docs/adr/0004-coding-workflow-recovery-authority.md`

Goal:

Make the existing single-task controlled coding workflow recoverable across process exit, restart, pending approvals, pending tool actions, validation pending, repair pending, re-validation pending, repeated resume, repeated approval, and partially stale or inconsistent state.

Official direction:

- Workflow recovery checkpoint is owned by `src/pp_agent/coding`.
- `SessionStore` remains responsible for transcript, runtime/session snapshots, and generic durable message evidence only.
- `PendingActionStore` remains the only owner of staged action and approval lifecycle.
- Checkpoint stores safe pending action references only; it never copies approval state.
- `TraceStore` is diagnostic and is not a recovery fact source.
- Mission 07 `repair_attempted`, `revalidation_attempted`, validation execution count, and terminal outcome must become durable.
- Checkpoint must be versioned, atomic, bounded, and fail-closed.
- Recovery must inspect and reconcile first, then execute only by explicit request.
- No generic workflow engine, no full session format rewrite, and no OpenCode session, permission, or agent-loop framework port.

Planned tasks:

- 08A: architecture audit. Status: completed / ready for human review.
- 08A-D: targeted OpenCode comparison and authoritative durable recovery design. Status: design ready for human review.
- 08B: versioned coding workflow checkpoint contract. Status: implemented / ready for human review.
- 08C: atomic storage, revision/CAS, and read-only reconciliation. Status: implemented / ready for human review.
- 08D preflight: approval/tool-boundary resume audit. Status: stopped for human review because model continuation lacked a durable intent/correlation boundary.
- 08D-P: durable model continuation intent contract and checkpoint schema v2. Status: implemented / ready for human review.
- 08D-S: SessionStore/tool-result correlation evidence integration. Status: implemented / ready for human review.
- 08D-R: explicit approval/tool-boundary resume execution. Status: implemented / ready for human review.
- 08D-T: generic coding workflow terminal outcome and ordinary completion. Status: implemented / ready for human review.
- 08E: Mission 07 validation/repair recovery integration. Status: implemented / closeout ready.
- 08F: CLI inspect/resume/cancel.
- 08G: doctor, release gate, documentation, and closeout.

Non-goals:

- No production code in 08A-D.
- No test code in 08A-D.
- No checkpoint implementation in 08A-D.
- No session migration.
- No resume implementation in 08A-D.
- No CLI implementation in 08A-D.
- No database or new dependency.
- No generic workflow engine.
- No second approval store, second tool state, or second runtime loop.
- No OpenCode framework port.
- No Mission 07 semantic change.
- No Mission 09.

Hard stops:

- Stop for human review if Mission 08 requires a second approval store, second tool execution state, second runtime/model loop, generic workflow engine, database migration, full session format rewrite, approval token semantic change, Mission 07 runtime semantic change, new dependency, pickle, trace as sole authority, or unresolved checkpoint/session double authority.

08D-R implementation note:

- `src/pp_agent/coding.workflow_recovery` owns read-only inspection and explicit resume orchestration.
- Resume requires an expected checkpoint revision and uses checkpoint CAS before any model continuation attempt.
- One resume call may dispatch at most one existing runtime model continuation, with `stop_after_model_boundary=True`.
- Recovery never approves, rejects, or executes tools. New tool calls are staged by the existing runtime planner approval owner and then the resume call stops.
- If a continuation intent exists without SessionStore completion evidence, repeated resume fails closed and does not retry the model.
- SessionStore remains the only authority for durable external tool-result and model-continuation completion evidence.
- PendingActionStore remains the only authority for staged action and approval lifecycle.
- Mission 07 validation, repair, and re-validation recovery remain deferred to 08E.
- CLI and doctor integration remain deferred to 08F/08G.

08D-T implementation note:

- CHECKPOINT SCHEMA V1: FROZEN.
- CHECKPOINT SCHEMA V2: FROZEN.
- CHECKPOINT SCHEMA V3: GENERIC TERMINAL OUTCOME CAPABLE.
- `session_committed` is continuation completion evidence only; it is not workflow terminality.
- Workflow completion authority remains the `pp_agent.coding` checkpoint.
- Ordinary completion requires schema v3, exact SessionStore model-continuation completion evidence, typed ordinary terminal outcome, no active pending action, a completion marker, and checkpoint CAS.
- Completed checkpoint is immutable.
- V1/V2 checkpoints are not automatically migrated to v3.
- Validation terminal contract is defined, but Mission 07 validation/repair/re-validation recovery remains not implemented.
- CLI and doctor integration remain not implemented.

08E implementation note:

- Mission 07 validation/repair/re-validation recovery is implemented inside the coding-owned recovery layer.
- Initial validation staging writes schema v3 checkpoints and safe validation pending action references without executing pytest.
- Explicit resume interprets durable validation evidence, persists terminal validation outcomes for pass/blocked, and starts repair only from trusted pytest `tests_failed` evidence.
- Repair resume CAS-writes `repair_attempted=true` before one model continuation and stops at repair tool approval, repair completed, uncertain, or terminal blocked.
- Same-command revalidation resume stages one revalidation approval using the original selected logical command digest.
- Final revalidation interpretation persists schema v3 validation terminal outcomes with `validation_execution_count=2`.
- No second repair, no second revalidation, no schema migration, no runtime/session/CLI contract change, and no generic workflow engine were added.
- Technical debt TD-1: schema v3 does not allow `model_continuation_intent` to coexist with an active `pending_action_ref`; after repair continuation creates a repair-tool pending action, recovery uses `pending_action_ref(role=REPAIR_TOOL)` as the current recovery authority and does not retain the continuation intent in that checkpoint.
- Technical debt TD-2: `approve_staged_validation_cycle` remains as a compatibility alias, but it is now a pure interpretation wrapper; future cleanup may rename or remove it.

## Mission 07: Bounded Validation and Repair Loop

Status: Completed / ready for final human review

Details:

- `solo-workdocs/mission-docs/16-mission-07-bounded-validation-repair-loop-design.md`
- `solo-workdocs/mission-docs/17-mission-07-bounded-validation-repair-loop-closeout.md`

Goal:

Turn the existing non-executing `ValidationPlan` into a bounded, approval-gated validation feedback loop that can observe one pytest validation result, allow at most one repair continuation after a real test failure, re-run the same validation once, and finish with an explicit validated, failed, blocked, or approval-pending outcome.

Official direction:

- Mission 07 is a `NEXT PRODUCT CAPABILITY`, not a generic self-healing agent, generic planner, or autonomous infinite repair loop.
- 07A architecture discovery is completed. Its conclusion is that the largest current product gap is the missing bounded loop between `ValidationPlan`, approval-gated validation execution, bounded validation observation, one repair-or-stop decision, bounded re-validation, and explicit completion outcome.
- `NO PRE-MISSION HARDENING REQUIRED`: known technical debt and hardening items do not block Mission 07.
- First version supports pytest validation only, through the existing `ValidationPlan -> stage_test_command -> approval -> run_shell -> bounded shell result` path.
- Validation execution remains approval-gated. `approval_pending` is not validation failure and must not trigger repair.
- Execution or infrastructure failure is not test failure and must produce a blocked or equivalent non-repair outcome.
- First version allows `MAX_REPAIR_CONTINUATIONS = 1`, then one same-command re-validation attempt. No recursive repair and no configurable unbounded retries.
- Re-validation uses the same normalized validation command as the initial validation cycle.
- Validation and repair lifecycle belongs to the controlled coding workflow / controlled coding loop, not `ContextPipeline`, `ToolRegistry`, shell tools, provider layer, or Web UI.
- Mission 07 must reuse existing mechanisms and must not create a second shell executor, second approval system, second coding runtime, generic planner framework, or generic workflow engine.

Completed tasks:

- 07A: architecture inventory and scope decision. Status: completed.
- 07B: validation observation and outcome contracts. Status: completed.
- 07C: approval-gated validation execution integration. Status: completed.
- 07D-P: structured pytest provenance foundation. Status: completed.
- 07D-R: one bounded repair continuation and same-command re-validation. Status: completed.
- 07E: CLI exposure, explainability, release gate, and closeout. Status: completed.

Not done:

- No npm, pnpm, yarn, cargo, go test, CI, GitHub Actions, remote runners, or arbitrary shell validation in the first version.
- No model-invented validation commands outside `ValidationPlan`.
- No approval bypass, auto-approval, direct subprocess execution, or hidden validation commands.
- No full pytest parser, JUnit XML framework, custom pytest plugin, or plugin dependency.
- No automatic rollback by default.
- No persistence / resume, background worker, scheduled validation, or cross-process validation lifecycle.
- No generic planner, task DAG, multi-agent delegation, generic step scheduler, or Web redesign.
- No second model loop, second shell executor, second approval system, ContextPipeline rewrite, Web integration, or non-pytest validation surface.
- No stdout/stderr semantic parsing, exit-code-only repair trigger, auto approval, approval bypass, recursive repair, or third validation execution.

## Mission 06: Scoped Repository Instructions

Status: Completed / ready for human merge review

Details:

- `solo-workdocs/mission-docs/14-mission-06-scoped-repository-instructions-design.md`
- `solo-workdocs/mission-docs/15-mission-06-scoped-repository-instructions-closeout.md`

Goal:

Automatically resolve repository-local `AGENTS.md` and `CLAUDE.md` instructions relevant to concrete task/read paths, activate them lazily and safely, and deliver them only through the existing `ContextItem -> ContextPipeline -> ContextPack -> final_messages` path.

Official direction:

- Mission 05 remains the owner of `RepositorySummary` and root project instruction integration.
- Mission 06 owns scoped repository instruction discovery and activation for concrete nested task/read paths.
- First version uses Design B: `TaskScope` seed plus runtime `read_file` lazy activation.
- Same-directory precedence is `AGENTS.md` canonical, then `CLAUDE.md` compatibility fallback.
- Ancestor lookup is bounded O(directory depth), cumulative, deterministic, and non-recursive.
- Root project instruction ownership remains in the Mission 05 path; Mission 06 must not create a second root instruction path.
- Scoped instructions must enter the model only through `ContextItem(section="project_context")` and the existing `ContextPipeline`.
- No generic recursive scan, no raw prompt injection, no second provider-message path, and no session-global activation.

Completed:

- 06A: OpenCode source-level benchmark and scoped instruction semantics decision.
- 06B: `ScopedInstruction` contract and bounded resolver.
- 06C: scoped activation state and triggers.
- 06D: ContextPipeline integration, release gate, and closeout.

Not done:

- No edit trigger.
- No global, custom, or remote rules.
- No generic recursive scan.
- No session-global activation.
- No new context section.
- No second prompt/provider path.
- No new trace schema.
- No new ContextPipeline or budget engine.
- No dependency additions.

Carried forward:

- Resolver still reuses repository-summary collector private helpers; acceptable for Mission 06 MVP, but can be cleaned up later if collector ownership changes.
- Scoped instruction digest means bounded decoded canonical content digest, not full raw-file digest.
- Future support for edit-triggered activation, custom filenames, remote rules, or global policy should be scoped as a later Mission.

## Mission 05: Repository Summary Integration with Existing ContextPipeline

Status: Completed / ready for human merge review

Details:

- `solo-workdocs/mission-docs/12-mission-05-repository-summary-context-pipeline-design.md`
- `solo-workdocs/mission-docs/13-mission-05-repository-summary-context-pipeline-closeout.md`

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
