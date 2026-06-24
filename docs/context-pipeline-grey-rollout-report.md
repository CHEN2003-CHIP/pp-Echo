# ContextPipeline Grey Rollout Report

## Test Scope

Deterministic local comparison cases covering memory, tools, attachments, capabilities, MCP, skills, workflow/subagent intent, and ordinary chat.

## Commands

- `python -m pp_agent.cli.main context compare-messages --json`
- `python -m pp_agent.cli.main context replay-trace --json`
- `python -m pp_agent.cli.main context grey-report --json`

## Summary

- Cases: 8
- Fallbacks predicted by diff checks: 0
- Quality regression: none detected by deterministic message-shape comparison
- Recommendation: keep default `on`; continue monitoring live trace replay for fallback spikes before broad release tagging.

## Case Results

### memory case

- Fallback reason: none
- Message count diff: 1
- Total char diff: 3407
- Dropped reasons: {"section_budget_exceeded": 1}
- Source refs: {"count": 3, "by_type": {"system": 1, "conversation": 1, "markdown_memory": 1}}

### tool selection case

- Fallback reason: none
- Message count diff: 1
- Total char diff: 3407
- Dropped reasons: {"section_budget_exceeded": 1}
- Source refs: {"count": 3, "by_type": {"system": 1, "conversation": 1, "markdown_memory": 1}}

### attachment case

- Fallback reason: none
- Message count diff: 1
- Total char diff: 3407
- Dropped reasons: {"section_budget_exceeded": 1}
- Source refs: {"count": 3, "by_type": {"system": 1, "conversation": 1, "markdown_memory": 1}}

### capability governance case

- Fallback reason: none
- Message count diff: 1
- Total char diff: 3407
- Dropped reasons: {"section_budget_exceeded": 1}
- Source refs: {"count": 3, "by_type": {"system": 1, "conversation": 1, "markdown_memory": 1}}

### MCP case

- Fallback reason: none
- Message count diff: 1
- Total char diff: 3407
- Dropped reasons: {"section_budget_exceeded": 1}
- Source refs: {"count": 3, "by_type": {"system": 1, "conversation": 1, "markdown_memory": 1}}

### skill case

- Fallback reason: none
- Message count diff: 1
- Total char diff: 3407
- Dropped reasons: {"section_budget_exceeded": 1}
- Source refs: {"count": 3, "by_type": {"system": 1, "conversation": 1, "markdown_memory": 1}}

### subagent or workflow case

- Fallback reason: none
- Message count diff: 1
- Total char diff: 3407
- Dropped reasons: {"section_budget_exceeded": 1}
- Source refs: {"count": 3, "by_type": {"system": 1, "conversation": 1, "markdown_memory": 1}}

### ordinary chat case

- Fallback reason: none
- Message count diff: 1
- Total char diff: 3407
- Dropped reasons: {"section_budget_exceeded": 1}
- Source refs: {"count": 3, "by_type": {"system": 1, "conversation": 1, "markdown_memory": 1}}

## TraceInspect Data

Trace payloads include `context_pack_v3`, `per_section_usage`, included/dropped items, source refs, markdown memory paths/hash, core governance status, MCP/Skill compact card summaries, `pipeline_mode`, and `fallback_reason`.
