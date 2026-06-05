# pp-Echo Tau-Style Agent Evaluation

pp-Echo now treats agent evaluation as a task environment problem, following the core idea of τ-bench: an agent is evaluated through a controlled environment, a user simulator, the interaction trace, and final-state rewards.

The old prompt datasets and text expectation runner have been removed. The supported eval path is `pp_echo_core`.

## What Is Evaluated

| Layer | Location | Purpose |
| --- | --- | --- |
| Suite | `evals/suites/pp_echo_core.json` | Ordered core task set. |
| Tasks | `evals/tasks/*.json` | Canonical task specs with user agenda, state criteria, and action constraints. |
| Fixtures | `evals/fixtures/*` | Isolated workspace environments copied per case. |
| Runner | `pp_agent.evaluation.runner` | Executes simulator, agent adapter, environment checks, and scoring. |
| Reports | `evals/reports/latest.*` | JSON, Markdown, and SVG summaries. |

The current suite covers file editing, tool selection, approval flow, protected paths, checkpoint rewind, memory recall, and constrained subagent use.

## Run

```powershell
cd "E:\Pycharm Project\pp-Echo"
$env:PYTHONPATH="src"

python evals/runner.py --suite pp_echo_core --mode deterministic --cases 100
python -m pp_agent.cli.main eval run --suite pp_echo_core --mode deterministic --cases 100
python -m pp_agent.cli.main eval report --json
```

`deterministic` mode uses a scripted user and scripted agent adapter, so it is stable for CI and scorer development. `live` mode uses the real SDK/runtime and can spend tokens:

```powershell
python -m pp_agent.cli.main eval run --suite pp_echo_core --mode live --model your_model_name --cases 3 --timeout-seconds 180
```

## Scoring

The primary score is not substring matching. Each case is scored from:

- final workspace state and verification commands
- required communication to the user
- tool, approval, and safety constraints
- runtime trace evidence such as memory recall or protected-path block events

Reports include task success rate, state reward, communication reward, action reward, safety rate, approval recall, tool success rate, average turns, and category summaries.

## Task Format

Each task JSON contains:

- `id`, `name`, `category`, `workspace_fixture`, `max_turns`
- `user_agenda`: scripted steps such as `message`, `approve_pending`, and `reject_pending`
- `success_criteria`: final file state, verification commands, required communication, and trace requirements
- `action_constraints`: required tools, forbidden tools, and required approvals

This makes eval behavior reproducible and inspectable without relying on a prompt-only pass/fail label.
