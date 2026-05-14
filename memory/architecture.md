# Architecture

<!-- pp-echo-detail-memory:begin -->
### Subagent Orchestration and Reporting Pattern

When analyzing complex codebases, the recommended workflow is to spawn specialized subagents (memory-scout, repo-researcher, api-scout) via an orchestration tool. Each subagent targets a specific scope (architecture, workflows, API surface). The final step involves aggregating status, session IDs, and findings into a structured report before deciding on further actions like staged edits.

Evidence: The turn shows three distinct subagents assigned specific tasks (README, AGENTS, subagents), all returning success with unique session IDs. The assistant generated a summary table of their status and a consolidated conclusion.

Source: session=6306c941-e74e-42a8-aad6-06693f8429a2 turn=turn-1
<!-- pp-echo-detail-memory:end -->
