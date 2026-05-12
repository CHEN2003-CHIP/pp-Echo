# pp-Echo Interview Evaluation Demo

This demo is designed for a short, stable interview walkthrough. It uses a small eval set that covers direct answers, repository awareness, tool use, Git awareness, safety, and approval protection.

## Run the Demo

```powershell
cd "E:\Pycharm Project\pp-Echo"
$env:PP_AGENT_HTTP_TRUST_ENV="0"

python -m pp_agent.cli.main eval run example-interview-eval-cases.json --workspace "E:\Pycharm Project\pp-Echo" --preflight --stop-on-failure
python -m pp_agent.cli.main eval report --workspace "E:\Pycharm Project\pp-Echo"
```

## What to Show

- Overall pass rate proves the agent can complete the scripted interview scenarios.
- `metrics` shows provider requests, tool calls, tool errors, approvals, and average duration.
- `Tag Summary` groups results by capability, such as `tool_use`, `repo_awareness`, `git_awareness`, `safety`, and `approval`.
- Infrastructure failures, such as network or provider errors, are counted separately from behavior assertion failures.

## Datasets

- `example-eval-cases.json` is the minimal smoke suite.
- `example-interview-eval-cases.json` is the interview demo suite.
- `example-memory-recall-eval-cases.json` is the slower long-term recall suite for preference, fix, path/command, dedup, and session-diversity checks.

## Memory Recall Eval

Run this separately from the interview demo when you want to inspect long-term recall behavior:

```powershell
python -m pp_agent.cli.main eval run example-memory-recall-eval-cases.json --workspace "E:\Pycharm Project\pp-Echo" --preflight --stop-on-failure
python -m pp_agent.cli.main eval report --workspace "E:\Pycharm Project\pp-Echo"
```

The report metrics include recall event count, recalled chunk count, and recall categories when memory recall is active.

Keep the interview suite small and deterministic. Avoid adding MCP, subagent, or safe rewind cases to the default demo unless the local environment is prepared for them.
