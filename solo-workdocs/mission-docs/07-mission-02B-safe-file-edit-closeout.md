# Mission 02B：安全文件编辑闭环收口

日期：2026-07-05

状态：Completed / 待人工最终 review

## 1. Summary

Mission 02B 已形成最小单文件安全文件编辑闭环：

`stage -> preview -> approve -> digest/baseline check -> checkpoint -> write -> rollback`

本轮只覆盖普通 `write_file` / `edit_file` 路径，以及 worktree direct write/edit 的最小安全 guard。多文件事务、Git rollback、自动 rollback、完整 audit log、AST 编辑、IDE、GitHub PR 均未进入本 Mission。

## 2. What Changed

- `write_file` / `edit_file` 在 staged action 前增加安全 guard。
- guard 覆盖 workspace boundary、sensitive file policy、large file、binary/NUL、非 UTF-8、symlink、非普通文件。
- 大文件阈值第一版为 `1 MiB`。
- `write_file` 新建文件也限制 content size。
- `patch_proposal` 成为 staged edit 的 canonical source。
- `diff_preview` 从 `patch_proposal` 派生。
- approval 绑定 `proposal_digest`。
- apply 前校验 staged proposal digest 未变化。
- apply 前校验 baseline 未变化。
- apply 前创建单文件 checkpoint。
- v0.2 当前 checkpoint runtime storage 使用 `.pp-agent/pending-edits/file-checkpoints/`。该位置是当前实现约定，未来可随 retention、session storage、workspace state 设计演进迁移。
- 新增 host-only 工具 `rollback_file_checkpoint`，通过 `checkpoint_id` 手动恢复单文件。
- `rollback_file_checkpoint` 归入 approval execute/control capability，不暴露给模型普通 tool list。
- 修复 focused test 独立收集时的循环导入。
- 增加最小 e2e 验证。
- Windows newline 使用保真写读，不让平台自动转换 proposal/checkpoint 中的换行。

## 3. Safety Invariants

- preview 不写盘。
- approve 前不写盘。
- proposal digest mismatch 拒绝 apply。
- baseline changed 拒绝 apply。
- checkpoint 创建失败拒绝写盘。
- `rollback_file_checkpoint` 不对模型普通暴露。
- rollback 只能基于 `checkpoint_id`。
- rollback 拒绝 workspace 外路径、protected path、symlink、目录和非普通文件。
- `before_state=present` 时 rollback 恢复 checkpoint content。
- `before_state=absent` 时 rollback 删除当前普通文件；目标已不存在则返回 `already_absent`。
- 文本写盘保留 proposal/checkpoint 原始 newline。
- `.env`、`.env.*`、`.git/**`、`.pp-agent/**`、`*.pem`、`*.key` 默认拒绝。

## 4. Verification

- 02B-7 e2e tests：`3 passed`。
- 02B-1/2/3/4/5/6/7 focused 集合：`40 passed, 3 skipped`。
- worktree guard 独立测试：`1 passed`。

说明：

- skipped 原因：Windows symlink 创建权限/环境限制。
- pytest cache warning 不影响测试结果。
- 尚未运行全量测试。

## 5. Decisions

- `patch_proposal` 暂时保持轻量 dict，不抽 dataclass / domain model。
- v0.2 当前 checkpoint runtime storage 使用 `.pp-agent/pending-edits/file-checkpoints/`。该位置是当前实现约定，未来可随 retention、session storage、workspace state 设计演进迁移。
- `rollback_file_checkpoint` 保持 host-only。
- `rollback_file_checkpoint` 归入 approval execute/control capability。
- rollback status 保留 `restored` / `restored_absent` / `already_absent`。
- Windows newline 使用保真写读，不让平台自动转换换行。
- 当前周期只做单文件安全编辑闭环，多文件编辑放后续 Mission。

## 6. Risks / Follow-ups

- 尚未跑全量测试。
- symlink tests 需要在支持 symlink 的环境补跑。
- rollback 目前没有完整 audit log。
- checkpoint content 依赖 pending-edits 下文件存在。
- patch candidate 多文件路径仍使用原有写入方式。
- 动态 extension 直接写盘仍属于后续治理范围。
- 未来可能需要正式 `PatchProposal` contract / dataclass。
- 未来可能需要 checkpoint retention / cleanup policy。
- 未来需要补最小 rollback audit metadata。

## 7. Not Done

- 未做多文件事务。
- 未做 Git rollback。
- 未做自动 rollback。
- 未做完整 audit log 重构。
- 未做 checkpoint 存储位置重构。
- 未做 AST 编辑。
- 未做自动 commit。
- 未接三方 API。
- 未做 IDE。
- 未做 GitHub PR。
- 未进入 Mission 03。

## 8. Next Recommended Task

进入 Mission 03 前，建议先做：

- git diff review；
- 人工确认 02B 范围；
- 按主题拆分提交；
- 补一次全量或更大范围回归测试。
