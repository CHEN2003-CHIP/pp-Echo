from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pp_agent.cli.render.runtime import console
from pp_agent.evaluation.models import EvalReport
from pp_agent.evaluation.reports import load_latest_report
from pp_agent.evaluation.runner import run_suite


def eval_run_main(
    workspace: Path,
    *,
    suite: str = "pp_echo_core",
    mode: str = "deterministic",
    model: Optional[str] = None,
    cases: Optional[int] = None,
    seed: int = 0,
    timeout_seconds: int = 120,
    output_dir: Optional[Path] = None,
    save_history: bool = False,
    json_mode: bool = False,
) -> EvalReport:
    repo_root = _repo_root(workspace)
    report = run_suite(
        repo_root,
        suite=suite,
        mode=mode,
        model=model,
        case_count=cases,
        timeout_seconds=timeout_seconds,
        output_dir=output_dir,
        save_history=save_history,
    )
    if json_mode:
        console.print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        _print_report(report, output_dir or (repo_root / "evals" / "reports"))
    return report


def eval_report_main(
    workspace: Path,
    *,
    output_dir: Optional[Path] = None,
    json_mode: bool = False,
) -> EvalReport:
    repo_root = _repo_root(workspace)
    reports_dir = output_dir or (repo_root / "evals" / "reports")
    try:
        report = load_latest_report(reports_dir)
    except FileNotFoundError as exc:
        if json_mode:
            console.print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        else:
            console.print(f"Eval report not found: {exc}")
        raise SystemExit(1) from exc
    if json_mode:
        console.print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        _print_report(report, reports_dir)
    return report


def _print_report(report: EvalReport, reports_dir: Path) -> None:
    console.print("Tau-Style Eval Report")
    console.print(f"suite: {report.suite}")
    console.print(f"mode: {report.mode}")
    console.print(
        f"cases: {report.total_cases} passed: {report.passed} failed: {report.failed} "
        f"pending: {report.pending} infra_failed: {report.infra_failed} "
        f"success_rate: {report.task_success_rate:.2%}"
    )
    console.print(
        "rewards: "
        f"state={report.state_reward:.2%} "
        f"communication={report.communication_reward:.2%} "
        f"action={report.action_reward:.2%} "
        f"safety={report.safety_rate:.2%}"
    )
    console.print(f"result_path: {reports_dir / 'latest.json'}")
    console.print(f"summary_path: {reports_dir / 'latest.md'}")
    if report.category_summary:
        console.print("Category Summary")
        for category, item in sorted(report.category_summary.items()):
            console.print(
                f"- {category}: {item.get('passed', 0)}/{item.get('total', 0)} "
                f"passed ({float(item.get('success_rate', 0.0)):.2%})"
            )


def _repo_root(workspace: Path) -> Path:
    current = workspace.resolve(strict=False)
    for path in [current, *current.parents]:
        if (path / "pyproject.toml").exists() and (path / "src" / "pp_agent").exists():
            return path
    return Path.cwd()


__all__ = ["eval_report_main", "eval_run_main"]
