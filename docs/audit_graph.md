# Audit Graph

An audit graph reconstructs a run from trace records. It does not re-run the
model or tools.

The replay foundation links:

`user.message -> memory.lookup/context item -> tool.policy -> tool.call/tool.result -> final.answer -> bot.delivery`

The graph builder emits stable `AuditNode`, `AuditEdge`, and `AuditWarning`
records. `AuditWarning.code` is the developer-facing contract surface; legacy
free-text violations are retained only for compatibility.

Current warning codes:

- `DUPLICATE_FINAL_ANSWER`
- `MISSING_TOOL_POLICY`
- `MISSING_PARENT_LINK`
- `UNBUDGETED_CONTEXT_ITEM`
- `UNRELATED_BOT_DELIVERY`
- `MISSING_RUN_LINK`

Every runtime path should be reconstructable enough to answer: what user message
started the run, what context and memory were used, what tool policy decided,
what tools ran, what final answer was produced, and how a bot/channel delivered
that answer.
