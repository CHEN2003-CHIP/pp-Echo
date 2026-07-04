# AGENTS.md

## 项目定位

pp-Echo 是一个本地优先的 Agent runtime 与工作台。它协调 model provider、AgentRuntime、tools、MCP、skills、memory、bots、traces 和 evals，让 agent 可以在用户工作区内以可审计方式工作。

当前仓库不是单纯聊天 UI，而是面向个人开发者和小团队的 Coding Agent 与通用助手基础设施。修改时必须尊重 model、runtime、tools、capability governance、memory、extensions、bots、observability、evals 的边界。

## 当前阶段

当前优先级是建立 Solo AI-native 工作流，让项目从学习项目进入产品化推进状态。

除非用户明确要求，本阶段不要擅自开发 Agent 功能、重构核心代码、添加依赖、接入三方 API、运行安装命令或执行危险 shell 命令。

## 工作模式

- 使用 Mission -> Task -> Check 的轻量工作流。
- 每次任务先确认目标、边界、验收标准，再动手。
- 默认小步推进，优先做可审查、可回滚、可验证的改动。
- 对一人团队友好：文档要短、清晰、可执行。
- 发现范围变大时，先写入风险或决策记录，再请求用户确认。

## 项目管理文档规则

- Solo AI-native 工作流文档统一放在 `solo-workdocs/`。
- 不要把 Solo AI-native 工作流、Mission、Roadmap、风险、复盘写进 `docs/`。
- 如果未来存在或继续使用 `docs/`，它主要用于传统技术文档、架构说明、用户文档和 API 文档。
- `solo-workdocs/` 用于个人研发管理、Mission、Roadmap、风险、决策和发布复盘。
- `AGENTS.md` 必须保留在项目根目录，因为它是后续 Codex/AI Agent 进入仓库后的第一协作规则入口。

## 不要做什么

- 不要在没有明确请求时修改核心业务逻辑。
- 不要为了整理文档顺手重构代码。
- 不要添加依赖、升级依赖或运行安装命令。
- 不要接入第三方 API、云服务或外部系统。
- 不要移动、删除、覆盖 `docs/` 中已有内容。
- 不要提交 commit，除非用户明确要求。
- 不要把 secrets、tokens、完整 prompts、凭据或敏感文件内容写入文档、trace、metadata 或 project map。
- 不要把 MCP、skills、bots 或 capabilities 做成替代 AgentRuntime 的执行入口。

## 修改代码前的规则

始终先读：

- `AGENTS.md`
- `.pp-echo/project-map.json`
- 可能编辑模块最近的 `MODULE.md`
- 与任务相关的 ADR

涉及 runtime/session/tooling 时，再读：

- `src/pp_agent/app/bootstrap.py`
- `src/pp_agent/runtime/runtime.py`
- `src/pp_agent/runtime/lifecycle.py`
- `src/pp_agent/runtime/tool_surface.py`
- `src/pp_agent/tools/registry.py`

涉及 model/provider 时，再读：

- `src/pp_agent/llm/`
- `src/pp_agent/runtime/resolver.py`
- `docs/adr/0001-model-runtime-split.md`

涉及 memory 时，再读：

- `src/pp_agent/memory/`
- `src/pp_agent/learning/`
- `docs/adr/0002-memory-governance.md`

涉及 capability/tool/MCP/skill/bot 时，再读：

- `src/pp_agent/capabilities/`
- `src/pp_agent/tools/`
- `src/pp_agent/mcp/`
- `src/pp_agent/skills/`
- `src/pp_agent/bots/`
- `docs/adr/0003-capability-governance.md`

## 文档优先规则

- 当任务目标不清楚，先更新 Mission、Decision 或 Risk，不直接改代码。
- 当变更会影响架构边界，先写短 ADR，再实现。
- 当实现和文档冲突，以可运行代码和 doctor/report 为准，同时补齐文档差异。
- Runtime readiness 以 doctor/report 为准；公开文档和示例应引用 doctor/report，不使用临时口头判断。

## 测试和验收规则

- 修改代码时，先运行 touched module 的 focused tests。
- Runtime 状态相关改动，使用 `python -m pp_agent.cli.main workflow doctor --json` 作为 readiness gate。
- Web 类型改动，在 `web/` 中运行 `npx tsc --noEmit`。
- 不为了让测试通过做大范围无关格式化或重写。
- 只改文档时，可用人工 review 作为验收，并说明未运行代码测试。

## 安全边界

- Shell 操作默认最小化，优先只读命令。
- 不执行危险命令，例如递归删除、强制 reset、批量移动、未知脚本。
- 不运行安装命令，除非用户明确要求。
- 不访问网络或外部 API，除非任务明确需要并获得许可。
- 涉及文件写入时，只写任务指定文件或明确相关文件。

## 每次任务结束时的输出格式

任务结束后输出：

1. Summary：完成了什么。
2. Files Changed：新增/修改的文件。
3. Verification：如何检查，已运行哪些验证。
4. Risks：剩余风险或未验证点。
5. Next Step：建议下一步。
6. Need Human Review：需要用户确认的地方。

如果完成了 git stage、commit、branch、push 或 PR，再按 Codex app 要求输出对应 directive。未执行这些操作时不要输出 directive。
