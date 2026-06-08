# pp-Echo Release Checklist

## 1. Security

- [ ] `.env` is not tracked.
- [ ] `.env.example` exists if environment variables are needed.
- [ ] No API keys, AccessKeys, tokens, cookies, or private keys are tracked.
- [ ] `.gitignore` ignores local secret files.

## 2. Tests

- [ ] `pytest tests/observability -q`
- [ ] `pytest tests/onboarding -q`
- [ ] `pytest tests/server -q`
- [ ] `pytest tests -q`
- [ ] `python -m pp_agent.cli.main onboard --json`
- [ ] `python -m pp_agent.cli.main workflow doctor --json`
- [ ] `python -m pp_agent.cli.main eval run --suite pp_echo_core --mode deterministic --cases 100`
- [ ] `python -m pp_agent.cli.main eval report`
- [ ] `cd web && npm run build`

## 3. Manual Smoke Test

- [ ] `start-web.bat` opens Web UI.
- [ ] Upper-left `pp-Echo` opens Startup Guide.
- [ ] TraceInspect opens.
- [ ] A read-only prompt can run.
- [ ] Approval panel still works.
- [ ] Trace files are written to `.pp-agent/traces`.

## 4. Version

- [ ] Version is set to `0.1.0a1` if package metadata supports it.
- [ ] Git tag is `v0.1.0-alpha.1`.
- [ ] Release notes are ready.

## 5. GitHub Release

- [ ] Push release preparation commit.
- [ ] Create annotated tag.
- [ ] Push tag.
- [ ] Draft GitHub Release from tag.
- [ ] Paste release notes.
- [ ] Mark as pre-release.
