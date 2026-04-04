from __future__ import annotations

from pathlib import Path

from pp_agent.benchmarks import load_tasks, render_markdown, run_suite


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_core_benchmark_dataset_shape() -> None:
    tasks = load_tasks(REPO_ROOT, "core")

    assert len(tasks) == 15
    assert {task.group for task in tasks} == {
        "planner_gate",
        "safe_rewind",
        "session_branching",
        "mcp_lazy",
        "context_compaction",
    }


def test_run_suite_is_stable(tmp_path: Path) -> None:
    first, _ = run_suite(REPO_ROOT, suite="core", artifacts_dir=tmp_path / "artifacts1", docs_output=tmp_path / "latest1.md")
    second, _ = run_suite(REPO_ROOT, suite="core", artifacts_dir=tmp_path / "artifacts2", docs_output=tmp_path / "latest2.md")

    assert first.task_count == second.task_count == 15
    assert first.aggregate_metrics == second.aggregate_metrics
    assert [item.headline_results for item in [first, second]][0] == [item.headline_results for item in [first, second]][1]


def test_run_suite_writes_report_outputs(tmp_path: Path) -> None:
    result, artifact = run_suite(REPO_ROOT, suite="core", artifacts_dir=tmp_path / "artifacts", docs_output=tmp_path / "docs" / "latest.md")

    assert artifact is not None
    assert artifact.exists()
    report = (tmp_path / "docs" / "latest.md").read_text(encoding="utf-8")
    assert "pp-Echo Benchmark Report" in report
    assert "Headline results" in report
    assert "approval_block_rate_pp_echo" in report
    assert result.headline_results
    assert render_markdown(result).startswith("# pp-Echo Benchmark Report")
