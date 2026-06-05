from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import time
from typing import Optional

from pp_agent.evaluation.adapter import ScriptedAgentAdapter, SdkAgentAdapter
from pp_agent.evaluation.environment import WorkspaceEnvironment
from pp_agent.evaluation.models import EvalReport, EvalTask
from pp_agent.evaluation.reports import build_report, write_report
from pp_agent.evaluation.scoring import score_case
from pp_agent.evaluation.user_simulator import ScriptedUserSimulator


def load_task(path: Path) -> EvalTask:
    return EvalTask.model_validate(json.loads(path.read_text(encoding="utf-8")))


def load_suite(repo_root: Path, suite: str) -> list[EvalTask]:
    suite_path = repo_root / "evals" / "suites" / f"{suite}.json"
    if not suite_path.exists():
        raise ValueError(f"Unknown eval suite: {suite}")
    payload = json.loads(suite_path.read_text(encoding="utf-8"))
    task_ids = [str(item) for item in payload.get("tasks", [])]
    return [load_task(repo_root / "evals" / "tasks" / f"{task_id}.json") for task_id in task_ids]


def expand_tasks(tasks: list[EvalTask], *, case_count: Optional[int]) -> list[EvalTask]:
    if case_count is None or case_count <= len(tasks):
        return tasks if case_count is None else tasks[:case_count]
    expanded: list[EvalTask] = []
    index = 0
    while len(expanded) < case_count:
        base = tasks[index % len(tasks)]
        round_no = index // len(tasks) + 1
        expanded.append(base.model_copy(update={"id": f"{base.id}__v{round_no:02d}"}))
        index += 1
    return expanded


def run_suite(
    repo_root: Path,
    *,
    suite: str = "pp_echo_core",
    mode: str = "deterministic",
    model: Optional[str] = None,
    case_count: Optional[int] = None,
    timeout_seconds: int = 120,
    output_dir: Optional[Path] = None,
    save_history: bool = False,
) -> EvalReport:
    tasks = expand_tasks(load_suite(repo_root, suite), case_count=case_count)
    scores = []
    simulator = ScriptedUserSimulator()
    provider = "scripted" if mode == "deterministic" else "runtime"
    resolved_model = model or ("ScriptedAgent" if mode == "deterministic" else "configured-runtime")
    reports_dir = output_dir or (repo_root / "evals" / "reports")
    with tempfile.TemporaryDirectory(prefix="pp_echo_tau_eval_") as dirname:
        run_root = Path(dirname)
        for task in tasks:
            env = WorkspaceEnvironment(repo_root, task, run_root)
            workspace = env.prepare()
            before = env.snapshot()
            adapter = ScriptedAgentAdapter() if mode == "deterministic" else SdkAgentAdapter(timeout_seconds=timeout_seconds)
            started = time.perf_counter()
            trace = simulator.run(task, workspace, adapter)
            trace.duration_seconds += time.perf_counter() - started
            after = env.snapshot()
            verification = env.run_verification_commands()
            scores.append(
                score_case(
                    task,
                    workspace=workspace,
                    before_snapshot=before,
                    after_snapshot=after,
                    trace=trace,
                    verification_results=verification,
                )
            )
    report = build_report(suite=suite, mode=mode, provider=provider, model=resolved_model, scores=scores)
    report = report.model_copy(update={"chart_path": "latest.svg"})
    write_report(report, reports_dir, save_history=save_history)
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run pp-Echo tau-style agent evals.")
    parser.add_argument("--suite", default="pp_echo_core")
    parser.add_argument("--mode", choices=["deterministic", "live"], default="deterministic")
    parser.add_argument("--model", default=None)
    parser.add_argument("--cases", type=int, default=None)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--save-history", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[3]
    report = run_suite(
        repo_root,
        suite=args.suite,
        mode=args.mode,
        model=args.model,
        case_count=args.cases,
        timeout_seconds=args.timeout_seconds,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        save_history=args.save_history,
    )
    if args.json:
        print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        print(f"Passed {report.passed}/{report.total_cases} with {report.pending} pending")
        print(f"Wrote {(Path(args.output_dir) if args.output_dir else repo_root / 'evals' / 'reports') / 'latest.json'}")
    return 0 if report.failed == 0 and report.pending == 0 and report.infra_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
