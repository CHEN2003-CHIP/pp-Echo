# pp-Echo Agent Evaluation Demo

This evaluation package is designed for an engineering-focused interview story:

> I did not only prepare a few demo prompts. I built a layered evaluation set for agent behavior: a small live demo suite, a 60-case main suite, deterministic runtime benchmarks, and an optional stress suite.

## Dataset Matrix

| Layer | File | Cases | Purpose |
| --- | --- | ---: | --- |
| Live interview demo | `example-interview-eval-cases.json` | 12 | Short, stable walkthrough for live interviews. |
| Main agent eval | `evals/datasets/agent-core-60.json` | 60 | Primary result set for real agent behavior. |
| Offline benchmark | `benchmarks/tasks/core.json` | 15 | Deterministic runtime benchmark with fake LLM clients. |
| Optional stress eval | `evals/datasets/agent-stress-10.json` | 10 | Slower or higher-risk scenarios for deeper validation. |

The full experimental matrix is **85 cases**: 60 main eval cases, 15 offline benchmark tasks, and 10 optional stress cases. The live interview path normally runs only the 12-case demo.

## Main Suite Breakdown

`evals/datasets/agent-core-60.json` is grouped by case id prefix:

| Prefix | Cases | Capability |
| --- | ---: | --- |
| `direct.` | 8 | Direct answers and tool restraint. |
| `repo.` | 12 | Repository understanding and code search. |
| `tool.` | 10 | Correct tool choice, parameters, and call discipline. |
| `safety.` | 10 | Secret protection, approval gates, and destructive-operation caution. |
| `collab.` | 8 | Git awareness, diff awareness, testing strategy, and scope control. |
| `memory.` | 6 | Preference, command, error-fix, dedup, and cross-session recall. |
| `chinese.` | 6 | Chinese technical explanation and interview-ready expression. |

Every case includes `metadata.capability`, `metadata.risk_level`, `metadata.demo_point`, `metadata.expected_tools`, and `metadata.interview_notes` so the result can be explained by capability, not only by pass rate.

## Run The Live Demo

```powershell
cd "E:\Pycharm Project\pp-Echo"
$env:PP_AGENT_HTTP_TRUST_ENV="0"

python -m pp_agent.cli.main eval run example-interview-eval-cases.json --workspace "E:\Pycharm Project\pp-Echo" --preflight --stop-on-failure
python -m pp_agent.cli.main eval report --workspace "E:\Pycharm Project\pp-Echo"
```

Show:

- Overall pass rate for the 12 scripted interview scenarios.
- `Tag Summary` for `tool_use`, `repo_awareness`, `git_awareness`, `safety`, `approval`, and `subagent`.
- `metrics` for provider requests, tool calls, tool errors, approval count, recall events, and average duration.
- Infrastructure failures counted separately from behavior assertion failures.

## Run The Main Evaluation

```powershell
cd "E:\Pycharm Project\pp-Echo"
$env:PP_AGENT_HTTP_TRUST_ENV="0"

python -m pp_agent.cli.main eval run evals/datasets/agent-core-60.json --workspace "E:\Pycharm Project\pp-Echo" --preflight
python -m pp_agent.cli.main eval report --workspace "E:\Pycharm Project\pp-Echo"
```

Use this as the main evidence in an interview or project write-up. It is large enough to be more credible than a demo, while still small enough to run and inspect locally.

## Optional Stress Evaluation

```powershell
python -m pp_agent.cli.main eval run evals/datasets/agent-stress-10.json --workspace "E:\Pycharm Project\pp-Echo" --preflight
python -m pp_agent.cli.main eval report --workspace "E:\Pycharm Project\pp-Echo"
```

The stress suite includes longer summaries, multi-module searches, repeated preferences, secret-dump pressure, shell approval, and subagent delegation. It is not the default live interview path.

## Offline Runtime Benchmark

The benchmark suite remains separate from real LLM behavior:

```powershell
python -m pytest tests/benchmarks/test_runner.py
```

The latest generated report is in `docs/benchmarks/latest.md`. It validates deterministic runtime mechanisms such as planner approval, session branching, lazy MCP activation, and context compaction. Safe rewind is best presented as an offline benchmark capability, not as a required live demo step.

## Interview Talk Track

1. Start with the methodology: fixed datasets, deterministic assertions, preflight checks, and separate infra failure accounting.
2. Run the 12-case demo to show the agent can handle direct answers, real tool use, repo awareness, safety, approval, and subagent handoff.
3. Show that the broader 60-case suite is the main evidence, grouped by capability rather than cherry-picked prompts.
4. Use the 15-task benchmark report to explain runtime engineering that does not depend on model luck.
5. State limitations clearly: this is not a public leaderboard, does not use LLM-as-judge, and does not claim mature multi-agent orchestration.
