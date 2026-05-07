# Subagent Validation Checklist

Use this checklist after subagent reliability changes to confirm the runtime still behaves predictably.

## Focused pytest

Run:

```powershell
pytest tests/subagents/test_failure_modes.py -q
pytest tests/subagents/test_result_parsing.py -q
pytest tests/subagents/test_manager.py -q
pytest tests/tools/test_subagent_tool.py -q
```

Recommended additional coverage:

```powershell
pytest tests/runtime/test_runtime.py -q -k "subagent or textual_tool_call"
```

## Manual chat checks

1. `@subagent 总结AGENTS.md`
- Expected: successful concise summary, not raw file content.

2. `@subagent 总结README.md`
- Expected on success: concise summary.
- Expected on provider empty-response path: clear failure explanation, not the full README text.

3. `@subagent 帮我审查当前工作区的改动，告诉我主要风险`
- Expected: routes through `change-reviewer` and returns a short risk summary.

4. `打开AGENTS.md`
- Expected: if the model emits prose followed by `read_file {...}`, the runtime promotes it into a real `read_file` tool call.

5. After a failed `@subagent`, immediately ask `为什么刚才失败？`
- Expected: the main agent explains the subagent failure and suggests retrying or switching to direct execution.
