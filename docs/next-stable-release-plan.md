# pp-Echo 下一版成熟稳定化计划

## 目标

下一版不以新增 Agent 能力为目标，而是把现有 Runtime、Session、Tool、Approval、Memory、Trace、Web/CLI/API、Onboarding/Eval 收敛成可长期使用、可诊断、可升级的稳定基线。

稳定版完成后，项目应满足四个判断：

- 新用户能按一条主路径完成安装、onboard、doctor、eval、Web 启动。
- 开发者能从 doctor/report/trace 中判断系统是否健康，并获得明确下一步。
- 高风险动作都有可审计的 preview、digest、approval record、trace 证据。
- 后续大改可以依赖测试、eval、release gate 判断是否回归。

## 对标结论

- OpenClaw 的成熟方向集中在 security/safe defaults、setup reliability、first-run UX、doctor/onboard、远程暴露前检查和 bug/stability 优先级。
- Hermes 的成熟方向集中在 dashboard、background monitoring、security hardening、backup/import、debug report、lazy dependencies、session/profile 持久化和跨入口体验一致。
- pp-Echo 下一版应优先补齐“可维护性能力”，而不是扩展更多用户侧工具生态。

参考：

- https://github.com/openclaw/openclaw
- https://github.com/openclaw/openclaw/blob/main/VISION.md
- https://github.com/openclaw/openclaw/blob/main/docs/gateway/configuration-reference.md
- https://github.com/NousResearch/hermes-agent/releases

## 当前基线

已知状态：

- `workflow doctor --json` 为 `warning`，包含 pending action、active pending action、pending artifact、findings 和 pending config effects。
- `eval report` 最新记录为 2026-06-08 deterministic `100/100`，发布前必须重新生成。
- 核心测试曾通过：`runtime/tools/subagents/observability` 257 passed；`onboarding/storage/config/mcp/attachments` 109 passed。
- 已知真实不稳点：`tests/web/test_server.py::test_web_api_memory_status_search_and_read` 中 Web memory 搜索 `MEMORY.md` 返回空结果。
- readiness 以 `doctor`、`eval report`、focused/full tests、Web build 为准。

## 非目标

- 不新增用户侧 Agent 能力。
- 不新增插件市场、工具生态入口或新的多 Agent 调度模型。
- 不重构 `SessionHost`、`AgentRuntime`、`ToolRegistry` 的公共 API。
- 不把 pp-Echo 宣称为生产级系统 sandbox。
- 不为追求 UI 丰富度引入新的前端框架或重型依赖。

## Release Gate

下一版必须满足：

- `python -m pp_agent.cli.main workflow doctor --json` 为 `ok`，或仅剩 release notes 中明确解释、可复现、可接受的 warning。
- `python -m pp_agent.cli.main eval run --suite pp_echo_core --mode deterministic --cases 100` 通过。
- `python -m pp_agent.cli.main eval report --json` 显示 deterministic `100/100`，并写入 `evals/reports/latest.*`。
- `pytest tests -q` 通过；若因环境限制跳过，必须列出跳过原因和替代 focused tests。
- `cd web && npm run build` 通过。
- release checklist、README、Startup Guide、CLI onboard 的主路径一致。
- `.pp-agent` 状态维护操作默认 dry-run；任何实际修复都需要显式 `--apply` 或 API confirm。

## 阶段计划

### Phase 0：冻结与基线记录

目标：进入 feature freeze，固定当前真实问题列表。

交付：

- 更新 `docs/release-checklist.md`，加入稳定版 gate、失败处理和回滚说明。
- 运行并保存当前 `doctor --json`、focused tests、eval report、Web build 结果。
- 建立 `docs/stability-known-issues.md` 或 release issue，记录每个 warning 是否阻塞发布。
- 明确版本号、tag、release notes 模板。

验收：

- 每个 release blocker 都有 owner、状态、验证命令。
- release gate 中的命令能被复制执行。

### Phase 1：Doctor / Maintenance / State Hygiene

目标：doctor 从“报 warning”升级为“可诊断、可预览修复、可安全应用”。

交付：

- 扩展 `runtime.control_plane`，为 findings 增加 `severity`、`explanation`、`remediation`、`safe_to_auto_fix`、`affected_paths`。
- 新增维护入口：
  - CLI：`workflow doctor --fix --dry-run`
  - CLI：`workflow doctor --fix --apply`
  - API：可选 `/api/runtime/maintenance/preview`、`/api/runtime/maintenance/apply`
- 维护策略只处理明显失效状态：orphaned planner token、缺 session 的 patch artifact、缺 artifact 文件的 active action、长期 rejected/execution_failed/grant_invalidated 记录。
- 对 `.pp-agent` 增加 retention summary：sessions、traces、pending actions、artifacts 的数量、大小、最新时间、可归档状态。
- 所有 apply 前创建备份或可恢复记录。

验收：

- dry-run 不修改任何文件。
- apply 不会清理 active approval、当前 session、仍存在 artifact 文件的 pending action。
- doctor JSON 旧字段兼容，新字段可选扩展。

### Phase 2：Memory 稳定化

目标：Web/CLI/API 使用同一套 memory 状态和搜索语义。

交付：

- 修复 Web memory 搜索 `MEMORY.md` 空结果。
- 抽出共享 service，避免 Web route 和 CLI 各自实现 indexing/search 判断。
- memory status 增加诊断：文件是否存在、索引是否存在、索引是否过期、embedding 是否关闭、query 是否过短、权限是否异常。
- 增加 focused tests：
  - Web 搜索 workspace `MEMORY.md`
  - CLI 搜索同一文件
  - 空召回返回原因
  - learning 写入失败只 warning，不中断主 turn
- memory eval 增加相关召回、过期记忆不注入、同 session 去重、top-k/token budget。

验收：

- `pytest tests/web/test_server.py::test_web_api_memory_status_search_and_read -q` 通过。
- CLI/Web/API 搜索同一个 workspace memory 返回一致路径和摘要。

### Phase 3：Session / History / Storage

目标：长期使用后 session、trace、artifact 不膨胀到不可诊断。

交付：

- `SessionStore` 增加只读结构健康检查：损坏 JSON/JSONL、缺 snapshot、active_head 指向不存在节点、turn tree 断链、session 数量过大。
- 历史列表默认分页/限量，避免 100+ sessions 时 Web/API/doctor 输出过长。
- repair preview 列出可修复项；apply 必须备份原文件。
- `.pp-agent` retention policy 文档化：默认不删除用户数据，只提示可归档项。
- trace/session/artifact size 纳入 doctor summary。

验收：

- 损坏样本不会让 session list 或 doctor 崩溃。
- Web sessions API 在大量 session 下仍返回轻量摘要。

### Phase 4：Tool / Approval / Safety

目标：所有高风险动作都能被稳定表达、审批、追踪和拒绝重放。

交付：

- 审计 `ToolRegistry` 真实注册名，生成工具 inventory，确保 allowlist/denylist 使用真实工具名。
- 高风险工具统一要求 exact-effect preview、payload_digest、changed_paths/target_path、approval record、trace span。
- 动态工具、MCP、Browser、extension 统一风险分类：`inspect`、`workspace_mutation`、`external_mutation`、`networked`、`destructive`。
- 增加 regression：
  - digest mismatch 禁止执行
  - shell 参数变化触发 mismatch
  - protected path 拒绝
  - approval token 重放失败
  - tool failure 后 final answer 有诊断，不假装成功
- Browser doctor 纳入 runtime report，但不得让浏览器缺失阻塞纯 CLI release gate。

验收：

- 所有写文件、shell、safe rewind、patch artifact apply 都有可验证 approval 链。
- subagent profile 的工具 allowlist 与真实注册名一致。

### Phase 5：Multi-Agent / Subagent

目标：冻结新能力，稳定已有 `spawn_subagent` / `orchestrate_agents`。

交付：

- 明确 subagent capability contract：工具 allowlist、workspace mode、MCP policy、turn limit、timeout、取消传播。
- `code_change` 工作流必须产出 patch artifact；无 artifact 必须返回 orchestration failure。
- 主 agent 不应在 subagent 失败后静默 fallback 直接修改 workspace。
- failure-mode tests 覆盖：部分成功、全部失败、timeout、取消、invalid summary、无 patch artifact、worktree 不可用、prior manifest 注入不执行。

验收：

- `pytest tests/subagents -q` 通过。
- 每种 failure 都有结构化错误和 trace 证据。

### Phase 6：Trace / Observability / Debug Report

目标：出了问题能打包、定位、复现。

交付：

- Trace schema 加兼容性测试，确保 TraceInspect、summary、diagnosis 不依赖易变字段。
- 增加 trace retention/export：按日期、大小统计；导出失败 run bundle。
- Diagnosis 增强：memory 空召回、approval pending、tool error 后仍 final answer、context/token 过大、artifact 丢失、policy blocked、config pending effects。
- Eval 消费 trace summary，至少检查工具轨迹、审批链、safety violation、memory recall 与 final answer 是否一致。
- 增加本地 debug bundle 命令或文档化手动打包路径，默认脱敏。

验收：

- 单个失败 run 可从 trace summary 定位到 tool/span/approval/artifact。
- debug bundle 不包含 API key、token、cookie、private key。

### Phase 7：Config / Onboarding / First-Run UX

目标：第一次启动路径足够短，配置错误足够清楚。

交付：

- 配置变更统一走 config manager；schema 改动必须有 migration 或清晰错误。
- Onboarding 与 doctor 使用同一套检查项命名、状态名、下一步建议。
- `pending_config_effects` 解释为 `next_turn`、`rebuild_runtime` 或 `restart_required`，并给出用户动作。
- README、Startup Guide、CLI onboard 只保留一条主路径：
  1. 安装依赖
  2. 配置 API key
  3. `onboard`
  4. `workflow doctor --json`
  5. deterministic eval
  6. 启动 Web/CLI
- start scripts 不应隐式吞掉依赖安装或 build 失败，失败时输出下一条可复制命令。

验收：

- 新用户按 README 主路径能跑到 doctor/report。
- onboard warning 不与 doctor status 互相矛盾。

### Phase 8：Web / CLI / API 一致性

目标：Web 只展示后端结构化状态，不复制业务判断。

交付：

- Web runtime report、memory、approvals、trace routes 共用后端 service 层。
- 前端不猜 pending/action/session 状态，只渲染后端 status、severity、next_actions。
- 对应 focused tests 覆盖 Web memory、runtime report、approvals、trace routes。
- 若修改前端，运行 `web/scripts/*.tests.cjs` 和 `npm run build`。

验收：

- CLI `workflow doctor --json` 与 Web `/api/runtime/report` 的关键 summary 一致。
- Web 页面在大量 sessions/pending actions 下不阻塞、不溢出、不丢失状态。

### Phase 9：Packaging / Install Size / Lazy Dependencies

目标：安装边界清楚，基础路径轻，重依赖按需安装。

交付：

- 审计 `pyproject.toml` extras，区分 core、web、attachments、qqbot、eval/dev。
- README 明确最小安装和完整安装命令。
- optional dependency 缺失时，doctor/onboard 给出可复制安装命令。
- Web build 与 Python package release 不互相隐式依赖。

验收：

- core CLI 不需要 PDF/DOCX/QQBot 等重依赖即可启动。
- 缺 optional dependency 时功能降级为 warning，不影响核心 doctor/eval。

### Phase 10：CI / Regression / Release

目标：把稳定版验证固定成自动化和 checklist。

交付：

- 建立或更新 CI workflow，至少覆盖：
  - `pytest tests/runtime tests/tools tests/subagents tests/observability -q`
  - `pytest tests/onboarding tests/storage tests/config tests/mcp tests/attachments -q`
  - `pytest tests/web tests/server tests/api tests/cli tests/smoke -q`
  - deterministic eval 100 cases
  - Web JS tests 和 build
- `scripts/check_release.py` 纳入 release gate。
- release notes 记录 doctor/report/test/eval/build 的最终结果。
- tag 前生成 debug/readiness bundle，保存在 release artifacts 或 docs 记录中。

验收：

- release checklist 每项都有命令、通过标准、失败处理。
- tag 前没有未解释 warning。

## Public Interfaces

保持兼容：

- 已有 CLI/API 字段不删除。
- doctor JSON 可新增字段，但旧字段保持兼容。
- Web route 可新增维护型端点，apply 必须显式确认。

建议新增：

- CLI：`workflow doctor --fix --dry-run`
- CLI：`workflow doctor --fix --apply`
- API：`/api/runtime/maintenance/preview`
- API：`/api/runtime/maintenance/apply`
- Report fields：`remediation`、`retention`、`storage`、`trace_store`、`debug_bundle`

## 测试矩阵

Focused first：

```powershell
pytest tests/runtime tests/tools tests/subagents tests/observability -q
pytest tests/onboarding tests/storage tests/config tests/mcp tests/attachments -q
pytest tests/web/test_server.py::test_web_api_memory_status_search_and_read -q
```

Integration：

```powershell
pytest tests/web tests/server tests/api tests/cli tests/smoke tests/tui tests/browser tests/evaluation tests/evals tests/benchmarks -q
pytest tests -q
```

Readiness：

```powershell
python -m pp_agent.cli.main onboard --json
python -m pp_agent.cli.main workflow doctor --json
python -m pp_agent.cli.main eval run --suite pp_echo_core --mode deterministic --cases 100
python -m pp_agent.cli.main eval report --json
```

Web：

```powershell
cd web
npm run build
node scripts/transcript.tests.cjs
node scripts/rich-text.tests.cjs
```

## 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| cleanup 误删用户状态 | 默认 dry-run；apply 前备份；只处理明确失效状态；测试覆盖 active 状态 |
| doctor 字段破坏 Web | 新字段 additive；旧字段兼容；Web 使用结构化 fallback |
| memory 修复引入重复索引 | service 层统一；加入去重和过期索引测试 |
| subagent 失败被主 agent 静默掩盖 | code_change 无 artifact 即失败；trace 记录 failure reason |
| optional 依赖阻塞 core | extras 分层；缺失只 warning；README 明确安装路径 |
| 全量测试过慢 | focused tests 先跑；CI 分组；release 前全量 |

## 推荐执行顺序

1. 修复 Web memory 已知失败，恢复绿色 focused test。
2. 扩展 doctor JSON 和 release checklist，建立 release gate。
3. 加 maintenance dry-run/apply 和 `.pp-agent` retention summary。
4. 做 Tool/Approval/Safety 审计和回归测试。
5. 稳定 Subagent failure mode。
6. 补 Trace debug bundle 和 diagnosis。
7. 收敛 Onboarding/README/Startup Guide。
8. 跑 full tests、eval、Web build，生成最终 report。

## 完成定义

下一版可以标记为成熟稳定版，当且仅当：

- release gate 全部通过。
- 所有 doctor warning 都有明确解释或已清理。
- 已知真实不稳点全部关闭。
- docs/release-checklist.md 与实际命令一致。
- release notes 包含测试、eval、doctor、Web build 的最终结果。
- 后续开发者能仅凭 doctor/report/trace/debug bundle 判断问题位置。
