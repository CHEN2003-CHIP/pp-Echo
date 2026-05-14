# pp-Echo

<p align="center">
  <img src="docs/assets/logo-echo.svg" alt="pp-Echo logo" width="104" height="104" />
</p>

<p align="center">
  <strong>A Windows-first, CLI-first coding agent you can actually study, run locally, and extend.</strong><br />
  It shows plans before execution, asks before risky actions, and can rewind both repository state and conversation history.
</p>

<p align="center">
  <a href="#quick-start"><img alt="Quick Start" src="https://img.shields.io/badge/Quick_Start-59D0A8?style=for-the-badge&logo=windows-terminal&logoColor=white"></a>
  <a href="docs/agent-learning-zh.md"><img alt="Chinese Learning Path" src="https://img.shields.io/badge/Chinese_Learning_Path-DC2626?style=for-the-badge&logo=readme&logoColor=white"></a>
  <a href="#why-this-repo-is-worth-studying"><img alt="Why Study" src="https://img.shields.io/badge/Why_Study-1E293B?style=for-the-badge&logo=bookstack&logoColor=white"></a>
  <a href="#quick-learning-path"><img alt="Learning Path" src="https://img.shields.io/badge/Learning_Path-2563EB?style=for-the-badge&logo=readthedocs&logoColor=white"></a>
  <a href="#demo--screenshots"><img alt="Demo" src="https://img.shields.io/badge/Demo-163257?style=for-the-badge&logo=gitlfs&logoColor=white"></a>
  <a href="https://github.com/CHEN2003-CHIP/pp-Echo/releases"><img alt="Releases" src="https://img.shields.io/badge/Releases-F8D66D?style=for-the-badge&logo=github&logoColor=111827"></a>
</p>

![pp-Echo hero](docs/assets/hero.svg)

<p align="center">
  <img src="docs/assets/windows-first-agent-pixel.png" alt="Pixel art Windows-first agent mascot" width="720" />
</p>

<p align="center">
  <code>Plan before act</code> | <code>Approve risky actions</code> | <code>Explicit @subagent handoff</code> | <code>Rewind code + conversation safely</code> | <code>CLI + Web UI + TUI</code>
</p>

pp-Echo is both a practical local coding agent and a learn-by-reading reference project for agent engineering. If you are new to agents, this repo gives you something many projects do not: a real runtime, visible planning, approval gates, memory, session recovery, and a codebase you can follow without needing a giant platform behind it.

pp-Echo 既是一个可以实际运行的本地 coding agent，也是一个适合边读边学的 agent engineering 参考项目。如果你是 agent 初学者，这个仓库提供了很多项目没有的东西：真实可运行的 runtime、可见的 planning、审批门控、memory、session 恢复能力，以及一套不依赖庞大平台也能顺着读懂的代码结构。

## Current Status

pp-Echo should currently be understood as a `Windows-first` project.

- Windows is the main supported and most tested path today.
- The helper scripts and the quickest onboarding path are Windows-oriented.
- The Web UI is part of the normal workflow, including project switching, visible runtime status, and approval handling.
- Linux and macOS should not be assumed to have equal support yet.
- The runtime, exact-effect approvals, memory files, rewind, session tree, and storage model are real and useful today.
- Subagent support exists, but it is still MVP-level rather than a finished agent-team system.

In other words: this repo already contains real architecture worth studying, but it is still evolving and should not be described as a fully mature multi-agent platform.

## Windows-First Scope

The project is intentionally described as `Windows-first` to avoid confusion.

- Use Windows for the clearest supported experience.
- Treat Linux/macOS compatibility as future work rather than current parity.
- Read the `.bat` scripts as the primary convenience entrypoints, not as optional historical leftovers.
- Prefer `start-web.bat` when you want the browser UI with visible approvals, status, sessions, and project switching.

## Subagent Progress

The `@subagent` path is real, but narrow by design today.

What exists now:

- explicit user-triggered `@subagent` handoff
- a built-in `spawn_subagent` tool
- a built-in `orchestrate_agents` tool for parallel read-only repository analysis and planning-style fan-out
- seven built-in child specs: `repo-researcher`, `change-reviewer`, `test-investigator`, `api-scout`, `memory-scout`, `implementation-planner`, and `code-worker`
- child execution that forks a session, narrows tools, runs a constrained prompt, and returns a summary

What does not exist yet:

- full agent-team orchestration
- rich long-running multi-agent coordination
- broad autonomous agent-team execution with independent write ownership

The honest description is: `subagent support exists, with explicit child handoff and narrow orchestration support, but it is not yet a finished autonomous agent-team system`.

## Why This Repo Is Worth Studying

- It is not just a toy chatbot. It contains a real runtime loop, tool registry, session host, memory layer, approvals, rewind, and multiple user interfaces.
- It is beginner-friendly. The repo includes Chinese and English learning guides plus a source map for reading the code in a sensible order.
- It is practical. You can run it locally, inspect its behavior, and use it as a reference when building your own agent system.
- It is opinionated in the right places. Planning is visible, risky actions are reviewable, and the system is designed around repo work instead of generic chat.
- It is a good bridge project. Beginners can learn architecture here, and experienced builders can borrow patterns for runtime orchestration, tool calling, and safety boundaries.

## Best For

- Beginners who want to understand how an agent project is organized end to end.
- Developers who want a local coding agent with visible planning and approval flow.
- Builders who want to learn how runtime, tools, memory, sessions, CLI, and TUI fit together.
- People comparing agent repos and looking for one that is easier to read, extend, and trust.

## What You Will Learn

- How an agent runtime manages turns, planning, tools, and execution.
- How tool registration and dispatch work in a repo-aware coding assistant.
- How session hosting, rewind, and checkpoint ideas can improve agent usability.
- How memory and vector retrieval integrate into an agent workflow.
- How one backend can drive both a CLI chat experience and a richer TUI.
- How to structure a project so it is usable as both product and learning material.

## Evaluated Agent Behavior

pp-Echo is evaluated as an engineering agent, not only as a chatbot demo. The evaluation stack separates live model behavior from deterministic runtime checks, so failures can be understood as either behavior regressions or infrastructure issues.

<p align="center">
  <img alt="Live Eval" src="https://img.shields.io/badge/Live_eval-12%2F12_passed-22C55E?style=for-the-badge&logo=checkmarx&logoColor=white">
  <img alt="Main Suite" src="https://img.shields.io/badge/Main_suite-60_cases-2563EB?style=for-the-badge&logo=pytest&logoColor=white">
  <img alt="Runtime Benchmark" src="https://img.shields.io/badge/Runtime_benchmark-15_tasks-7C3AED?style=for-the-badge&logo=speedtest&logoColor=white">
  <img alt="Stress Suite" src="https://img.shields.io/badge/Stress_suite-10_cases-F97316?style=for-the-badge&logo=target&logoColor=white">
</p>

| Evaluation layer | Size | What it proves | How to run |
| --- | ---: | --- | --- |
| Live interview demo | 12 cases | Direct answers, repo awareness, tool use, Git awareness, safety, approvals, and explicit subagent handoff | `python -m pp_agent.cli.main eval run example-interview-eval-cases.json --workspace . --preflight` |
| Main agent eval | 60 cases | Broader evidence across tool restraint, code search, safety, collaboration, memory, and Chinese technical expression | `python -m pp_agent.cli.main eval run evals/datasets/agent-core-60.json --workspace . --preflight` |
| Deterministic runtime benchmark | 15 tasks | Planner approval, safe rewind, session branching, lazy MCP activation, and context compaction without model randomness | `python -m pytest tests/benchmarks/test_runner.py` |
| Optional stress suite | 10 cases | Longer context, multi-module search, secret-dump pressure, shell approval, and subagent delegation | `python -m pp_agent.cli.main eval run evals/datasets/agent-stress-10.json --workspace . --preflight` |

Most recent recorded local live demo result:

| Run | Cases | Pass rate | Tool calls | Approval gates | Expected policy blocks |
| --- | ---: | ---: | ---: | ---: | ---: |
| `20260512-234612-6fb26ca4` | 12 | 100% | 14 | 2 | 1 |

The expected policy block is the protected `.env` safety case: the tool layer refuses to expose secrets, and the evaluator counts that as a correct safety outcome. The two approval gates come from write-file and shell-execution scenarios.

```mermaid
flowchart LR
  A["Agent evaluation"] --> B["Live eval<br/>12 cases"]
  A --> C["Main suite<br/>60 cases"]
  A --> D["Runtime benchmark<br/>15 deterministic tasks"]
  A --> E["Stress suite<br/>10 cases"]

  B --> B1["100% pass<br/>14 tool calls<br/>2 approvals"]
  C --> C1["7 capability groups<br/>fixed assertions"]
  D --> D1["Fake LLM clients<br/>reproducible runtime checks"]
  E --> E1["Longer and higher-risk scenarios"]
```

The benchmark report in [docs/benchmarks/latest.md](docs/benchmarks/latest.md) currently highlights:

- Planner approval blocked risky mutations before execution in 100% of gating tasks.
- Safe rewind recovered requested workspace and conversation state in 100% of rewind tasks.
- Lazy MCP avoided unnecessary server initialization while still activating the matched fetch path.
- Context compaction reduced normalized prompt size by about 44% in long-dialogue tasks.

See [docs/evaluation-demo.md](docs/evaluation-demo.md) for the interview talk track and dataset methodology.

## Quick Start

pp-Echo targets Python 3.9+ and is easiest to try on Windows first.

Before you start:

- Set `PP_AGENT_API_KEY` in your environment.
- Use `start-agent.bat` for the fastest first run.
- Use `start-web.bat` for the browser Web UI.
- If you run from source, set `PYTHONPATH=src`.

### Fastest Windows path

```powershell
set PP_AGENT_API_KEY=your_api_key
.\start-agent.bat
```

This is the shortest path from clone to first conversation.

### Web UI on Windows

```powershell
set PP_AGENT_API_KEY=your_api_key
.\start-web.bat
```

This opens `http://127.0.0.1:8765` automatically, installs missing Web dependencies when needed, and builds the browser UI the first time.
You can also launch a specific project with `.\start-web.bat "E:\path\to\project"` and switch projects from the Web UI.

### TUI on Windows

```powershell
set PP_AGENT_API_KEY=your_api_key
.\echo-cli.bat
```

Use this when you want the richer terminal UI instead of plain chat output.

### Run from source

```powershell
git clone https://github.com/CHEN2003-CHIP/pp-Echo.git
cd pp-Echo
set PP_AGENT_API_KEY=your_api_key
set PYTHONPATH=src
python -m pp_agent.cli.main chat
```

Minimal non-interactive demo:

```powershell
set PP_AGENT_API_KEY=your_api_key
set PYTHONPATH=src
python -m pp_agent.cli.main run "Give me a quick overview of this repo"
```

### Installed CLI

```powershell
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
pp-agent chat
```

If `pip install -e .` fails on an older environment, use the source-run path first.

## Quick Learning Path

If you are new to this repo, read in this order:

1. Start with the learning docs:
   [docs/agent-learning-zh.md](docs/agent-learning-zh.md),
   [docs/agent-learning-en.md](docs/agent-learning-en.md),
   [docs/source-map.md](docs/source-map.md)
2. Then read the three core backend files:
   [src/pp_agent/runtime/runtime.py](src/pp_agent/runtime/runtime.py),
   [src/pp_agent/tools/registry.py](src/pp_agent/tools/registry.py),
   [src/pp_agent/runtime/session_host.py](src/pp_agent/runtime/session_host.py)
3. Then move to the product layers:
   [src/pp_agent/cli/chat.py](src/pp_agent/cli/chat.py),
   [src/pp_agent/tui/app.py](src/pp_agent/tui/app.py),
   [src/pp_agent/app/bootstrap.py](src/pp_agent/app/bootstrap.py)

```mermaid
flowchart TD
  A["Start Here"] --> B["Learning Guides"]
  B --> B1["docs/agent-learning-zh.md"]
  B --> B2["docs/agent-learning-en.md"]
  B --> B3["docs/source-map.md"]

  B3 --> C["Core Runtime Path"]
  C --> C1["runtime/runtime.py"]
  C1 --> C2["tools/registry.py"]
  C2 --> C3["runtime/session_host.py"]

  C3 --> D["System Assembly"]
  D --> D1["app/bootstrap.py"]
  D1 --> D2["storage/settings.py"]

  C1 --> E["Capability Layers"]
  E --> E1["memory/*"]
  E --> E2["skills/*"]
  E --> E3["extensions/*"]
  E --> E4["mcp/*"]

  C1 --> F["Product Layers"]
  F --> F1["cli/chat.py"]
  F --> F2["tui/app.py"]
  F --> F3["cli/render/*"]
```

## Demo / Screenshots

![pp-Echo demo](docs/assets/demo.gif)

- Launch with `start-agent.bat` for chat or `echo-cli.bat` for the TUI.
- Ask the agent to inspect a repo task and preview risky work before execution.
- Review approvals, create checkpoints, and use safe rewind to recover both code and conversation state.

| Interactive chat | Checkpoint + rewind |
| --- | --- |
| ![Interactive chat screenshot](docs/assets/screenshot-chat.png) | ![Checkpoint screenshot](docs/assets/screenshot-checkpoint.png) |

The Web UI is now part of the normal workflow; a dedicated Web UI screenshot should be added with the next visual refresh so the README matches the current browser approval experience.

## Why pp-Echo

Most coding agents are good at producing output. Fewer are good at making their behavior visible, reviewable, and reversible once a real repository gets messy. pp-Echo is built for that gap.

- Planning stays visible before execution, so you can supervise direction instead of reacting after changes land.
- High-risk operations can pause behind approvals instead of mutating the workspace immediately.
- Sessions are stored as a tree, making branch, resume, compare, and rewind workflows easier to reason about.
- Safe rewind is git-backed, so you can restore the conversation, the workspace, or both together.
- Skills, extensions, and MCP-backed capabilities fit into the same repo-aware runtime rather than feeling bolted on.
- Subagent delegation is explicit: users can require a child handoff with `@subagent` instead of guessing when the agent will delegate on its own.

If this repo helps you learn agents faster or gives you a useful starting point for your own system, a Star helps more people discover it.

## Safety Boundary

Phase 1 now uses a mandatory policy gate for sensitive execution. This gate is checked at execution time, not only at planner time.

- The policy gate returns `allow`, `ask`, or `deny`.
- `ask` means the model can stage a proposed effect, but only the host/user side may approve it.
- Protected paths are enforced through path protection and policy gating.
- This phase is not a true shell sandbox. The existing shell runner remains in place behind the policy gate and host approval flow.

Protected paths in Phase 1:

- `.pp-agent/**`
- `.git/**`
- `.env`
- `.env.*`
- `*.pem`
- `*.key`

Important Phase 1 limit:

- `.pp-agent/**` is logically isolated from model-facing tools, but it is not physically separated from the repository yet.

## Exact-Effect Approvals

Phase 2A upgrades sensitive approval binding so host approval applies to an exact staged effect, not just a token.

- Sensitive file and shell proposals now produce an effect record before execution.
- `payload_digest` is the primary approval binding.
- Human-readable summaries are review output and a secondary consistency check, not the primary security anchor.
- File effects distinguish whether the target was absent or present at staging time.
- Shell effects use narrow normalization: whitespace-only differences normalize, but command content, separators, redirection, quotes, parameter order, and timeout changes remain material.
- Planner approval is still not execution approval.
- The Web UI mirrors this two-step model: first approve the plan, then apply the concrete staged write/edit/command. After host execution it removes the consumed token and shows a clear success/failure message.

## Shell Effect Classification

Phase 2B keeps exact-effect approval binding, but makes staged shell effects easier to review and reason about.

- Shell effects now include structured fields such as `normalized_command`, `command_head`, `risk_class`, `writes_workspace_files`, `touches_external_paths`, `requests_network`, and `destructive_hint`.
- Current shell classes are `inspect`, `workspace_mutation`, `external_mutation`, `networked`, and `destructive`.
- Human-readable shell summaries are stable review output such as `Inspect repository status with git status` or `Fetch remote content with curl`.
- Classification enriches policy decisions and previews, but it does not bypass host-side approval and it is not a shell sandbox.
- Normalization remains intentionally narrow: whitespace-only differences normalize to the same effect, while command, parameter, separator, redirection, quote, and timeout changes remain material.

Current Phase 2B limits:

- Shell classification is still conservative heuristic matching, not a full shell parser or AST.
- The existing shell runner is still used; this phase does not add sandbox infrastructure.
- Policy still keeps shell execution behind host-side approval even for `inspect` commands.

Planned Phase 2C direction:

- Finer-grained shell semantics and better effect summaries.
- Broader effect classification across more tool families.
- Stronger policy differentiation once classification confidence is high enough.

## Shared Effect Analysis

Phase 2C generalizes effect semantics across built-in file tools, shell tools, and dynamic extension or MCP tools.

- Shared analysis records now expose `family`, `risk_class`, `summary`, `confidence_band`, `touches_workspace`, `touches_external`, `requests_network`, `destructive_hint`, and `protected_path_hint`.
- Policy uses stable confidence bands such as `high`, `medium`, `low`, and `unknown` instead of relying on raw float thresholds in behavior rules.
- Built-in file reads can still be allowed when the target is a normal workspace path and analysis is high confidence.
- Shell policy differentiation stays narrow: only a known-safe inspect subset such as `git status`, `git diff`, `rg`, `grep`, `ls`, `dir`, and `Get-ChildItem` may be allowed automatically.
- Extension and MCP tools now receive shared analysis too, but this does not mean they have shared exact-effect approvals. Without staged exact-effect support, they remain policy-level `ask` or `deny`.

Current Phase 2C limits:

- Shared analysis is still heuristic and conservative.
- Unknown or weakly understood extension or MCP semantics fail closed.
- Only security-relevant, stably recomputable analysis fields are included in effect identity.

## Dynamic Tool Declarations

Phase 4A completes the public cutover: explicit declarations are now the only author-facing semantics contract for dynamic extension and MCP tools.

- Dynamic tools declare `exact_effect_mode` as `none`, `auto`, or `required`.
- `exact_effect_mode` is the primary exact-effect capability declaration. Authors do not set a free `supports_exact_effect_staging` boolean directly.
- Registration acceptance is intentionally looser than execution eligibility: weakly declared tools may still register, but they fail closed at policy or execution time.
- `required` never falls back to direct execution. If a call cannot be represented stably enough for exact approval, it fails closed with `approval_unavailable`.
- `known_safe_inspect` only makes a tool eligible for safe-inspect policy consideration. It never implies `allow` by itself.
- Runtime/shared analysis now tightens fields conservatively instead of replacing declared semantics wholesale.
- Author-facing `analysis_hints` are no longer accepted by public registration APIs.
- A private runtime-internal override path remains available only for conservative risk tightening inside framework code.

Primary declarations:

- `exact_effect_mode`
- `non_side_effectful`
- `known_safe_inspect`
- `requests_network_hint`
- `touches_external_hint`

Private runtime-only risk overrides may only tighten risk with these keys:

- `requests_network`
- `touches_external`
- `destructive_hint`
- `protected_path_hint`
- `touches_workspace`

Only the tightening-direction value `True` is accepted for these internal overrides. Safe or widening values such as `False`, `safe`, `allow`, `read_only`, or `inspect_only` are rejected.

Disallowed legacy keys:

- `risk_class`
- `summary`
- `confidence_score`
- `confidence_band`
- `known_safe_inspect`
- `exact_effect_mode`
- `supports_exact_effect_staging`

Representative alias examples that are also rejected as primary-semantics hints:

- `safe`
- `allow`
- `read_only`
- `inspect_only`
- `stageable`
- `approval_supported`
- `exact_effect_supported`
- `confidence`
- `safety_score`
- `display_summary`

Author guidance:

- Prefer `exact_effect_mode="auto"` when unsure.
- Use `required` only for tools that should enter exact-effect approval whenever the call is policy-sensitive and stably representable.
- Leave `known_safe_inspect=False` unless the tool is clearly read-only and non-side-effectful.
- Runtime risk signals win conservatively on a field-by-field basis. A declared safe inspect tool can still be tightened back to `ask`, `approval_unavailable`, or `deny`.
- See `docs/dynamic-tool-declarations.md` for the versioned deprecation timeline, an old-to-new migration table, and examples of a safe inspect tool, a staged side-effectful tool, an unstable fail-closed tool, and an MCP registration.

## Legacy Hint Doctor

The legacy-hints doctor now doubles as a release gate for the public cutover.

- Use `pp-agent capabilities legacy-hints --workspace <path>` for a human-readable report.
- Use `pp-agent capabilities legacy-hints --json --workspace <path>` for machine-readable output.
- Use `pp-agent capabilities legacy-hints --strict --workspace <path>` to fail the command when author-facing legacy usage remains.
- Runtime metadata is the authoritative readiness source.
- Static source scanning is advisory only and does not decide readiness by itself.
- Author-facing legacy `analysis_hints` count as removal blockers. Runtime-internal risk overrides are reported separately.
- Removal readiness for `v0.4.0` requires zero author-facing legacy `analysis_hints` in runtime metadata.

Current limits:

- Dynamic tool defaults remain tighter than built-in file and shell flows.
- Direct execution on policy `allow` stays limited to a narrow high-confidence, non-side-effectful inspect subset.
- Unknown, weakly understood, networked, destructive, or externally touching dynamic calls still fail closed to `ask` or `deny`.
- This phase still does not add sandboxing, a grant history ledger, or physical control-plane separation.

## Core Workflows

### 1. Chat and run

```powershell
set PYTHONPATH=src
python -m pp_agent.cli.main chat
python -m pp_agent.cli.main run "Audit this repo and summarize risky commands"
```

### 1A. Explicit subagent handoff

Use `@subagent` when you want the runtime to force a child handoff before the main agent touches other tools.

This is currently a bounded child workflow with an orchestration helper, not a full autonomous agent-team planner. Treat it as explicit delegated inspection and planning fan-out with constrained children, not as mature long-running multi-agent execution.

```text
@subagent Read README.md and summarize the project
@subagent Review the current diff and call out the biggest risks
```

Current built-in subagent specs:

- `repo-researcher`: read-only repository inspection with `read_file`, `list_files`, `search_text`, and `grep_code`
- `change-reviewer`: change-review flow with `git_status` and `git_diff_worktree` added to the read-only tool set
- `test-investigator`: inspect failing tests, error output, and related code paths
- `api-scout`: trace interfaces, types, and call sites across the repository
- `memory-scout`: search long-term file memory with `memory_search` and `memory_get`
- `implementation-planner`: turn research findings into a low-risk implementation plan and write-scope split
- `code-worker`: scoped coding child profile; currently constrained to read/review tools and staged-edit reporting

Behavior notes:

- `@subagent` is required before `spawn_subagent` can run.
- `orchestrate_agents` can fan out multiple constrained subagents for read-only analysis, debugging, or implementation planning.
- If the model invents an unknown child name, runtime normalizes it back to a valid built-in subagent spec.
- In chat mode, `@subagent` requests are forced through `spawn_subagent` instead of silently falling back to direct main-agent file reads.
- Current child execution is intentionally narrow: fork session, restrict tools, run a constrained prompt, return summary output.

### 2. Sessions and tree navigation

```powershell
set PYTHONPATH=src
python -m pp_agent.cli.main sessions list
python -m pp_agent.cli.main sessions tree
```

### 3. Approvals and staged actions

```powershell
set PYTHONPATH=src
python -m pp_agent.cli.main approvals list
python -m pp_agent.cli.main approvals summary
```

### 4. Checkpoints and safe rewind

```powershell
set PYTHONPATH=src
python -m pp_agent.cli.main checkpoint list
python -m pp_agent.cli.main rewind-safe --session <session_id> --turns 2
```

### 5. Capabilities, skills, and MCP

```powershell
set PYTHONPATH=src
python -m pp_agent.cli.main capabilities list
python -m pp_agent.cli.main skills list
```

## Architecture

```mermaid
flowchart LR
  U["User Prompt"] --> CLI["CLI / BAT entry"]
  CLI --> RT["Agent runtime"]
  RT --> PLAN["Planner"]
  PLAN --> GATE{"Approval needed?"}
  GATE -->|"Yes"| AQ["Approval queue"]
  GATE -->|"No"| EXEC["Executor"]
  AQ --> EXEC
  EXEC --> TOOLS["Repo / file / shell / search / MCP tools"]
  TOOLS --> CKPT["Git-backed checkpoint + safe rewind"]
  CKPT --> SESS["Session tree + workspace state"]
  SESS --> CLI
```

## Learning Docs

If you are new to agent engineering or want a guided tour of this codebase:

- Chinese learning guide: [docs/agent-learning-zh.md](docs/agent-learning-zh.md)
- English learning guide: [docs/agent-learning-en.md](docs/agent-learning-en.md)
- Source map / module call graph: [docs/source-map.md](docs/source-map.md)

## Configuration

### Environment variables

- `PP_AGENT_API_KEY`
- `PP_AGENT_BASE_URL`
- `PP_AGENT_MODEL`
- `PP_AGENT_ENABLE_THINKING`
- `PP_AGENT_HOME`

### Project config

Create `.pp-agent/config.json` for per-project overrides:

```json
{
  "model": "qwen3.5-plus",
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "enable_thinking": false,
  "shell_timeout_seconds": 30,
  "capabilities": {
    "builtin_tools": { "enable": true },
    "skills": {
      "enable_project": true,
      "enable_user": true,
      "enable_builtin": true,
      "custom_directories": [],
      "ignored": [],
      "include": []
    },
    "extensions": {
      "enable_project": true,
      "enable_user": true,
      "enable_builtin": false,
      "custom_directories": [],
      "ignored": [],
      "include": []
    },
    "mcp": {
      "enable": false,
      "config_paths": [],
      "server_filters": []
    }
  },
  "tool_confirmation": {
    "write_file": true,
    "edit_file": true,
    "run_shell": true,
    "high_risk_plan": true
  }
}
```

`tool_confirmation` still exists for planner-era compatibility, but it is no longer the complete safety model on its own. Sensitive execution now also passes through a mandatory execution-time policy gate.

### Resources and manifests

Project resources can be declared in `.pp-agent/resources.json` or `.pp-agent/package.json`. If no manifest is present, pp-Echo falls back to conventional directories like `.pp-agent/skills` and `.pp-agent/extensions`, and also supports pi-compatible discovery from `.pi/skills` and `.agents/skills`.

## Releases

- Release notes for the first formal release live in [releases/v0.2.0.md](releases/v0.2.0.md).
- A reusable template for future releases lives in [.github/release-template.md](.github/release-template.md).
- GitHub Releases page: [github.com/CHEN2003-CHIP/pp-Echo/releases](https://github.com/CHEN2003-CHIP/pp-Echo/releases)

## Benchmarks

- Latest benchmark report: [docs/benchmarks/latest.md](docs/benchmarks/latest.md)
- Generated benchmark artifacts: [artifacts/benchmarks](artifacts/benchmarks)
- The suite is deterministic, offline, and focuses on planner gating, safe rewind, MCP lazy activation, session branching, and long-context compaction.

## Contributing

Contributions are welcome across CLI behavior, docs polish, demo assets, tests, extensions, and release packaging.

Start here:

- Read [CONTRIBUTING.md](CONTRIBUTING.md)
- Run tests with `python -m pytest`
- Keep documentation and demo assets in sync when user-facing behavior changes

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
