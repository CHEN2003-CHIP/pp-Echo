# AGENTS.md

## Goal
Implement minimal, low-risk changes that fit the existing pp-Echo architecture.

## Codebase priorities
- Reuse SessionHost, AgentRuntime, and ToolRegistry
- Prefer small additive changes over refactors
- Keep public API stable

## Before coding
- Read runtime/session/tool registry code paths first
- Identify real tool names before wiring allowlists

## Testing
- Run focused tests first
- Add unit tests for new subagent modules
- Avoid broad unrelated changes
- readiness 以 doctor/report 为准

## Style
- Follow existing naming and module patterns
- Keep functions short and explicit
- Document architectural tradeoffs briefly
