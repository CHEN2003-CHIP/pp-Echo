# pp-Echo Release Checklist

## 1. 安全检查

- [ ] `.env` 没有被 Git 跟踪。
- [ ] 如果项目需要环境变量，`.env.example` 已存在。
- [ ] 仓库中没有 API key、AccessKey、token、cookie 或 private key。
- [ ] `.gitignore` 已忽略本地 secret 文件。

## 2. 测试检查

- [ ] `pytest tests/observability -q`
- [ ] `pytest tests/onboarding -q`
- [ ] `pytest tests/server -q`
- [ ] `pytest tests -q`
- [ ] `python -m pp_agent.cli.main onboard --json`
- [ ] `python -m pp_agent.cli.main workflow doctor --json`
- [ ] `python -m pp_agent.cli.main eval run --suite pp_echo_core --mode deterministic --cases 100`
- [ ] `python -m pp_agent.cli.main eval report`
- [ ] `cd web && npm run build`

## 3. 手动 Smoke Test

- [ ] `start-web.bat` 可以打开 Web UI。
- [ ] 左上角 `pp-Echo` 可以打开 Startup Guide。
- [ ] TraceInspect 可以打开。
- [ ] 一个只读 prompt 可以运行。
- [ ] Approval panel 仍可使用。
- [ ] Trace 文件会写入 `.pp-agent/traces`。

## 4. 版本检查

- [ ] 如果包元数据支持版本号，版本为 `0.1.0a1`。
- [ ] Git tag 为 `v0.1.0-alpha.1`。
- [ ] Release notes 已准备好。

## 5. GitHub Release

- [ ] release preparation commit 已 push。
- [ ] annotated tag 已创建。
- [ ] tag 已 push。
- [ ] GitHub Release 已从 tag 创建。
- [ ] release notes 已粘贴。
- [ ] 已标记为 pre-release。
