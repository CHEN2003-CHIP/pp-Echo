# Multi-Agent Demo

pp-Echo supports an OpenClaw-style subagent orchestration demo through the `orchestrate_agents` tool.
Subagents run in forked sessions, use restricted tools, and return announce-style summaries to the parent agent.

## Research Demo

Ask in the web chat:

```text
并行分析文件型长期记忆模块的调用链、风险和可优化点。
```

Expected workflow: `memory-scout`, `repo-researcher`, and `api-scout` run in parallel.

## Debug Demo

Ask:

```text
并行定位为什么全量 pytest 在 test_catalog 冲突，并告诉我最小修复方案。
```

Expected workflow: `memory-scout`, `test-investigator`, and `change-reviewer` run in parallel.

## Staged Edit Demo

Ask explicitly:

```text
允许子 agent 生成 staged diff，但不要自动落盘。请修复 pytest test_catalog collection 冲突。
```

The orchestrator may run `code-worker` with `allow_edits=true`. The worker can only stage edits through
`edit_file` or `write_file`; it cannot call approval tools. Review generated tokens with
`preview_pending_action`, then approve selected tokens through the normal host approval flow.

## Safety Model

- Subagents are leaf workers and cannot spawn other subagents.
- `allow_edits=false` is the default.
- Editing subagents stage pending actions only; they do not write directly to disk.
- The parent agent receives summaries, findings, inspected paths, and staged tokens, not raw child transcripts.
