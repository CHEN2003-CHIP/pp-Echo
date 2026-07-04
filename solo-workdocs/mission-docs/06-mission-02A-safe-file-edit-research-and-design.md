# Mission 02A：安全文件编辑闭环调研与设计

## 1. Mission 目标

为 pp-Echo 设计一个安全、可回滚、可审查、适合一人团队推进的文件编辑闭环。

本阶段只做现状调研、成熟项目对标和轻量设计，不开发功能代码，不修改核心源码，不运行项目，不运行测试，不提交 commit。

## 2. 本项目当前现状

调研方式：只读检查，包括阅读治理文档、`.pp-echo/project-map.json`、相关 `MODULE.md`、源码文件名、源码内容、`rg` 搜索、`git status`、`git log`。

### 已确认能力

| 能力 | 当前状态 | 主要位置 | 说明 |
| --- | --- | --- | --- |
| 文件读取 | 已有 | `src/pp_agent/tools/file_tools.py` | `ReadFileTool` 支持受限文本读取、`max_chars`、`offset` 和截断提示。 |
| 文件写入 | 已有但需收敛 | `src/pp_agent/tools/file_tools.py` | `WriteFileTool` 先 stage，不直接写盘，等待 approval token。 |
| 文件编辑 | 已有但需收敛 | `src/pp_agent/tools/file_tools.py` | `EditFileTool` 支持 SEARCH/REPLACE 或 unified diff，先 stage。 |
| diff preview | 已有 | `src/pp_agent/tools/file_tools.py` | `WriteFileTool` / `EditFileTool` 生成 unified diff；`PreviewPendingActionTool` 可预览 staged action。 |
| patch candidate | 已有 | `src/pp_agent/tools/file_tools.py`、`src/pp_agent/sandbox/docker.py` | sandbox run 可产出 patch、changed_files、structured_changes，并 stage 为 `apply_patch_candidate`。 |
| approval | 已有 | `src/pp_agent/storage/approvals.py`、`src/pp_agent/tools/file_tools.py` | pending action、approval grant、reject、consume、digest 校验已存在。 |
| tool registry | 已有 | `src/pp_agent/tools/registry.py` | 统一注册工具、权限域、确认策略、动态工具 effect 分析。 |
| shell tool | 已有 | `src/pp_agent/tools/shell_tool.py` | shell 命令先 stage；执行通过 sandbox executor。 |
| audit log | 部分已有 | `src/pp_agent/storage/approvals.py` | pending action lifecycle 写 audit record，但还不是完整编辑审计模型。 |
| session trace | 已有 | `src/pp_agent/observability/`、`src/pp_agent/tools/registry.py` | tool trace 输出会脱敏并记录 token hash、changed_paths、exit_code 等摘要。 |
| checkpoint | 已有但未嵌入单次编辑闭环 | `src/pp_agent/runtime/git_checkpoint.py`、`src/pp_agent/storage/checkpoints.py` | Git checkpoint 支持 HEAD/stash 快照和恢复。 |
| rollback | 部分已有 | `src/pp_agent/tools/file_tools.py`、`src/pp_agent/runtime/safe_rewind.py` | patch candidate apply 内部有 snapshot rollback；safe rewind 走 Git checkpoint。 |
| sandbox | 已有 | `src/pp_agent/sandbox/` | local/docker executor；docker 能隔离运行并收集 diff。 |
| workspace boundary | 已有 | `src/pp_agent/tools/policy.py`、`src/pp_agent/storage/files.py` | policy 拒绝 workspace 外路径；storage helper 也有 resolver。 |
| 敏感路径保护 | 已有但需统一 | `src/pp_agent/sandbox/changes.py`、`src/pp_agent/coding/scope.py` | `.env`、`.git`、`.pp-agent`、`*.pem`、`*.key` 等被识别为 protected/disallowed。 |
| 工具调用审批 | 已有 | `src/pp_agent/tools/policy.py`、`src/pp_agent/tools/registry.py` | edit/bash 默认 ask 或 requires_confirmation。 |
| 文件修改前后状态记录 | 部分已有 | `src/pp_agent/storage/approvals.py`、`src/pp_agent/tools/effects.py` | staged payload 有 before/after、effect、baseline digest；patch candidate 有 structured changes digest。 |

### 不确定或缺口

- 普通 `write_file` / `edit_file` 对大文件和二进制文件的防护不确定；当前读取/写入路径偏文本，二进制保护需要后续确认。
- `checkpoint before edit` 尚未明确绑定到每一次 approval 后 apply 前；现有 checkpoint 能力更像会话/回滚中心能力。
- `AuditLog` 还不是独立编辑审计对象；当前 audit record 偏 approval lifecycle 摘要。
- `Git checkpoint` 和 `patch candidate snapshot rollback` 是两条保护线，Mission 02B 需要明确优先级和组合方式。
- 多文件复杂事务已有部分 structured changes 检查，但本阶段应明确拒绝或限制。
- `apply_patch_candidate` 能处理 patch，但普通 `write_file/edit_file` 是否共享同一 rollback 语义需要后续确认。

## 3. 成熟项目对标

资料原则：只引用官方文档、官方仓库源码或项目主页能确认的内容；没有可靠来源的结论标“不确定/待补充”。本轮没有 clone 外部项目，也没有执行外部项目代码。

### OpenCode

参考来源：[OpenCode Permissions](https://opencode.ai/docs/permissions/)、[OpenCode edit tool source](https://raw.githubusercontent.com/sst/opencode/dev/packages/opencode/src/tool/edit.ts)、[OpenCode write tool source](https://raw.githubusercontent.com/sst/opencode/dev/packages/opencode/src/tool/write.ts)、[OpenCode read tool source](https://raw.githubusercontent.com/sst/opencode/dev/packages/opencode/src/tool/read.ts)、[OpenCode bash tool source](https://raw.githubusercontent.com/sst/opencode/dev/packages/opencode/src/tool/bash.ts)、[OpenCode permission service source](https://raw.githubusercontent.com/sst/opencode/dev/packages/opencode/src/permission/index.ts)、[OpenCode snapshot source](https://raw.githubusercontent.com/sst/opencode/dev/packages/opencode/src/snapshot/index.ts)、[OpenCode external directory guard source](https://raw.githubusercontent.com/sst/opencode/dev/packages/opencode/src/tool/external-directory.ts)。

已确认模式：

- 权限系统围绕 `permission + pattern + action` 组织，默认未匹配时走 ask。
- read/edit/write/bash 都可以通过 `ctx.ask(...)` 进入权限请求，而不是工具自行绕过用户确认。
- edit/write 在真正写入前生成 diff，并把 diff 放进 permission metadata。
- edit 使用 `oldString/newString`，要求 oldString 精确匹配；如果存在多处匹配或匹配过宽，会拒绝并要求补更多上下文。
- edit 对单文件加锁，避免同一文件并发修改。
- read 有行数、字节数和单行长度上限，并检测常见二进制文件；图片/PDF 走附件式返回。
- bash 对命令、workdir、timeout 建模，并对文件相关命令做 arity/路径分析。
- external directory guard 会检查目标是否在工作区内；访问外部目录时需要 `external_directory` 权限确认。
- snapshot 使用独立 gitdir 跟踪工作区状态，能生成 patch、diff、restore、revert；同时跳过 ignored 文件并限制大文件进入 snapshot。

可借鉴：

- 权限模型不要只按工具名判断，还要绑定 permission domain 和路径 pattern。
- diff 应作为 approval metadata 的一部分，而不是 apply 后才生成。
- edit/write/read/bash 都应共享同一套 permission request 语义。
- 文件编辑必须有单文件锁或 workspace apply lock，避免并发写入。
- read guard 和 edit guard 应分开：read 可以截断预览，edit 应拒绝大文件/二进制。
- checkpoint/snapshot 可以使用 Git 技术实现，但应使用隔离的安全层，不等同于自动 commit。
- external directory 应作为独立权限域，而不是普通 file path error。

不适合当前照搬：

- 完整权限 DSL、插件生态、LSP diagnostics、格式化联动、复杂 shell arity 分析都放 Later。
- OpenCode 的 snapshot 系统较完整，pp-Echo Mission 02B 先做单文件 checkpoint/apply/rollback，不直接照搬完整 snapshot subsystem。
- edit 的多种 fuzzy replacer 很强，但当前阶段 pp-Echo 应先使用严格 patch/diff，复杂纠错放 Later。

### OpenCode 对 pp-Echo 的优先借鉴结论

1. `ApprovalDecision` 应绑定 permission domain、path pattern、diff metadata 和 digest。
2. `DiffPreview` 应在写入前生成，并成为用户确认的核心内容。
3. `FileEditRequest` 应区分 workspace 内路径和 external directory，不要只在底层 path resolve 抛错。
4. `PatchProposal` 应支持“精确上下文失败即停止”，不要自动猜测用户意图。
5. `Checkpoint` 可以借鉴 OpenCode 的独立 snapshot 思路，但 Mission 02B 先做最小实现：单文件 snapshot + 可选 Git checkpoint。
6. `AuditLog` 应记录 permission request、decision、diff summary、apply result、rollback result，而不是只记录最终写入。
7. `ReadFileTool` 的截断和 binary guard 可以保留为 read 体验；edit/write 必须更严格。

### Cline

参考来源：[Cline Checkpoints](https://docs.cline.bot/features/checkpoints)、[Cline Plan and Act](https://docs.cline.bot/core-workflows/plan-and-act)、[Cline .clineignore](https://docs.cline.bot/exploring-clines-tools/clineignore)。

可借鉴：

- Plan / Act 分离适合 pp-Echo 的 Mission 02A -> 02B 节奏。
- Checkpoints 强调用户可恢复到任务过程中的状态。
- `.clineignore` 类机制可对应 pp-Echo 的 sensitive/disallowed path policy。

不适合当前照搬：

- IDE 插件体验、丰富 UI、自动化交互细节放 Later。

### Aider

参考来源：[Aider usage and watch mode](https://aider.chat/docs/usage/watch.html)。

可借鉴：

- 以 Git 工作区为用户可见变更事实来源。
- 编辑后让用户能通过 diff/commit/undo 思维审查。

不适合当前照搬：

- 自动 commit 或强依赖 Git 作为唯一安全机制不适合当前阶段；pp-Echo 需要 non-git safety guard。

### OpenHands

参考来源：[OpenHands Docs](https://docs.openhands.dev/)、[OpenHands llms.txt](https://docs.openhands.dev/llms.txt)。

可借鉴：

- 使用 runtime/sandbox 概念隔离 agent 执行环境。
- 将工具、运行环境、审计与用户任务分层。

不适合当前照搬：

- 完整云端/容器运行平台、复杂 runtime 编排放 Later。

### SWE-agent

参考来源：[SWE-agent Docs](https://swe-agent.com/latest/)。

可借鉴：

- 面向代码仓库任务，强调 agent 在受控环境中操作、观察和迭代。
- 适合作为后续 eval / benchmark 思路参考。

不适合当前照搬：

- Benchmark/competition 风格执行框架、批量任务自动化放 Later。

### Roo Code

参考来源：[Roo Code Docs](https://docs.roocode.com/)。

可借鉴：

- 作为 VS Code agent 类工具，重点关注用户确认、编辑可见性和工具权限。

不确定：

- 本轮未拿到足够细的官方页面来确认 checkpoint、rollback、sandbox 细节；需要后续人工补充。

### Continue

参考来源：待补充。

不确定：

- 本轮未拿到可靠官方资料，暂不写确定性结论。

## 4. 对标矩阵

| 项目 | 编辑入口 | diff/review | checkpoint/rollback | 权限模型 | sandbox | Git 集成 | 行为记录 | 对 pp-Echo 的借鉴 | 当前不适合照搬 | 参考来源或待补充 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| OpenCode | read/edit/write/bash 工具 | edit/write 写入前生成 diff 并进入 permission metadata | 独立 snapshot gitdir 支持 patch/diff/restore/revert | permission + pattern + allow/ask/deny；外部目录独立权限 | 不确定是否作为完整 OS sandbox；但有工作区/外部目录权限 guard | snapshot 使用 Git 技术但不等同用户仓库 commit | permission ask/reply 事件、tool metadata、snapshot patch | 优先借鉴 permission domain、diff-before-apply、single-file lock、snapshot-before-edit | Later：完整权限 DSL、LSP/format 联动、复杂 fuzzy edit、完整 snapshot subsystem | [Permissions](https://opencode.ai/docs/permissions/)、[edit](https://raw.githubusercontent.com/sst/opencode/dev/packages/opencode/src/tool/edit.ts)、[write](https://raw.githubusercontent.com/sst/opencode/dev/packages/opencode/src/tool/write.ts)、[snapshot](https://raw.githubusercontent.com/sst/opencode/dev/packages/opencode/src/snapshot/index.ts) |
| Cline | IDE agent 编辑 | 用户可见编辑审查 | 官方有 checkpoints | `.clineignore` 和模式控制可借鉴 | 不确定 | 不确定 | 不确定 | Plan/Act、checkpoint、ignore policy | Later：IDE 插件体验 | [Checkpoints](https://docs.cline.bot/features/checkpoints)、[Plan and Act](https://docs.cline.bot/core-workflows/plan-and-act)、[.clineignore](https://docs.cline.bot/exploring-clines-tools/clineignore) |
| Aider | 聊天驱动代码编辑 | 依赖 Git diff/用户审查 | Git undo/commit 相关能力需后续细读 | 不确定 | 不确定 | 强 Git 工作流 | 不确定 | Git 可作为可见变更层 | 不把 Git 当唯一安全机制；自动 commit 放 Later | [Aider watch mode](https://aider.chat/docs/usage/watch.html) |
| OpenHands | Agent runtime 工具操作 | 不确定 | 不确定 | runtime/tool 分层 | 官方文档强调 runtime/sandbox 方向 | 不确定 | 不确定 | runtime/sandbox 分层 | Later：完整平台化 runtime | [OpenHands Docs](https://docs.openhands.dev/)、[llms.txt](https://docs.openhands.dev/llms.txt) |
| SWE-agent | Agent 操作 repo | 不确定 | 不确定 | 不确定 | 受控环境方向 | 面向 repo task | trajectory/行为记录需后续确认 | 后续 eval/任务闭环参考 | Later：批量 benchmark 自动化 | [SWE-agent Docs](https://swe-agent.com/latest/) |
| Roo Code | VS Code agent 编辑 | 不确定 | 不确定 | 不确定 | 不确定 | 不确定 | 不确定 | 关注 IDE 中用户确认体验 | Later：IDE 插件 | [Roo Code Docs](https://docs.roocode.com/) |
| Continue | 待补充 | 待补充 | 待补充 | 待补充 | 待补充 | 待补充 | 待补充 | 待补充 | 待补充 | 待补充 |

## 5. 设计原则

1. 默认只读，写入必须确认。
2. 所有写入先生成 patch/diff。
3. 所有写入前创建 checkpoint。
4. 不允许修改 workspace 外文件。
5. 敏感文件默认拒绝。
6. 大文件和二进制文件不直接编辑。
7. patch 失败必须停止。
8. checkpoint 创建失败时不继续写入。
9. rollback 失败必须告警。
10. 所有编辑行为必须进入 audit log。
11. 不自动 commit。
12. Git 可以用于 diff/undo，但不能成为唯一安全机制。
13. 当前阶段不做 AST 级复杂编辑。
14. 当前阶段不做多文件复杂事务。
15. 当前阶段不做 IDE 插件和 GitHub PR 自动化。

## 6. 最小闭环范围

Mission 02B 最小实现范围：

- workspace boundary；
- sensitive file policy；
- large file / binary file guard；
- patch proposal；
- diff preview；
- approval decision；
- checkpoint before edit；
- apply patch；
- rollback；
- audit log；
- final summary。

## 7. 本阶段不做什么

- 不做 AST 级复杂编辑。
- 不做多 Agent。
- 不做 IDE 插件。
- 不做 GitHub PR。
- 不接入三方 API。
- 不做大规模重构。
- 不自动提交 commit。
- 不自动删除文件。
- 不自动安装依赖。
- 不做多文件复杂事务。
- 不做云端 sandbox。
- 不做团队权限后台。

## 8. 安全边界

- 写入只能发生在 workspace 内。
- `.env`、`.env.*`、`.git/**`、`.pp-agent/**`、`*.pem`、`*.key` 默认拒绝。
- 大文件默认拒绝或要求二次确认；建议 Mission 02B 先拒绝。
- 二进制文件默认拒绝。
- patch proposal 与 approval decision 必须绑定 digest。
- approval decision 必须绑定 permission domain、path pattern 和 diff metadata。
- approval 只对同一个 effect 生效，文件 baseline 改变则失效。
- checkpoint 创建失败时停止，不进入 apply。
- apply 失败时停止并报告，不尝试继续编辑其他文件。
- rollback 失败必须在 summary 和 audit log 中明确告警。
- 不自动 commit；Git 只作为可见 diff/恢复辅助。

## 9. 建议模块设计

### FileEditRequest

- 职责：表达用户允许范围内的一次文件编辑请求。
- 最小字段：`request_id`、`session_id`、`target_paths`、`intent`、`permission_domain`、`path_patterns`、`allowed_scope`、`created_at`。
- 由谁创建：Agent runtime 或 coding workflow 准备阶段。
- 什么时候创建：用户提出编辑请求并完成目标文件定位后。
- 失败时如何处理：目标不清或越界则停止，要求用户澄清。

### PatchProposal

- 职责：保存尚未写入磁盘的候选 patch。
- 最小字段：`proposal_id`、`request_id`、`target_paths`、`patch`、`patch_digest`、`baseline_digest`、`created_at`。
- 由谁创建：文件编辑工具或 patch proposal service。
- 什么时候创建：读取目标文件并生成编辑方案后。
- 失败时如何处理：生成失败或 baseline 不明则停止，不进入 approval。

### DiffPreview

- 职责：给用户审查的变更预览。
- 最小字段：`preview_id`、`proposal_id`、`changed_files`、`diff_text`、`truncated`、`risk_flags`、`permission_metadata`。
- 由谁创建：preview tool/service。
- 什么时候创建：PatchProposal 生成后、用户确认前。
- 失败时如何处理：diff 生成失败则不允许写入；过大或截断时要求二次确认或拒绝。

### ApprovalDecision

- 职责：记录用户是否批准本次 patch。
- 最小字段：`decision_id`、`proposal_id`、`approved`、`decided_by`、`decided_at`、`reason`、`proposal_digest`、`permission_domain`、`path_patterns`、`decision_scope`。
- 由谁创建：host approval flow。
- 什么时候创建：用户审查 DiffPreview 后。
- 失败时如何处理：无确认、拒绝或 digest 不匹配都停止。

### Checkpoint

- 职责：写入前保存可恢复状态。
- 最小字段：`checkpoint_id`、`request_id`、`target_paths`、`snapshot_type`、`baseline_digests`、`created_at`、`status`。
- 由谁创建：checkpoint manager。
- 什么时候创建：用户批准后、apply patch 前。
- 失败时如何处理：停止写入，记录 audit log。

### ApplyResult

- 职责：记录 patch 应用结果。
- 最小字段：`apply_id`、`proposal_id`、`checkpoint_id`、`applied`、`changed_paths`、`error`、`post_apply_digest`、`created_at`。
- 由谁创建：apply patch service/tool。
- 什么时候创建：apply patch 完成或失败时。
- 失败时如何处理：停止并进入 rollback 判断；不得继续后续文件。

### RollbackResult

- 职责：记录恢复结果。
- 最小字段：`rollback_id`、`checkpoint_id`、`requested_by`、`succeeded`、`restored_paths`、`error`、`created_at`。
- 由谁创建：rollback service。
- 什么时候创建：用户请求恢复，或 apply/post validation 失败需要自动恢复时。
- 失败时如何处理：明确告警，标记 partial state possible。

### AuditLog

- 职责：保存本次编辑的审计摘要。
- 最小字段：`event_id`、`request_id`、`event_type`、`target_paths`、`summary`、`decision`、`result`、`timestamp`、`risk_flags`。
- 由谁创建：每个关键节点的工具或 orchestration layer。
- 什么时候创建：request、proposal、preview、approval、checkpoint、apply、rollback、final summary 阶段。
- 失败时如何处理：audit 写入失败要在 summary 中告警；是否阻断 apply 需 Mission 02B 决策，建议 checkpoint/apply 前 audit 失败阻断。

## 10. 执行流程

1. 用户提出编辑请求。
2. Agent 定位目标文件。
3. 检查文件是否在 workspace 内。
4. 检查是否为敏感文件。
5. 检查文件大小。
6. 检查是否为二进制文件。
7. 生成 patch proposal。
8. 生成 diff preview。
9. 请求用户确认。
10. 用户拒绝时停止，不写入。
11. 用户确认后创建 checkpoint。
12. checkpoint 成功后 apply patch。
13. 验证文件状态。
14. 记录 audit log。
15. 输出 summary。
16. 如果 apply 失败，停止并报告。
17. 如果需要恢复，执行 rollback。
18. rollback 失败时明确告警。

## 11. 验收标准

- [ ] 正常文本文件修改成功。
- [ ] 未确认时不写入。
- [ ] 用户拒绝确认时不写入。
- [ ] workspace 外文件被拒绝。
- [ ] 敏感文件被拒绝。
- [ ] 大文件被拒绝或需要二次确认。
- [ ] 二进制文件被拒绝。
- [ ] patch 失败不会产生半写入。
- [ ] checkpoint 创建失败时不继续写入。
- [ ] apply patch 成功后能生成 summary。
- [ ] rollback 可以恢复。
- [ ] rollback 失败会明确告警。
- [ ] audit log 能记录编辑请求。
- [ ] audit log 能记录 diff 摘要。
- [ ] audit log 能记录确认结果。
- [ ] audit log 能记录 apply 结果。
- [ ] audit log 能记录 rollback 结果。
- [ ] 不自动 commit。
- [ ] 不修改核心源码之外的无关文件。

## 12. 测试计划

| 测试 | 测试目标 | 前置条件 | 操作 | 预期结果 | Mission 02B 必做 |
| --- | --- | --- | --- | --- | --- |
| 正常修改文本文件 | 验证最小成功路径 | workspace 内有小文本文件 | 生成 patch、确认、checkpoint、apply | 文件被修改，summary/audit 完整 | 是 |
| 拒绝修改 | 验证拒绝后无写入 | staged proposal 存在 | 用户拒绝 | 不写盘，audit 记录拒绝 | 是 |
| 未确认不写入 | 验证 approval gate | proposal 已生成 | 不调用 approve | 文件不变 | 是 |
| 修改 workspace 外文件 | 验证边界 | 输入绝对外部路径 | 发起编辑 | 拒绝 | 是 |
| 修改 `.env` | 验证敏感文件 | workspace 有 `.env` | 发起编辑 | 拒绝 | 是 |
| 修改密钥类文件 | 验证 secret policy | `test.key` 或 `test.pem` | 发起编辑 | 拒绝 | 是 |
| 修改大文件 | 验证大小保护 | 超过阈值文件 | 发起编辑 | 拒绝或二次确认；建议先拒绝 | 是 |
| 修改二进制文件 | 验证 binary guard | workspace 内二进制文件 | 发起编辑 | 拒绝 | 是 |
| patch 冲突 | 验证 patch fail stop | patch context 不匹配 | apply | apply 失败，不继续 | 是 |
| 多处匹配 old_text | 验证精确上下文 | 文件中有重复片段 | 发起 edit | 拒绝并要求更多上下文 | 是 |
| patch 目标文件已变化 | 验证 baseline digest | proposal 后手动变更文件 | approve/apply | approval invalidated 或 apply 拒绝 | 是 |
| checkpoint 失败 | 验证 checkpoint gate | 模拟 checkpoint manager 失败 | apply 前创建 checkpoint | 停止，不写入 | 是 |
| apply patch 失败 | 验证失败处理 | 模拟 apply error | apply | 停止并记录失败 | 是 |
| rollback 成功 | 验证恢复 | apply 后请求 rollback | rollback | 文件恢复 | 是 |
| rollback 失败 | 验证告警 | 模拟恢复异常 | rollback | 明确告警，partial state possible | 是 |
| audit log 写入 | 验证审计 | 正常/失败路径 | 执行流程 | 关键事件写入 | 是 |
| 多文件编辑暂不支持 | 验证范围限制 | proposal 涉及多文件 | 发起编辑 | 拒绝或要求拆分 | 是 |

## 13. 后续任务拆分

### 1. workspace boundary 和敏感文件策略

- 任务目标：统一 FileEditRequest 的 workspace 和 sensitive path 校验。
- 修改范围：优先 tools/policy 或新建轻量 helper；不直接改 runtime 主循环。
- 不做什么：不做 UI，不做 GitHub，不做多文件事务。
- 验收标准：workspace 外、`.env`、`.git`、`.pp-agent`、`*.pem`、`*.key` 被拒绝。
- 测试建议：workspace 外、敏感文件、普通文件。
- 风险：重复现有 policy 逻辑；应复用 `ToolPolicyEvaluator` / protected path。

### 2. 大文件和二进制文件保护

- 任务目标：在 proposal 前拒绝大文件和二进制文件。
- 修改范围：file edit guard 或 proposal service。
- 不做什么：不做二进制 patch。
- 验收标准：大文件/二进制不会进入 patch proposal。
- 测试建议：大文本、二进制、正常小文本。
- 风险：阈值过低影响正常使用，需要可配置但先保守。

### 3. PatchProposal 和 DiffPreview

- 任务目标：把候选变更和用户预览明确成对象。
- 修改范围：file tools 或新建 contracts/helper。
- 不做什么：不应用 patch。
- 验收标准：proposal 有 digest/baseline，preview 有 changed_files/truncated/risk_flags。
- 测试建议：新增、修改、patch context mismatch。
- 风险：与现有 pending action payload 重叠。

### 4. ApprovalDecision

- 任务目标：明确 approve/reject 记录、digest 绑定、permission domain 和 path pattern。
- 修改范围：`PendingActionStore` 或 approval flow。
- 不做什么：不改变用户交互 UI。
- 验收标准：拒绝不写入；digest mismatch 失效；permission/path scope 不匹配失效。
- 测试建议：approve、reject、baseline changed。
- 风险：破坏现有 pending action 兼容。

### 5. Checkpoint before edit

- 任务目标：approval 后、apply 前创建 checkpoint。
- 修改范围：apply orchestration；可能复用 `GitCheckpointManager`。
- 不做什么：不自动 commit。
- 验收标准：checkpoint 失败则不写入。
- 测试建议：checkpoint success/failure。
- 风险：Git checkpoint 对非 git workspace 支持不足，需要 fallback 决策。

### 5A. 单文件锁与并发保护

- 任务目标：防止同一文件在 proposal/apply 期间被并发修改。
- 修改范围：apply orchestration 或 file edit service。
- 不做什么：不做复杂多文件事务锁。
- 验收标准：同一文件同时 apply 时只有一个成功进入 apply；另一个明确失败或重试。
- 测试建议：模拟两个 proposal 同时修改同一文件。
- 风险：锁粒度过粗影响体验；锁粒度过细无法保护跨步骤 baseline。

### 6. ApplyPatch

- 任务目标：统一 apply patch 成功/失败结果。
- 修改范围：现有 apply patch candidate 路径或新增内部 service。
- 不做什么：不做 AST 编辑。
- 验收标准：patch 失败停止，不产生半写入。
- 测试建议：正常、冲突、目标变化。
- 风险：普通 write/edit 与 patch candidate 路径不一致。

### 7. Rollback

- 任务目标：提供可审计恢复结果。
- 修改范围：patch snapshot rollback 或 safe rewind adapter。
- 不做什么：不做复杂多文件事务。
- 验收标准：rollback 成功恢复；失败明确告警。
- 测试建议：rollback 成功/失败。
- 风险：Git rollback 与内部 snapshot rollback 语义冲突。

### 8. AuditLog

- 任务目标：记录 request、diff、approval、apply、rollback。
- 修改范围：pending action audit 或新建 edit audit adapter。
- 不做什么：不记录完整敏感文件内容。
- 验收标准：每个关键节点有摘要记录。
- 测试建议：正常、拒绝、失败、rollback。
- 风险：trace/audit 重复；需要保持 trace-safe。

### 9. 集成到现有 tool registry

- 任务目标：让安全编辑闭环通过 ToolRegistry 暴露和执行。
- 修改范围：`ToolRegistry` 注册和 metadata。
- 不做什么：不绕过 `ToolPolicyEvaluator`。
- 验收标准：模型只能通过受控工具触发写入。
- 测试建议：tool metadata、approval policy、read-only profile。
- 风险：动态工具或 MCP 工具绕过闭环，需要后续单独治理。

### 10. 补测试和文档

- 任务目标：覆盖 Mission 02B 必做路径。
- 修改范围：focused tests 和 solo-workdocs 更新。
- 不做什么：不做大范围测试重写。
- 验收标准：关键 checklist 有测试。
- 测试建议：按第 12 节。
- 风险：测试夹具可能需要模拟 checkpoint failure。

### 11. 手动 demo case

- 任务目标：用一个小文本文件演示完整闭环。
- 修改范围：demo 文档或临时工作区。
- 不做什么：不修改核心源码。
- 验收标准：能展示 request -> diff -> approval -> checkpoint -> apply -> summary -> rollback。
- 测试建议：手动步骤记录。
- 风险：demo 不能替代自动测试。

## 14. 风险和应对策略

| 风险 | 等级 | 触发信号 | 应对策略 |
| --- | --- | --- | --- |
| 重复造安全策略 | 高 | 新增 helper 与 ToolPolicyEvaluator 逻辑冲突 | 优先复用现有 policy/protected path/scope contract |
| checkpoint 语义不清 | 高 | Git checkpoint 和内部 snapshot rollback 都能恢复 | Mission 02B 前明确优先级：先 checkpoint gate，再局部 apply rollback |
| audit log 泄露内容 | 高 | audit 记录完整 diff 或 secret 内容 | audit 只存摘要、digest、路径和状态；敏感路径默认拒绝 |
| 写入路径绕过 ToolRegistry | 高 | 某些工具直接写盘 | 写入必须经 ToolRegistry + approval + audit |
| permission 与 diff 脱钩 | 高 | 用户批准的是路径，但实际 apply 的 diff 已变 | approval 必须绑定 diff/proposal digest、permission domain 和 path pattern |
| 大文件/二进制处理不一致 | 中 | sandbox 标 truncated，但普通 edit 仍读写 | proposal 前统一 guard |
| Git 依赖过强 | 中 | 非 git workspace 无法编辑 | Git 作为增强安全层，不作为唯一机制；无 checkpoint 时停止或采用文件 snapshot |
| 多文件事务失控 | 中 | 一个 patch 修改多个模块 | Mission 02B 默认拒绝或限制 `max_files_changed=1` |

## 15. 需要人工确认的问题

- Mission 02B 是否要求支持非 Git workspace？如果支持，需要文件级 checkpoint fallback。
- 大文件阈值建议多少？初始建议 1MB 或沿用 sandbox `MAX_DIFF_FILE_BYTES`。
- Mission 02B 是否先只支持单文件？建议是。
- audit log 写入失败是否阻断 apply？建议 checkpoint/apply 前 audit 失败阻断。
- rollback 是优先使用 Git checkpoint，还是优先使用 apply 前文件 snapshot？建议两层：单文件 snapshot 用于 apply 失败原子性，Git checkpoint 用于用户级 rewind。
- 是否接受 Mission 02B 引入单文件锁？建议接受，先锁 target file，不做全 workspace 事务。

## 16. 参考来源或待补充来源

已查看：

- [OpenCode Permissions](https://opencode.ai/docs/permissions/)
- [OpenCode edit tool source](https://raw.githubusercontent.com/sst/opencode/dev/packages/opencode/src/tool/edit.ts)
- [OpenCode write tool source](https://raw.githubusercontent.com/sst/opencode/dev/packages/opencode/src/tool/write.ts)
- [OpenCode read tool source](https://raw.githubusercontent.com/sst/opencode/dev/packages/opencode/src/tool/read.ts)
- [OpenCode bash tool source](https://raw.githubusercontent.com/sst/opencode/dev/packages/opencode/src/tool/bash.ts)
- [OpenCode permission service source](https://raw.githubusercontent.com/sst/opencode/dev/packages/opencode/src/permission/index.ts)
- [OpenCode snapshot source](https://raw.githubusercontent.com/sst/opencode/dev/packages/opencode/src/snapshot/index.ts)
- [OpenCode external directory guard source](https://raw.githubusercontent.com/sst/opencode/dev/packages/opencode/src/tool/external-directory.ts)
- [Cline Checkpoints](https://docs.cline.bot/features/checkpoints)
- [Cline Plan and Act](https://docs.cline.bot/core-workflows/plan-and-act)
- [Cline .clineignore](https://docs.cline.bot/exploring-clines-tools/clineignore)
- [Aider watch mode](https://aider.chat/docs/usage/watch.html)
- [OpenHands Docs](https://docs.openhands.dev/)
- [OpenHands llms.txt](https://docs.openhands.dev/llms.txt)
- [SWE-agent Docs](https://swe-agent.com/latest/)
- [Roo Code Docs](https://docs.roocode.com/)

待补充：

- OpenCode 是否有更高层的 undo 用户文档和 sandbox 文档。
- Aider Git undo/auto commit 详细文档。
- OpenHands sandbox、trajectory、file edit 具体机制页面。
- SWE-agent environment/tools/trajectory 具体页面。
- Roo Code checkpoint/approval/diff 具体页面。
- Continue permissions、edit flow、diff review 官方资料。
