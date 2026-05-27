# pp-Echo Agent Eval Baseline

This directory contains the first baseline eval framework for pp-Echo. It is intentionally separate from the core runtime so future Agent Kernel, EventBus, ContextEngine, and SessionTree changes can be compared against the same task set.

## Eval Modes

- `deterministic`: uses `AgentEvalAdapter` with scripted behavior. It is suitable for CI and scorer development.
- `live`: runs the real CLI runtime through `python -m pp_agent.cli.main run ... --json`. It is for before/after refactor comparisons and should not run in CI by default.

## Run

```powershell
python evals/runner.py --suite baseline --mode deterministic --cases 100
python evals/runner.py --suite baseline --mode live --model <model-name> --cases 10 --timeout-seconds 180
```

Reports are written to:

```text
evals/reports/latest.json
evals/reports/latest.md
evals/reports/latest.svg
```

The runner also saves timestamped history files such as:

```text
evals/reports/baseline-deterministic-YYYYMMDD-HHMMSS.json
evals/reports/baseline-deterministic-YYYYMMDD-HHMMSS.md
evals/reports/baseline-deterministic-YYYYMMDD-HHMMSS.svg
```

## Metrics

Reports include:

- task success rate
- tool success rate
- safety rate and safety violation count
- approval recall
- average tool calls
- average duration
- category-level summaries
- per-case failure reasons
- an SVG chart for quick visual comparison

## Live Runtime Notes

Before running live mode, configure the same environment you use for pp-Echo:

```powershell
set PYTHONPATH=src
set PP_AGENT_API_KEY=your_api_key
set PP_AGENT_MODEL=your_model_name
```

Then run:

```powershell
python evals/runner.py --suite baseline --mode live --model %PP_AGENT_MODEL% --cases 10
```

`--model` is recorded in the report for comparison. Configure the actual runtime model through pp-Echo's normal config or `PP_AGENT_MODEL` before running. Live mode can spend real tokens and may create pending approvals. Start with `--cases 1` or `--cases 10`, then scale up.

## Task Format

Each task file in `evals/tasks/*.yaml` is a YAML-compatible JSON document with:

- `id`
- `name`
- `category`
- `workspace_fixture`
- `user_goal`
- `expected_files_changed`
- `forbidden_files_changed`
- `required_approvals`
- `forbidden_tools`
- `verification_commands`
- `success_criteria`

## Current Coverage

Fully implemented in deterministic mode:

- 100-case expanded baseline from the seven task templates
- file edit baseline
- tool selection trace checks
- approval-required checks
- protected path safety checks
- checkpoint rewind restoration checks
- subagent limited-tools checks

Pending until runtime event/trace wiring exists:

- memory recall event verification
