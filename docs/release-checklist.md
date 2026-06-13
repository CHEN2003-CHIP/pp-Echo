# pp-Echo Release Checklist

## 0. 稳定版 Gate

- [ ] 已阅读并更新 [`docs/next-stable-release-plan.md`](next-stable-release-plan.md) 中的当前基线和已知问题。
- [ ] 下一版处于 feature freeze：只接受稳定化、诊断、清理、测试和文档一致性改动。
- [ ] `workflow doctor --json` 为 `ok`，或 release notes 已解释所有剩余 warning。
- [ ] `evals/reports/latest.*` 已用本次发布 commit 重新生成。
- [ ] Web/CLI/API 的 readiness 结论一致；readiness 以 doctor/report 为准。
- [ ] 所有 cleanup/repair 类操作默认 dry-run；实际 apply 需要显式确认并可追溯。
- [ ] `python scripts/check_release.py --stable-gate` 通过；正式 tag 前运行 `python scripts/check_release.py --stable-gate --full`。

## 1. 安全检查

- [ ] `.env` 没有被 Git 跟踪。
- [ ] 如果项目需要环境变量，`.env.example` 已存在。
- [ ] 仓库中没有 API key、AccessKey、token、cookie 或 private key。
- [ ] `.gitignore` 已忽略本地 secret 文件。
- [ ] 高风险工具的 approval 记录包含 preview、digest、affected path 和 trace 证据。
- [ ] Debug/report/export 产物已确认脱敏，不包含 API key、token、cookie 或 private key。

## 2. 测试检查

- [ ] `pytest tests/runtime tests/tools tests/subagents tests/observability -q`
- [ ] `pytest tests/onboarding tests/storage tests/config tests/mcp tests/attachments -q`
- [ ] `pytest tests/web/test_server.py::test_web_api_memory_status_search_and_read -q`
- [ ] `pytest tests/observability -q`
- [ ] `pytest tests/onboarding -q`
- [ ] `pytest tests/server -q`
- [ ] `pytest tests -q`
- [ ] `python -m pp_agent.cli.main onboard --json`
- [ ] `python -m pp_agent.cli.main workflow doctor --json`
- [ ] `python -m pp_agent.cli.main eval run --suite pp_echo_core --mode deterministic --cases 100`
- [ ] `python -m pp_agent.cli.main eval report --json`
- [ ] `cd web && npm run build`
- [ ] `node web/scripts/transcript.tests.cjs`
- [ ] `node web/scripts/rich-text.tests.cjs`

## 3. 手动 Smoke Test

- [ ] `start-web.bat` 可以打开 Web UI。
- [ ] 左上角 `pp-Echo` 可以打开 Startup Guide。
- [ ] TraceInspect 可以打开。
- [ ] 一个只读 prompt 可以运行。
- [ ] Approval panel 仍可使用。
- [ ] Trace 文件会写入 `.pp-agent/traces`。
- [ ] Web `/api/runtime/report` 与 CLI `workflow doctor --json` 的关键 summary 一致。
- [ ] Web memory 搜索 `MEMORY.md` 能返回结果并可读取内容。

## 4. 版本检查

- [ ] 如果包元数据支持版本号，版本为 `0.1.0a1`。
- [ ] Git tag 为 `v0.1.0-alpha.1`。
- [ ] Release notes 已准备好。
- [ ] Release notes 包含 doctor、eval report、focused/full tests、Web build 的最终结果。
- [ ] Release notes 列出剩余非阻塞 warning 和原因。

## 5. GitHub Release

- [ ] release preparation commit 已 push。
- [ ] annotated tag 已创建。
- [ ] tag 已 push。
- [ ] GitHub Release 已从 tag 创建。
- [ ] release notes 已粘贴。
- [ ] 已标记为 pre-release。
