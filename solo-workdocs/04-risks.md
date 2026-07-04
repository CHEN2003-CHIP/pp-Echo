# 04 Risks

风险清单用于提前发现失控信号。每周复盘时检查一次。

## 风险清单

| 风险 | 风险等级 | 触发信号 | 应对策略 |
| --- | --- | --- | --- |
| 项目范围失控 | 高 | 一个 Mission 同时包含多个大功能；任务不断追加但没有完成定义 | 每次只推进一个主 Mission；新增想法放 Later；先写 Won't Have |
| AI 生成代码不可维护 | 高 | 代码风格不一致；出现绕过现有模块边界的 helper；解释不清设计原因 | 先读 AGENTS、project-map、MODULE；小步 diff；要求 summary 和风险说明 |
| 未经审查合并 AI 代码 | 高 | AI 直接 commit 或用户未看 diff 就接受 | 默认不 commit；每次输出 Files Changed、Verification、Need Human Review |
| Shell/API 操作安全风险 | 高 | 运行安装命令、危险 shell、外部 API、未知脚本 | 默认只读；危险操作必须人工确认；不把 token 写入文档或 trace |
| 缺少测试导致回归 | 高 | 修改 runtime/tooling 后没有 focused tests；doctor/report 未检查 | touched module 先跑 focused tests；runtime readiness 使用 doctor/report |
| 过早做复杂多 Agent | 中 | 开始设计调度、自治队列、多个长期 agent，但单任务闭环还不稳定 | 先完成单 Agent Coding MVP；多 Agent 放 Later |
| 过早做 UI | 中 | 花大量时间做界面，但文件编辑、测试反馈还未闭环 | Week 11 前只做必要入口体验；优先 CLI/TUI 和工作流 |
| 文档和实现脱节 | 中 | 文档承诺能力但代码没有；Release Log 不更新 | 发布前检查实际命令和 doctor/report；Release Log 记录已知问题 |
| solo-workdocs/ 与项目技术文档混用导致混乱 | 中 | Mission、复盘写进 docs/；技术 ADR 写进 solo-workdocs/ 后无法被工程规则引用 | `solo-workdocs/` 管理个人研发；`docs/` 管传统技术文档和架构说明 |
| AGENTS.md 被 ignore 导致协作规则未进入版本管理 | 中 | `git status` 不显示 `AGENTS.md` 变更；新环境或协作者拿不到最新规则 | 明确 `AGENTS.md` 是本地规则还是版本化规则；若要版本化，调整 ignore 策略或使用明确的 git add 流程 |

## 每周检查问题

- 当前 Mission 是否仍然只有一个主目标？
- 是否有 AI 生成代码未经 review？
- 是否有测试或 doctor/report 被跳过？
- 是否有文档描述超过实际能力？
- `AGENTS.md` 是否仍能被后续 Agent 正确读取和追踪？
- 是否有新风险需要写入本文件？
