from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pp_agent.cli.render.runtime import console
from pp_agent.evaluation import EvalSummary, load_eval_summary, run_eval_file


def eval_run_main(
    dataset: Path,
    workspace: Path,
    *,
    run_id: Optional[str] = None,
    output_dir: Optional[Path] = None,
    reuse_session: bool = False,
    stop_on_failure: bool = False,
    preflight: bool = False,
    json_mode: bool = False,
) -> EvalSummary:
    summary = run_eval_file(
        dataset,
        workspace,
        run_id=run_id,
        output_dir=output_dir,
        reuse_session=reuse_session,
        stop_on_failure=stop_on_failure,
        preflight=preflight,
    )
    if json_mode:
        console.print(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        _print_summary(summary)
    return summary


def eval_report_main(
    workspace: Path,
    *,
    run_id: Optional[str] = None,
    output_dir: Optional[Path] = None,
    json_mode: bool = False,
) -> EvalSummary:
    try:
        summary = load_eval_summary(workspace, run_id=run_id, output_dir=output_dir)
    except FileNotFoundError as exc:
        if json_mode:
            console.print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        else:
            console.print(f"Eval report not found: {exc}")
        raise SystemExit(1) from exc
    if json_mode:
        console.print(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        _print_summary(summary)
    return summary


def _print_summary(summary: EvalSummary) -> None:
    console.print("Eval Summary")
    console.print(f"run_id: {summary.run_id}")
    console.print(
        f"cases: {summary.case_count} passed: {summary.passed_count} failed: {summary.failed_count} "
        f"infra_failed: {summary.infra_failed_count} assertion_failed: {summary.assertion_failed_count} "
        f"pass_rate: {summary.pass_rate:.2%}"
    )
    console.print(f"duration_seconds: {summary.duration_seconds:.3f}")
    console.print(f"result_path: {summary.result_path}")
    console.print(f"summary_path: {summary.summary_path}")
    metrics = summary.metrics
    if metrics:
        console.print(
            "metrics: "
            f"provider_requests={metrics.get('provider_request_count', 0)} "
            f"tool_calls={metrics.get('tool_call_count', 0)} "
            f"tool_errors={metrics.get('tool_error_count', 0)} "
            f"approvals={metrics.get('approval_count', 0)} "
            f"recall_events={metrics.get('memory_recall_event_count', 0)} "
            f"recalled_chunks={metrics.get('memory_recalled_chunk_count', 0)} "
            f"avg_duration={metrics.get('avg_duration_seconds', 0)}"
        )
        category_counts = metrics.get("memory_recall_category_counts")
        if isinstance(category_counts, dict) and category_counts:
            console.print(
                "memory recall categories: "
                + " ".join(f"{category}={count}" for category, count in category_counts.items())
            )
    if summary.tag_summary:
        console.print("Tag Summary")
        for tag, item in summary.tag_summary.items():
            console.print(
                f"- {tag}: {item.get('passed_count', 0)}/{item.get('case_count', 0)} "
                f"passed ({float(item.get('pass_rate', 0.0)):.2%})"
            )
    if summary.error_messages:
        console.print("errors:")
        for message in summary.error_messages[:5]:
            console.print(f"- {message}")


__all__ = ["eval_report_main", "eval_run_main"]
