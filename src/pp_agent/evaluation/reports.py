from __future__ import annotations

from datetime import datetime, timezone
import html
import json
from pathlib import Path
import subprocess
from typing import Optional, Union

from pp_agent.evaluation.models import CaseScore, EvalReport


def current_commit_hash(cwd: Optional[Path] = None) -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=cwd, text=True, capture_output=True, check=False)
    except OSError:
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else "unknown"


def build_report(
    *,
    suite: str,
    mode: str,
    provider: str,
    model: str,
    scores: list[CaseScore],
    commit_hash: Optional[str] = None,
) -> EvalReport:
    total = len(scores)
    passed = sum(1 for score in scores if score.passed)
    pending = sum(1 for score in scores if score.pending)
    infra_failed = sum(1 for score in scores if score.infra_failed)
    failed = total - passed - pending
    safety_violations = sum(len(score.safety_violations) for score in scores)
    safety_clean = sum(1 for score in scores if not score.safety_violations)
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
        infra_failed=infra_failed,
        task_success_rate=(passed / total) if total else 0.0,
        state_reward=_avg([score.state_reward for score in scores], default=0.0),
        communication_reward=_avg([score.communication_reward for score in scores], default=0.0),
        action_reward=_avg([score.action_reward for score in scores], default=0.0),
        safety_violations=safety_violations,
        safety_rate=(safety_clean / total) if total else 1.0,
        approval_recall=_avg([score.approval_recall for score in scores], default=1.0),
        tool_success_rate=_avg([score.tool_success_rate for score in scores], default=1.0),
        average_tool_calls=_avg([float(score.tool_call_count) for score in scores], default=0.0),
        average_turns=_avg([float(score.turn_count) for score in scores], default=0.0),
        average_duration=_avg([score.duration_seconds for score in scores], default=0.0),
        category_summary=_category_summary(scores),
        cases=[score.model_dump(mode="json") for score in scores],
    )


def write_report(report: EvalReport, reports_dir: Path, *, save_history: bool = False) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    report = report.model_copy(update={"chart_path": "latest.svg"})
    json_path = reports_dir / "latest.json"
    md_path = reports_dir / "latest.md"
    svg_path = reports_dir / "latest.svg"
    json_path.write_text(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    svg_path.write_text(render_svg_chart(report), encoding="utf-8")
    if save_history:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        prefix = f"{report.suite}-{report.mode}-{stamp}"
        (reports_dir / f"{prefix}.json").write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
        (reports_dir / f"{prefix}.md").write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
        (reports_dir / f"{prefix}.svg").write_text(svg_path.read_text(encoding="utf-8"), encoding="utf-8")
    return json_path, md_path


def load_latest_report(reports_dir: Path) -> EvalReport:
    path = reports_dir / "latest.json"
    if not path.exists():
        raise FileNotFoundError(f"No eval report found under {reports_dir}")
    return EvalReport.model_validate(json.loads(path.read_text(encoding="utf-8")))


def render_markdown(report: EvalReport) -> str:
    lines = [
        "# pp-Echo Tau-Style Eval Report",
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
        f"- State reward: `{report.state_reward:.2%}`",
        f"- Communication reward: `{report.communication_reward:.2%}`",
        f"- Action reward: `{report.action_reward:.2%}`",
        f"- Safety violations: `{report.safety_violations}`",
        f"- Safety rate: `{report.safety_rate:.2%}`",
        f"- Approval recall: `{report.approval_recall:.2%}`",
        f"- Tool success rate: `{report.tool_success_rate:.2%}`",
        f"- Average tool calls: `{report.average_tool_calls:.2f}`",
        f"- Average turns: `{report.average_turns:.2f}`",
        f"- Average duration: `{report.average_duration:.3f}s`",
        "",
        "![Eval chart](latest.svg)",
        "",
        "## Category Summary",
        "",
        "| Category | Total | Pass | Pending | Success | State | Communication | Action | Safety |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for category, item in sorted(report.category_summary.items()):
        lines.append(
            f"| `{category}` | {item['total']} | {item['passed']} | {item['pending']} | "
            f"{float(item['success_rate']):.2%} | {float(item['state_reward']):.2%} | "
            f"{float(item['communication_reward']):.2%} | {float(item['action_reward']):.2%} | "
            f"{float(item['safety_rate']):.2%} |"
        )
    lines.extend(["", "## Cases", "", "| Task | Category | Status | Failure reason |", "| --- | --- | --- | --- |"])
    for case in report.cases:
        status = "PASS" if case.get("passed") else "PENDING" if case.get("pending") else "FAIL"
        reasons = "; ".join(case.get("failure_reasons", [])) or "-"
        lines.append(f"| `{case.get('task_id')}` | `{case.get('category')}` | {status} | {reasons} |")
    lines.append("")
    return "\n".join(lines)


def render_svg_chart(report: EvalReport) -> str:
    metrics = [
        ("Task success", report.task_success_rate),
        ("State reward", report.state_reward),
        ("Communication", report.communication_reward),
        ("Action reward", report.action_reward),
        ("Safety", report.safety_rate),
    ]
    width = 780
    height = 360
    left = 180
    bar_width = 450
    rows = []
    for index, (label, value) in enumerate(metrics):
        y = 70 + index * 50
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
  <text x="24" y="32" class="title">pp-Echo Tau-Style Eval</text>
  <text x="24" y="54" class="meta">{html.escape(report.mode)} / {html.escape(report.model)} / {report.total_cases} cases</text>
  {''.join(rows)}
</svg>
"""


def _category_summary(scores: list[CaseScore]) -> dict[str, dict[str, Union[float, int]]]:
    grouped: dict[str, list[CaseScore]] = {}
    for score in scores:
        grouped.setdefault(score.category, []).append(score)
    summary: dict[str, dict[str, Union[float, int]]] = {}
    for category, items in grouped.items():
        total = len(items)
        passed = sum(1 for item in items if item.passed)
        pending = sum(1 for item in items if item.pending)
        safe = sum(1 for item in items if not item.safety_violations)
        summary[category] = {
            "total": total,
            "passed": passed,
            "pending": pending,
            "success_rate": (passed / total) if total else 0.0,
            "state_reward": _avg([item.state_reward for item in items], default=0.0),
            "communication_reward": _avg([item.communication_reward for item in items], default=0.0),
            "action_reward": _avg([item.action_reward for item in items], default=0.0),
            "safety_rate": (safe / total) if total else 1.0,
        }
    return summary


def _avg(values: list[float], *, default: float) -> float:
    return sum(values) / len(values) if values else default
