# 03 Decisions

## ADR-003: Mission 03 Uses Proposal-Bound Shell Execution

Status: Accepted

Date: 2026-07-07

Context:

Mission 03 needs a safe MVP loop for shell/test execution without turning pp-Echo into an arbitrary shell relay. The existing `run_shell` path already stages commands for host approval and uses the sandbox executor; the missing product contract was what the user previews, approves, and receives after execution.

Decision:

- Keep `run_shell` as the single shell execution path.
- Add lightweight dict `command_proposal` and `command_preview` contracts.
- Bind approval to `command_proposal.proposal_digest`.
- Bind the proposal digest to the original command text, not only the normalized command.
- Use `normalized_command` only for display, comparison, and risk-analysis support.
- Recompute proposal digest immediately before execution and reject mismatches.
- Keep legacy shell pending actions without `command_proposal` as migration compatibility only.
- Return bounded stdout/stderr result previews with metadata.
- Use 8 KiB per stream as the v0.x default stdout/stderr preview limit.
- Add `stage_test_command` as a narrow pytest helper that delegates to `run_shell`.
- Keep pytest helper support limited to workspace-relative path targets; no node ids or extra args in MVP.
- Use `permissions_required == ["bash"]` as the public capability catalog contract for shell execution risk.

Rationale:

- Reusing `run_shell` avoids a second executor and keeps approval, digest verification, policy, and result normalization centralized.
- Original command text must be part of the approved proposal because that is what the user is authorizing.
- Bounded output prevents trace/context growth and reduces leakage from command output.
- A path-only pytest helper gives agents a safe way to recommend focused tests without accepting arbitrary shell syntax.

Impact:

- New staged `run_shell` actions must include `command_proposal`.
- Preview derives from proposal metadata.
- Approval after proposal tampering rejects execution.
- `stage_test_command` is model-callable but still requires the `run_shell` approval loop.
- Read-only profiles cannot use the test helper.

Follow-up checks:

- Decide whether package manager, git mutation, and network commands should become hard-deny or remain high-risk ask.
- Consider configuration for stdout/stderr preview limits.
- Design a separate allowlisted field before adding pytest node id support.
- Remove legacy shell pending fallback after a future schema/version migration.

## ADR-002：Mission 02B 采用单文件安全编辑闭环

状态：Accepted

日期：2026-07-05

背景：

Mission 02B 需要把普通 `write_file` / `edit_file` 从“能改文件”推进到“可预览、可批准、可校验、可 checkpoint、可手动 rollback”的产品化闭环。但 pp-Echo 仍处于 solo MVP 阶段，不适合过早抽象复杂 domain model 或多文件事务系统。

决策：

- 当前周期只做单文件安全编辑闭环。
- `patch_proposal` 暂时保持轻量 dict，不抽 dataclass / domain model。
- `diff_preview` 从 `patch_proposal` 派生。
- approval 绑定 `proposal_digest`，apply 前校验 proposal digest 和 baseline。
- v0.2 当前 checkpoint runtime storage 使用 `.pp-agent/pending-edits/file-checkpoints/`。该位置是当前实现约定，未来可随 retention、session storage、workspace state 设计演进迁移。
- `rollback_file_checkpoint` 保持 host-only，不暴露给模型普通 tool list。
- `rollback_file_checkpoint` 归入 approval execute/control capability。
- rollback status 保留 `restored` / `restored_absent` / `already_absent`。
- Windows newline 使用保真写读，不让平台自动转换 proposal/checkpoint 中的换行。

原因：

- 单文件闭环足够支撑当前 Coding Agent MVP 的第一版安全写盘体验。
- 轻量 dict 更符合当前 solo MVP 的维护成本。
- host-only rollback 避免模型直接触发恢复操作。
- newline 保真可以避免 Windows 平台下 digest/baseline 因换行转换产生误判。

影响：

- 多文件事务、Git rollback、自动 rollback、完整 audit log 延后。
- 后续如果 `patch_proposal` 字段继续增长，再考虑正式 contract / dataclass。
- checkpoint retention / cleanup policy 需要后续补齐。

后续检查点：

- Mission 03 前做一次 git diff review 和人工范围确认。
- 在支持 symlink 的环境补跑 symlink tests。
- 在进入更大范围功能前补一次全量或更大范围回归测试。

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
