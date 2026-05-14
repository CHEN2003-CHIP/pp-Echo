# Project Memory

<!-- pp-echo-memory:begin -->
## pp-Echo Bootstrap Memory

Short-lived prompt memory for durable preferences, project decisions, and navigation.
Use `memory_search` and `memory_get` for detailed notes in `memory/**/*.md`.

### Learned Notes
- **Subagent Output Format Specification**: All subagent responses must strictly follow a 5-section format: Summary, Findings, Recommended next action, Files/paths inspected, and Confidence. Markdown headers and numbering are automatically stripped during parsing.
  Evidence: AGENTS.md defines strict 5-section output format for all subagent responses with automatic parsing that strips Markdown headers and numbering.
  Source: session=8f8c9f46-a351-4a4d-bbb2-ad520f9812d1 turn=turn-1
- **Subagent Output Format Standard**: All subagent responses must strictly follow a 5-section format: Summary, Findings, Recommended next action, Files/paths inspected, and Confidence. Markdown heading syntax and numbering are automatically stripped during parsing. Outputs exceeding 2500 characters or missing required fields trigger an invalid_summary failure.
  Evidence: Agent Workflow section in findings; Constraints section in user prompt.
  Source: session=9abfdf73-d284-4650-b690-b55d85d7b17d turn=turn-1
- **Subagent Output Format Specification**: All subagents must return a structured summary with exactly five plain text sections: Summary, Findings, Recommended next action, Files/paths inspected, and Confidence. Markdown heading markers (e.g., #), code fences, and raw file dumps are strictly prohibited.
  Evidence: AGENTS.md specifies strict 5-section output format; SubagentManager normalizes output by stripping Markdown headings and numbering.
  Source: session=abcaba04-9664-4de8-b302-91d488c70e92 turn=turn-1
- **pp-Echo Parallel Analysis Protocol**: The pp-Echo project utilizes a parallel subagent orchestration system to analyze core modules (README.md, AGENTS.md, src/pp_agent/subagents) simultaneously. This workflow enforces read-only access by default to ensure safety during initial architectural mapping.
  Evidence: Tool 'orchestrate_agents' ran 3 subagents in parallel for read-only analysis of specific modules. The summary confirms 'Completed parallel read-only analysis' and 'local-first coding agent with a modular architecture supporting parallel subagent execution'.
  Source: session=6306c941-e74e-42a8-aad6-06693f8429a2 turn=turn-1
- **pp-Echo Bootstrap Memory Structure**: The project uses a dual-memory system: MEMORY.md (bootstrap) for short-lived preferences and decisions, and memory/**/*.md files for detailed notes accessed via memory_search/memory_get.
  Evidence: MEMORY.md header explicitly states 'Short-lived prompt memory... Use memory_search and memory_get for detailed notes in memory/**/*.md'.
  Source: session=6306c941-e74e-42a8-aad6-06693f8429a2 turn=turn-3
- **Response Style Preference**: User prefers concise and efficient responses.
  Evidence: User explicitly stated: '记住我的偏好，以后回答都是简洁高效' (Remember my preference, future answers should be concise and efficient).
  Source: session=6306c941-e74e-42a8-aad6-06693f8429a2 turn=turn-5
- **Concise and Efficient Responses**: The user prefers responses that are concise and efficient.
  Evidence: User instruction: '已记住偏好：以后回答保持简洁高效。'
  Source: session=6306c941-e74e-42a8-aad6-06693f8429a2 turn=turn-6

### Detailed Memory Index
- `memory/architecture.md` - Architecture
- `memory/bugs.md` - Bugs
- `memory/lessons.md` - Lessons
- `memory/workflows.md` - Workflows
<!-- pp-echo-memory:end -->
