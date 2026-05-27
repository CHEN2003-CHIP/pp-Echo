from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import subprocess
from typing import Any


@dataclass(frozen=True)
class EvalReport:
    commit_hash: str
    date: str
    provider: str
    model: str
    mode: str
    suite: str
    total_cases: int
    passed: int
    failed: int
    pending: int
    task_success_rate: float
    safety_violations: int
    safety_rate: float
    approval_recall: float
    tool_success_rate: float
    average_tool_calls: float
    average_duration: float
    category_summary: dict[str, dict[str, float | int]]
    chart_path: str
    cases: list[dict[str, Any]]


def current_commit_hash(cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip() or "unknown"


def build_report(
    *,
    suite: str,
    mode: str,
    provider: str,
    model: str,
    case_results: list[dict[str, Any]],
    commit_hash: str | None = None,
) -> EvalReport:
    total = len(case_results)
    passed = sum(1 for case in case_results if case.get("passed") is True)
    pending = sum(1 for case in case_results if case.get("pending") is True)
    failed = total - passed - pending
    safety_violations = sum(len(case.get("safety_violations", [])) for case in case_results)
    safety_clean_cases = sum(1 for case in case_results if not case.get("safety_violations", []))
    approval_values = [float(case.get("approval_recall", 1.0)) for case in case_results]
    tool_success_values = [float(case.get("tool_success_rate", 1.0)) for case in case_results]
    tool_counts = [float(case.get("tool_call_count", 0)) for case in case_results]
    durations = [float(case.get("duration_seconds", 0.0)) for case in case_results]
    category_summary = _category_summary(case_results)

    return EvalReport(
        commit_hash=commit_hash or current_commit_hash(Path.cwd()),
        date=datetime.now(timezone.utc).isoformat(),
        provider=provider,
        model=model,
        mode=mode,
        suite=suite,
        total_cases=total,
        passed=passed,
        failed=failed,
        pending=pending,
        task_success_rate=(passed / total) if total else 0.0,
        safety_violations=safety_violations,
        safety_rate=(safety_clean_cases / total) if total else 1.0,
        approval_recall=(sum(approval_values) / len(approval_values)) if approval_values else 1.0,
        tool_success_rate=(sum(tool_success_values) / len(tool_success_values)) if tool_success_values else 1.0,
        average_tool_calls=(sum(tool_counts) / len(tool_counts)) if tool_counts else 0.0,
        average_duration=(sum(durations) / len(durations)) if durations else 0.0,
        category_summary=category_summary,
        chart_path="",
        cases=case_results,
    )


def write_report(report: EvalReport, reports_dir: Path, *, save_history: bool = False) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    chart_path = reports_dir / "latest.svg"
    report = EvalReport(**{**asdict(report), "chart_path": chart_path.name})
    json_path = reports_dir / "latest.json"
    md_path = reports_dir / "latest.md"

    json_path.write_text(json.dumps(asdict(report), indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    chart_path.write_text(render_svg_chart(report), encoding="utf-8")
    if save_history:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        prefix = f"{report.suite}-{report.mode}-{stamp}"
        (reports_dir / f"{prefix}.json").write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
        (reports_dir / f"{prefix}.md").write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
        (reports_dir / f"{prefix}.svg").write_text(chart_path.read_text(encoding="utf-8"), encoding="utf-8")
    return json_path, md_path


def render_markdown(report: EvalReport) -> str:
    lines = [
        "# pp-Echo Eval Report",
        "",
        f"- Commit: `{report.commit_hash}`",
        f"- Date: `{report.date}`",
        f"- Suite: `{report.suite}`",
        f"- Mode: `{report.mode}`",
        f"- Provider: `{report.provider}`",
        f"- Model: `{report.model}`",
        f"- Total cases: `{report.total_cases}`",
        f"- Pass / fail / pending: `{report.passed}` / `{report.failed}` / `{report.pending}`",
        f"- Task success rate: `{report.task_success_rate:.2%}`",
        f"- Safety violations: `{report.safety_violations}`",
        f"- Safety rate: `{report.safety_rate:.2%}`",
        f"- Approval recall: `{report.approval_recall:.2%}`",
        f"- Tool success rate: `{report.tool_success_rate:.2%}`",
        f"- Average tool calls: `{report.average_tool_calls:.2f}`",
        f"- Average duration: `{report.average_duration:.3f}s`",
        f"- Chart: `{report.chart_path}`",
        "",
        "![Eval chart](latest.svg)",
        "",
        "## Category Summary",
        "",
        "| Category | Total | Pass | Pending | Success rate | Safety rate | Tool success | Avg duration |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for category, item in sorted(report.category_summary.items()):
        lines.append(
            f"| `{category}` | {item['total']} | {item['passed']} | {item['pending']} | "
            f"{float(item['success_rate']):.2%} | {float(item['safety_rate']):.2%} | "
            f"{float(item['tool_success_rate']):.2%} | {float(item['average_duration']):.3f}s |"
        )
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| Task | Category | Status | Failure reason |",
            "| --- | --- | --- | --- |",
        ]
    )
    for case in report.cases:
        status = "PASS" if case.get("passed") else "PENDING" if case.get("pending") else "FAIL"
        reasons = "; ".join(case.get("failure_reasons", [])) or "-"
        lines.append(f"| `{case.get('task_id')}` | `{case.get('category')}` | {status} | {reasons} |")
    lines.append("")
    return "\n".join(lines)


def _category_summary(case_results: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for case in case_results:
        grouped.setdefault(str(case.get("category", "unknown")), []).append(case)
    summary: dict[str, dict[str, float | int]] = {}
    for category, cases in grouped.items():
        total = len(cases)
        passed = sum(1 for case in cases if case.get("passed") is True)
        pending = sum(1 for case in cases if case.get("pending") is True)
        safe = sum(1 for case in cases if not case.get("safety_violations", []))
        tool_success = [float(case.get("tool_success_rate", 1.0)) for case in cases]
        durations = [float(case.get("duration_seconds", 0.0)) for case in cases]
        summary[category] = {
            "total": total,
            "passed": passed,
            "pending": pending,
            "success_rate": (passed / total) if total else 0.0,
            "safety_rate": (safe / total) if total else 1.0,
            "tool_success_rate": (sum(tool_success) / len(tool_success)) if tool_success else 1.0,
            "average_duration": (sum(durations) / len(durations)) if durations else 0.0,
        }
    return summary


def render_svg_chart(report: EvalReport) -> str:
    metrics = [
        ("Task success", report.task_success_rate),
        ("Safety", report.safety_rate),
        ("Tool success", report.tool_success_rate),
        ("Approval recall", report.approval_recall),
    ]
    width = 760
    height = 320
    left = 170
    bar_width = 460
    rows = []
    for index, (label, value) in enumerate(metrics):
        y = 72 + index * 52
        filled = max(0, min(bar_width, int(bar_width * value)))
        rows.append(
            f'<text x="24" y="{y + 18}" class="label">{html.escape(label)}</text>'
            f'<rect x="{left}" y="{y}" width="{bar_width}" height="28" rx="6" class="track"/>'
            f'<rect x="{left}" y="{y}" width="{filled}" height="28" rx="6" class="bar"/>'
            f'<text x="{left + bar_width + 18}" y="{y + 19}" class="value">{value:.1%}</text>'
        )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <style>
    .bg {{ fill: #ffffff; }}
    .title {{ font: 700 20px Arial, sans-serif; fill: #111827; }}
    .meta {{ font: 13px Arial, sans-serif; fill: #4b5563; }}
    .label {{ font: 14px Arial, sans-serif; fill: #111827; }}
    .value {{ font: 700 14px Arial, sans-serif; fill: #111827; }}
    .track {{ fill: #e5e7eb; }}
    .bar {{ fill: #2563eb; }}
  </style>
  <rect class="bg" width="100%" height="100%"/>
  <text x="24" y="32" class="title">pp-Echo Eval Baseline</text>
  <text x="24" y="54" class="meta">{html.escape(report.mode)} / {html.escape(report.model)} / {report.total_cases} cases</text>
  {''.join(rows)}
</svg>
"""
