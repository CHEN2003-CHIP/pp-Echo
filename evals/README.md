# pp-Echo Tau-Style Agent Eval

This directory contains the canonical pp-Echo agent eval suite. It follows the τ-bench style: each case runs inside an isolated workspace environment, a scripted user drives turns, the adapter records the agent trace, and scoring is based on final state plus action and communication rewards.

## Run

```powershell
python evals/runner.py --suite pp_echo_core --mode deterministic --cases 100
python -m pp_agent.cli.main eval run --suite pp_echo_core --mode deterministic --cases 100
python -m pp_agent.cli.main eval report --json
```

Live mode uses the real runtime and may spend tokens:

```powershell
python -m pp_agent.cli.main eval run --suite pp_echo_core --mode live --model your_model_name --cases 3 --timeout-seconds 180
```

## Layout

- `suites/pp_echo_core.json`: ordered task list.
- `tasks/*.json`: task specs with user agenda, success criteria, and action constraints.
- `fixtures/*`: copied into a temporary workspace for each case.
- `reports/latest.json`, `latest.md`, `latest.svg`: generated report outputs.

## Metrics

Reports include task success rate, state reward, communication reward, action reward, safety rate, safety violations, approval recall, tool success rate, average tool calls, average turns, and per-category summaries.

The old prompt eval datasets and `contains`/`tool_called` expectation runner were removed. New cases should be expressed as environment tasks with final-state assertions.
