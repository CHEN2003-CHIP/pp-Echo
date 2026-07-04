# 01 Roadmap

12 周路线图用于给 Solo AI-native 推进定节奏。每周只追一个主目标。

## Week 1：建立 Solo AI-native 工作流

目标：建立项目治理脚手架。

范围：AGENTS、BOARD、PROMPTS、Vision、Roadmap、Mission、Decision、Risk、Release Log。

不做什么：不开发功能，不改核心代码，不加依赖。

验收标准：所有治理文件存在，内容能指导下一步 Mission。

## Week 2：安全文件编辑闭环

目标：让 Agent 文件修改具备明确范围、diff、确认和回滚思路。

范围：文件编辑策略、变更摘要、写入边界、人工确认点。

不做什么：不接入外部代码托管 API。

验收标准：一次文件修改任务能输出变更原因、文件列表、验证方式和剩余风险。

## Week 3：测试运行与失败反馈

目标：让 Agent 能运行 focused tests，并把失败反馈转成下一步行动。

范围：测试命令选择、失败摘要、最小修复建议、doctor/report 入口。

不做什么：不建立庞大 CI 系统。

验收标准：对指定模块能给出测试命令、结果摘要和失败处理建议。

## Week 4：Repo Scan 与项目摘要

目标：让 Agent 快速理解仓库结构、模块边界和风险区域。

范围：项目扫描、模块摘要、关键入口、不要触碰区域。

不做什么：不生成过长全量文档。

验收标准：能生成可读的项目摘要，并引用 AGENTS、project-map、MODULE。

## Week 5：Coding Agent MVP 串联

目标：串联理解、计划、编辑、测试、总结的最小闭环。

范围：单仓库、单任务、人工确认、可审查 diff。

不做什么：不做全自动长期任务执行。

验收标准：一个小功能或修复可以按 Mission -> Task -> Check 完成。

## Week 6：Eval 与回归测试

目标：为 Coding Agent MVP 建立基础回归信号。

范围：核心路径 eval、失败样例、回归报告。

不做什么：不追求复杂评分体系。

验收标准：关键能力有可重复检查方式。

## Week 7-10 滚动计划说明

Week 7-10 是滚动计划，不是硬切排期。若前一周闭环质量不足，优先延续修正，不为了赶路线图推进下一项。

Tool Connector、GitHub API、项目 Memory、Issue 到 PR 原型都必须在 Coding Agent MVP 稳定后再推进。稳定的含义是：文件编辑、测试反馈、人工确认和结果总结已经能在单任务中可靠闭环。

## Week 7：Tool Connector 抽象

目标：为未来外部系统操作建立轻量 connector 边界。

范围：connector 概念、权限、输入输出、错误处理。

不做什么：不立即接入多个真实第三方服务。

验收标准：connector 抽象不破坏 ToolRegistry 和 CapabilityPolicy。

## Week 8：GitHub API 接入

目标：接入 GitHub 的最小项目协作能力。

范围：Issue、branch、PR 的最小读写流程。

不做什么：不做完整 GitHub 客户端。

验收标准：能在安全边界内把 Issue 转成受控任务，并产出 PR 草稿。

## Week 9：项目 Memory 与 AGENTS.md

目标：让项目长期上下文能被保存、更新和审查。

范围：项目偏好、协作规则、常见任务、风险提醒。

不做什么：不保存 secrets 或完整敏感 prompt。

验收标准：Agent 能基于项目 Memory 和 AGENTS.md 更稳定地执行任务。

## Week 10：GitHub Issue 到 PR 原型

目标：完成从 Issue 到实现、测试、PR 摘要的原型链路。

范围：单 Issue、单分支、人工确认、PR draft。

不做什么：不全自动 merge。

验收标准：一个简单 Issue 可以转成可审查 PR。

## Week 11：CLI/TUI 体验优化

目标：优化个人开发者每天使用的入口体验。

范围：任务启动、状态显示、错误提示、结果摘要。

不做什么：不做大而全 Web UI。

验收标准：常用路径更短、更清楚、更少上下文切换。

## Week 12：v0.3 Beta 发布

目标：整理 Beta 能力边界并发布阶段成果。

范围：Release Log、已知问题、演示路径、下一阶段计划。

不做什么：不把未稳定能力包装成正式承诺。

验收标准：v0.3 Beta 有清晰能力、限制、安装/运行说明和下一步路线。
