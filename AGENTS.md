# AGENTS.md

## Project intent
pp-Echo is a lightweight personal safe coding agent.
Prioritize trustworthiness through explicit boundaries, auditability, and reversibility.
Do not introduce heavyweight infrastructure unless required.

## Safety model goals
- File tools are policy-first.
- Shell execution is sandbox-first in architecture, even if the current phase only prepares for it.
- Approvals must eventually bind to exact actions, not vague session trust.

## Current implementation priorities
When changing code related to safety:
1. Prefer explicit allow / ask / deny policy decisions.
2. Treat these as protected paths unless the task explicitly says otherwise:
   - .pp-agent/**
   - .git/**
   - .env
   - .env.*
   - *.pem
   - *.key
3. Do not add model-reachable bypasses for sensitive mutations.
4. Keep changes small, testable, and reviewable.
5. Update docs when behavior changes.

## Working style
- Inspect first, then propose a short plan, then edit.
- Favor minimal coherent patches over broad rewrites.
- Add or update tests for every boundary change.
- Explain tradeoffs briefly in the final summary.

## Validation
Always run relevant tests for modified code.
If no suitable automated tests exist, add focused tests or provide manual verification steps.

## Non-goals for routine tasks
- Do not add a heavy container-based sandbox by default.
- Do not redesign unrelated planner features unless required by the task.
- Do not broaden permissions just to make tests pass.