# Project Context

The default pp-Echo agent should build a lightweight project context at session bootstrap.

It is a compact, workspace-local summary, not a full repo index.

Supported manifest files:

- `PP_ECHO.md`
- `AGENTS.md`
- `CLAUDE.md`

Load precedence:

1. `PP_ECHO.md`
2. `AGENTS.md`
3. `CLAUDE.md`

The loader skips protected paths such as `.env`, `.git`, `.pp-agent`, `node_modules`, caches, and build outputs.

The timeline layer exposes:

- `project_context`
- `manifest_loaded`

