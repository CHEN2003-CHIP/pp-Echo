from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.report import build_report, write_report
from evals.scorers import AgentTrace, CommandResult, EvalTask, expand_tasks, load_tasks, score_case, snapshot_files


ROOT = Path(__file__).resolve().parents[1]
EVALS_DIR = ROOT / "evals"


class AgentEvalAdapter:
    """Adapter boundary for future real AgentRuntime wiring."""

    def __init__(self, *, timeout_seconds: int = 120) -> None:
        self.timeout_seconds = timeout_seconds

    def run(self, task: EvalTask, workspace: Path, *, mode: str, model: str | None) -> AgentTrace:
        started = time.perf_counter()
        if mode == "live":
            return self._run_live_cli(task, workspace, started=started, model=model)
        trace = self._run_deterministic(task, workspace)
        return AgentTrace(
            tool_calls=trace.tool_calls,
            approvals=trace.approvals,
            events=trace.events,
            tool_results=trace.tool_results,
            checkpoint_rewind_restored=trace.checkpoint_rewind_restored,
            duration_seconds=time.perf_counter() - started,
        )

    def _template_id(self, task: EvalTask) -> str:
        return task.template_id or task.id.split("__", 1)[0]

    def _run_deterministic(self, task: EvalTask, workspace: Path) -> AgentTrace:
        template_id = self._template_id(task)
        if template_id == "file_edit_basic":
            app = workspace / "app.py"
            app.write_text(app.read_text(encoding="utf-8").replace("return 0", "return a + b"), encoding="utf-8")
            return AgentTrace(tool_calls=["read_file", "edit_file"], tool_results=[True, True])

        if template_id == "tool_selection":
            return AgentTrace(tool_calls=["read_file", "grep_code"], tool_results=[True, True])

        if template_id == "approval_required":
            (workspace / "approved.txt").write_text("Approved write from deterministic eval.\n", encoding="utf-8")
            return AgentTrace(tool_calls=["write_file"], approvals=["write_file"], tool_results=[True])

        if template_id == "protected_path":
            return AgentTrace(
                tool_calls=["read_file"],
                events=[{"type": "protected_path_blocked", "path": ".env"}],
                tool_results=[True],
            )

        if template_id == "checkpoint_rewind":
            app = workspace / "app.py"
            before = app.read_bytes()
            app.write_bytes(before.replace(b"return 0", b"return a + b"))
            app.write_bytes(before)
            return AgentTrace(
                tool_calls=["create_checkpoint", "edit_file", "execute_safe_rewind"],
                approvals=["edit_file", "execute_safe_rewind"],
                tool_results=[True, True, True],
                checkpoint_rewind_restored=True,
            )

        if template_id == "memory_recall":
            return AgentTrace(tool_calls=["memory_search"], events=[{"type": "memory_recall_pending"}], tool_results=[True])

        if template_id == "subagent_limited_tools":
            return AgentTrace(tool_calls=["spawn_subagent", "read_file"], tool_results=[True, True])

        return AgentTrace(events=[{"type": "unknown_task", "task_id": task.id}])

    def _run_live_cli(self, task: EvalTask, workspace: Path, *, started: float, model: str | None) -> AgentTrace:
        command = [
            sys.executable,
            "-m",
            "pp_agent.cli.main",
            "run",
            task.user_goal,
            "--workspace",
            str(workspace),
            "--json",
        ]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        try:
            completed = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return AgentTrace(
                events=[{"type": "adapter_pending", "message": f"live runtime timed out after {self.timeout_seconds}s"}],
                duration_seconds=time.perf_counter() - started,
            )

        events = [{"type": "live_cli_completed", "returncode": completed.returncode, "model": model or ""}]
        parsed_lines = _parse_json_objects(completed.stdout)
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "live runtime returned non-zero exit").strip()
            return AgentTrace(
                events=[{"type": "adapter_pending", "message": message[:500], "returncode": completed.returncode}],
                duration_seconds=time.perf_counter() - started,
            )

        tool_calls: list[str] = []
        tool_results: list[bool] = []
        approvals: list[str] = []
        payload = next((item.get("result") for item in parsed_lines if item.get("kind") == "result"), None)
        for item in parsed_lines:
            if item.get("kind") == "event" and isinstance(item.get("event"), dict):
                event = item["event"]
                events.append(event)
                event_type = str(event.get("type", ""))
                tool_name = str(event.get("tool_name") or event.get("name") or "")
                if event_type == "tool_call" and tool_name:
                    tool_calls.append(tool_name)
                if event_type in {"tool_result", "tool_error"}:
                    tool_results.append(not bool(event.get("is_error", event_type == "tool_error")))
                if event_type in {"planner_gate_pending", "approval_required", "pending_action_created"}:
                    details = event.get("details", {}) if isinstance(event.get("details"), dict) else {}
                    tools = details.get("tools") if isinstance(details, dict) else None
                    if isinstance(tools, list):
                        approvals.extend(str(tool) for tool in tools)
                    elif tool_name:
                        approvals.append(tool_name)
        if isinstance(payload, dict):
            raw_events = payload.get("events", [])
            if isinstance(raw_events, list):
                for event in raw_events:
                    if isinstance(event, dict):
                        events.append(event)
                        event_type = str(event.get("type", ""))
                        tool_name = str(event.get("tool_name") or event.get("name") or "")
                        if event_type in {"tool_call", "tool_start"} and tool_name:
                            tool_calls.append(tool_name)
                        if event_type in {"tool_result", "tool_end"}:
                            tool_results.append(not bool(event.get("is_error", False)))
                        if event_type in {"approval_required", "pending_action_created"} and tool_name:
                            approvals.append(tool_name)
            if not tool_calls and isinstance(payload.get("tool_calls"), list):
                tool_calls = [str(name) for name in payload["tool_calls"]]
        else:
            events.append({"type": "live_cli_unparsed_json", "stdout": completed.stdout[-500:]})

        return AgentTrace(
            tool_calls=tool_calls,
            approvals=approvals,
            events=events,
            tool_results=tool_results,
            duration_seconds=time.perf_counter() - started,
        )


def _parse_json_lines(text: str) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            items.append(value)
    return items


def _parse_json_objects(text: str) -> list[dict[str, object]]:
    objects = _parse_json_lines(text)
    if objects:
        return objects
    decoder = json.JSONDecoder()
    index = 0
    parsed: list[dict[str, object]] = []
    while index < len(text):
        brace = text.find("{", index)
        if brace < 0:
            break
        try:
            value, end = decoder.raw_decode(text[brace:])
        except json.JSONDecodeError:
            index = brace + 1
            continue
        if isinstance(value, dict):
            parsed.append(value)
        index = brace + end
    return parsed


def _extract_json_payload(text: str) -> object | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except Exception:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(stripped[start : end + 1])
        except Exception:
            return None
    return None


def copy_fixture(task: EvalTask, run_root: Path) -> Path:
    source = EVALS_DIR / "fixtures" / task.workspace_fixture
    if not source.exists():
        raise FileNotFoundError(f"Missing fixture for task {task.id}: {source}")
    target = run_root / task.id
    shutil.copytree(source, target)
    return target


def run_verification_commands(task: EvalTask, workspace: Path) -> list[CommandResult]:
    results: list[CommandResult] = []
    for command in task.verification_commands:
        completed = subprocess.run(command, cwd=workspace, shell=True, text=True, capture_output=True, check=False)
        results.append(
            CommandResult(
                command=command,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        )
    return results


def run_suite(*, suite: str, mode: str, model: str | None, case_count: int, timeout_seconds: int) -> list[dict[str, object]]:
    if suite != "baseline":
        raise ValueError(f"Unknown suite: {suite}")

    tasks = expand_tasks(load_tasks(EVALS_DIR / "tasks"), target_count=case_count)
    adapter = AgentEvalAdapter(timeout_seconds=timeout_seconds)
    case_results: list[dict[str, object]] = []

    with tempfile.TemporaryDirectory(prefix="pp_echo_eval_") as dirname:
        run_root = Path(dirname)
        for task in tasks:
            workspace = copy_fixture(task, run_root)
            before = snapshot_files(workspace)
            trace = adapter.run(task, workspace, mode=mode, model=model)
            after = snapshot_files(workspace)
            verification = run_verification_commands(task, workspace)
            score = score_case(
                task,
                before_snapshot=before,
                after_snapshot=after,
                trace=trace,
                verification_results=verification,
            )
            payload = asdict(score)
            payload["name"] = task.name
            payload["category"] = task.category
            payload["template_id"] = task.template_id
            payload["verification_results"] = [asdict(result) for result in verification]
            payload["trace_events"] = trace.events
            case_results.append(payload)

    return case_results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run pp-Echo baseline evals.")
    parser.add_argument("--suite", default="baseline")
    parser.add_argument("--mode", choices=["deterministic", "live"], default="deterministic")
    parser.add_argument("--model", default=None)
    parser.add_argument("--cases", type=int, default=100)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    args = parser.parse_args(argv)

    provider = "scripted" if args.mode == "deterministic" else "runtime"
    model = args.model or ("ScriptedLLM" if args.mode == "deterministic" else "unspecified")
    cases = run_suite(
        suite=args.suite,
        mode=args.mode,
        model=model,
        case_count=args.cases,
        timeout_seconds=args.timeout_seconds,
    )
    report = build_report(suite=args.suite, mode=args.mode, provider=provider, model=model, case_results=cases)
    json_path, md_path = write_report(report, EVALS_DIR / "reports", save_history=True)

    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(f"Passed {report.passed}/{report.total_cases} with {report.pending} pending")
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
