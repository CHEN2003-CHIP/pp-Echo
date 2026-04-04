# pp-Echo Benchmark Report

Generated: `2026-04-04T05:46:54Z`

## What was measured

This benchmark suite measures deterministic runtime behaviors that pp-Echo is designed to improve: planner approvals, safe rewind, session branching, MCP lazy activation, and long-context compaction.

## Test matrix

- Suite: `core`
- Tasks: `15`
- Modes: `pp-echo` vs internal baseline
- Model usage: deterministic fake LLM clients only
- Token numbers: normalized proxy estimates, not provider billing usage

## Headline results

- Planner approval blocked risky mutations before execution in 100% of gating tasks, while the internal baseline mutated immediately in 100%.
- Safe rewind recovered the requested workspace and conversation state in 100% of rewind tasks, versus 0% in the no-recovery baseline.
- Lazy MCP routing avoided 1.00 unnecessary server initializations per task on average while still activating the matched web-fetch path when needed.
- Context compaction reduced normalized prompt size by 44% on average in long-dialogue tasks.

## Metric table

| Metric | Value |
| --- | --- |
| `approval_block_rate_pp_echo` | `1.000` |
| `compaction_trigger_rate_pp_echo` | `1.000` |
| `context_size_reduction_ratio_pp_echo` | `0.439` |
| `mcp_match_activation_rate_pp_echo` | `1.000` |
| `mcp_unneeded_connection_count_baseline` | `1.000` |
| `mcp_unneeded_connection_count_pp_echo` | `0.000` |
| `proxy_context_tokens_baseline` | `4431.000` |
| `proxy_context_tokens_pp_echo` | `2485.000` |
| `rewind_restore_success_rate_baseline` | `0.000` |
| `rewind_restore_success_rate_pp_echo` | `1.000` |
| `session_branch_integrity_pp_echo` | `1.000` |
| `unsafe_write_before_approval_baseline` | `1.000` |

## Methodology

- Planner gating tasks compare `require_plan_approval=True` against a baseline with the gate disabled.
- Safe rewind tasks compare real rewind flows against a no-recovery baseline.
- MCP tasks compare lazy discovery against eager pre-discovery in the same fixture.
- Compaction tasks compare normal compaction against a baseline with compaction effectively disabled.
- Session branching tasks validate branch, rewind, and tree semantics with a deterministic local runtime.

## Limitations

- All results come from deterministic offline benchmark tasks in this repository.
- Token values are normalized proxy estimates based on message and tool payload size, not provider billing data.
