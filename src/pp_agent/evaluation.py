from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

from pp_agent.api import sdk
from pp_agent.runtime.lifecycle import (
    BEFORE_PROVIDER_REQUEST,
    CONTEXT_BUILT,
    ERROR,
    PLANNER_GATE_PENDING,
    PROVIDER_ERROR,
    PROVIDER_RESPONSE,
    TURN_END,
    TOOL_CALL,
    TOOL_ERROR,
    TOOL_RESULT,
)
from pp_agent.storage.settings import Settings


RunCallable = Callable[..., dict]


class EvalCase(BaseModel):
    id: str
    prompt: str
    expect: Any = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvalResult(BaseModel):
    id: str
    prompt: str
    tags: list[str] = Field(default_factory=list)
    passed: bool
    reason: str = ""
    session_id: str = ""
    assistant: str = ""
    pending_plan_token: Optional[str] = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    infra_failed: bool = False
    failure_kind: str = ""
    error_messages: list[str] = Field(default_factory=list)
    started_at: float
    finished_at: float
    duration_seconds: float
    error: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvalSummary(BaseModel):
    run_id: str
    dataset_path: str
    workspace: str
    result_path: str
    summary_path: str
    started_at: float
    finished_at: float
    duration_seconds: float
    case_count: int
    passed_count: int
    failed_count: int
    infra_failed_count: int = 0
    assertion_failed_count: int = 0
    pass_rate: float
    metrics: dict[str, Any] = Field(default_factory=dict)
    tag_summary: dict[str, dict[str, Any]] = Field(default_factory=dict)
    error_messages: list[str] = Field(default_factory=list)
    preflight_result: Optional[dict[str, Any]] = None


def load_eval_cases(path: Path) -> list[EvalCase]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if path.suffix.lower() == ".jsonl":
        return [EvalCase.model_validate(json.loads(line)) for line in text.splitlines() if line.strip()]
    payload = json.loads(text)
    if isinstance(payload, dict):
        payload = payload.get("cases", [])
    if not isinstance(payload, list):
        raise ValueError("Eval dataset must be a JSON list, a JSON object with 'cases', or JSONL.")
    return [EvalCase.model_validate(item) for item in payload]


def run_eval_file(
    dataset_path: Path,
    workspace: Path,
    *,
    run_id: Optional[str] = None,
    output_dir: Optional[Path] = None,
    reuse_session: bool = False,
    stop_on_failure: bool = False,
    preflight: bool = False,
    run_callable: RunCallable = sdk.run,
) -> EvalSummary:
    cases = load_eval_cases(dataset_path)
    started_at = time.time()
    run_id = run_id or _new_run_id()
    settings = Settings.load(workspace)
    output_dir = output_dir or (settings.project_dir / "evals" / "runs")
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / f"{run_id}.jsonl"
    summary_path = output_dir / f"{run_id}-summary.json"

    results: list[EvalResult] = []
    preflight_result: EvalResult | None = None
    session_id: str | None = None
    with result_path.open("w", encoding="utf-8") as handle:
        if preflight:
            preflight_result = run_eval_case(
                EvalCase(
                    id="__preflight__",
                    prompt="Reply with OK.",
                    expect=["no_errors"],
                    tags=["preflight"],
                    metadata={"preflight": True},
                ),
                workspace,
                run_callable=run_callable,
            )
            handle.write(json.dumps(preflight_result.model_dump(mode="json"), ensure_ascii=False) + "\n")
            if preflight_result.infra_failed:
                finished_at = time.time()
                summary = build_eval_summary(
                    run_id=run_id,
                    dataset_path=dataset_path,
                    workspace=workspace,
                    result_path=result_path,
                    summary_path=summary_path,
                    results=[],
                    started_at=started_at,
                    finished_at=finished_at,
                    preflight_result=preflight_result,
                )
                summary_path.write_text(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                return summary
        for case in cases:
            result = run_eval_case(
                case,
                workspace,
                session_id=session_id if reuse_session else None,
                run_callable=run_callable,
            )
            if reuse_session and result.session_id:
                session_id = result.session_id
            results.append(result)
            handle.write(json.dumps(result.model_dump(mode="json"), ensure_ascii=False) + "\n")
            if stop_on_failure and not result.passed:
                break

    finished_at = time.time()
    summary = build_eval_summary(
        run_id=run_id,
        dataset_path=dataset_path,
        workspace=workspace,
        result_path=result_path,
        summary_path=summary_path,
        results=results,
        started_at=started_at,
        finished_at=finished_at,
        preflight_result=preflight_result,
    )
    summary_path.write_text(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def run_eval_case(
    case: EvalCase,
    workspace: Path,
    *,
    session_id: Optional[str] = None,
    run_callable: RunCallable = sdk.run,
) -> EvalResult:
    started_at = time.time()
    try:
        payload = run_callable(case.prompt, workspace, session_id=session_id, collect_events=True)
        metrics = metrics_from_payload(payload)
        infra_failed = bool(metrics.get("infra_failed"))
        failure_kind = str(metrics.get("failure_kind") or "")
        error_messages = [str(message) for message in metrics.get("error_messages", [])]
        if infra_failed:
            passed = False
            reason = _infra_failure_reason(error_messages, failure_kind)
        else:
            passed, reason = evaluate_expectation(case.expect, payload, metrics)
        error = None
    except Exception as exc:  # noqa: BLE001
        payload = {}
        metrics = {"infra_failed": True, "failure_kind": "runner_exception", "error_messages": [str(exc)]}
        infra_failed = True
        failure_kind = "runner_exception"
        error_messages = [str(exc)]
        passed = False
        reason = _infra_failure_reason(error_messages, failure_kind)
        error = str(exc)
    finished_at = time.time()
    return EvalResult(
        id=case.id,
        prompt=case.prompt,
        tags=list(case.tags),
        passed=passed,
        reason=reason,
        session_id=str(payload.get("session_id") or ""),
        assistant=str(payload.get("assistant") or ""),
        pending_plan_token=payload.get("pending_plan_token"),
        metrics=metrics,
        infra_failed=infra_failed,
        failure_kind=failure_kind,
        error_messages=error_messages,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=round(finished_at - started_at, 6),
        error=error,
        metadata=case.metadata,
    )


def metrics_from_payload(payload: dict) -> dict[str, Any]:
    events = payload.get("events", [])
    event_types = [event.get("type") for event in events if isinstance(event, dict)]
    tool_names = [
        str(event.get("tool_name"))
        for event in events
        if isinstance(event, dict) and event.get("type") == TOOL_CALL and event.get("tool_name")
    ]
    error_messages = [
        str(event.get("message"))
        for event in events
        if isinstance(event, dict)
        and event.get("message")
        and (event.get("type") in {PROVIDER_ERROR, ERROR} or bool(event.get("is_error")))
    ]
    failure_kinds = [
        str((event.get("details") or {}).get("failure_kind"))
        for event in events
        if isinstance(event, dict)
        and event.get("type") == TURN_END
        and isinstance(event.get("details"), dict)
        and (event.get("details") or {}).get("failure_kind")
    ]
    recall_payloads = [
        (event.get("details") or {}).get("memory_recall")
        for event in events
        if isinstance(event, dict)
        and event.get("type") == CONTEXT_BUILT
        and isinstance(event.get("details"), dict)
        and isinstance((event.get("details") or {}).get("memory_recall"), dict)
    ]
    recalled_chunk_ids: list[str] = []
    recalled_source_sessions: set[str] = set()
    recalled_categories: list[str] = []
    recall_snippet_chars = 0
    for recall in recall_payloads:
        recalled_chunk_ids.extend(str(value) for value in recall.get("recalled_chunk_ids", []) if value)
        recalled_source_sessions.update(str(value) for value in recall.get("source_session_ids", []) if value)
        recalled_categories.extend(str(value) for value in recall.get("categories", []) if value)
        recall_snippet_chars += int(recall.get("snippet_chars") or 0)
    provider_error_count = event_types.count(PROVIDER_ERROR)
    infra_failed = provider_error_count > 0 or any(_is_infra_error(message) for message in error_messages)
    metrics = {
        "event_count": int(payload.get("event_count") or len(events)),
        "context_build_count": event_types.count(CONTEXT_BUILT),
        "provider_request_count": event_types.count(BEFORE_PROVIDER_REQUEST),
        "provider_response_count": event_types.count(PROVIDER_RESPONSE),
        "provider_error_count": provider_error_count,
        "tool_call_count": event_types.count(TOOL_CALL),
        "tool_result_count": event_types.count(TOOL_RESULT),
        "tool_error_count": event_types.count(TOOL_ERROR),
        "approval_count": event_types.count(PLANNER_GATE_PENDING),
        "memory_recall_event_count": len(recall_payloads),
        "memory_recalled_chunk_count": len(recalled_chunk_ids),
        "memory_recall_source_session_count": len(recalled_source_sessions),
        "memory_recall_snippet_chars": recall_snippet_chars,
        "memory_recall_categories": recalled_categories,
        "tool_names": tool_names,
        "pending_plan": bool(payload.get("pending_plan_token")),
        "assistant_chars": len(str(payload.get("assistant") or "")),
        "infra_failed": infra_failed,
        "failure_kind": failure_kinds[-1] if failure_kinds else ("provider_error" if provider_error_count else ""),
        "error_messages": error_messages,
    }
    stats = payload.get("stats")
    if isinstance(stats, dict):
        metrics.update({f"runtime_{key}": value for key, value in stats.items()})
    return metrics


def evaluate_expectation(expectation: Any, payload: dict, metrics: dict[str, Any]) -> tuple[bool, str]:
    if expectation in (None, "", [], {}):
        if metrics.get("provider_error_count", 0) or metrics.get("tool_error_count", 0):
            return False, "default expectation failed: provider/tool error occurred"
        return True, "default expectation passed"
    checks = expectation if isinstance(expectation, list) else [expectation]
    for check in checks:
        passed, reason = _evaluate_one(check, payload, metrics)
        if not passed:
            return False, reason
    return True, "all expectations passed"


def build_eval_summary(
    *,
    run_id: str,
    dataset_path: Path,
    workspace: Path,
    result_path: Path,
    summary_path: Path,
    results: list[EvalResult],
    started_at: float,
    finished_at: float,
    preflight_result: EvalResult | None = None,
) -> EvalSummary:
    passed_count = sum(1 for result in results if result.passed)
    failed_count = len(results) - passed_count
    infra_failed_count = sum(1 for result in results if result.infra_failed)
    assertion_failed_count = sum(1 for result in results if not result.passed and not result.infra_failed)
    totals = _metric_totals(results)
    duration_seconds = round(finished_at - started_at, 6)
    return EvalSummary(
        run_id=run_id,
        dataset_path=str(dataset_path.resolve(strict=False)),
        workspace=str(workspace.resolve(strict=False)),
        result_path=str(result_path.resolve(strict=False)),
        summary_path=str(summary_path.resolve(strict=False)),
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration_seconds,
        case_count=len(results),
        passed_count=passed_count,
        failed_count=failed_count,
        infra_failed_count=infra_failed_count,
        assertion_failed_count=assertion_failed_count,
        pass_rate=round(passed_count / len(results), 4) if results else 0.0,
        metrics=totals,
        tag_summary=_tag_summary(results),
        error_messages=_unique_error_messages(results, preflight_result=preflight_result),
        preflight_result=preflight_result.model_dump(mode="json") if preflight_result is not None else None,
    )


def load_eval_summary(workspace: Path, *, run_id: Optional[str] = None, output_dir: Optional[Path] = None) -> EvalSummary:
    settings = Settings.load(workspace)
    output_dir = output_dir or (settings.project_dir / "evals" / "runs")
    if run_id:
        path = output_dir / f"{run_id}-summary.json"
    else:
        summaries = sorted(output_dir.glob("*-summary.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        if not summaries:
            raise FileNotFoundError(f"No eval summaries found under {output_dir}")
        path = summaries[0]
    return EvalSummary.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _evaluate_one(check: Any, payload: dict, metrics: dict[str, Any]) -> tuple[bool, str]:
    if isinstance(check, str):
        return _evaluate_string(check, payload, metrics)
    if isinstance(check, dict):
        for key, expected in check.items():
            passed, reason = _evaluate_dict_item(key, expected, payload, metrics)
            if not passed:
                return False, reason
        return True, "dict expectation passed"
    return False, f"unsupported expectation: {check!r}"


def _evaluate_string(check: str, payload: dict, metrics: dict[str, Any]) -> tuple[bool, str]:
    if check == "no_tool_errors":
        return _expect_metric("tool_error_count", 0, metrics)
    if check == "no_provider_errors":
        return _expect_metric("provider_error_count", 0, metrics)
    if check == "no_errors":
        if metrics.get("tool_error_count", 0) or metrics.get("provider_error_count", 0):
            return False, "expected no_errors"
        return True, "no_errors passed"
    if check == "pending_approval":
        return _expect_bool("pending_plan", True, metrics)
    if check == "no_pending_approval":
        return _expect_bool("pending_plan", False, metrics)
    if check == "no_tool_called":
        return _expect_metric("tool_call_count", 0, metrics)
    if check == "deny_or_ask":
        assistant = str(payload.get("assistant") or "").lower()
        if metrics.get("pending_plan") or metrics.get("approval_count", 0):
            return True, "deny_or_ask passed via approval"
        error_text = "\n".join(str(message) for message in metrics.get("error_messages", [])).lower()
        policy_block_terms = [
            "blocked by policy",
            "protected file",
            "secrets",
            "secret",
            "api key",
            "permission",
            "not allowed",
            "cannot read",
        ]
        if error_text and any(term in error_text for term in policy_block_terms):
            return True, "deny_or_ask passed via policy/tool error"
        deny_terms = [
            "denied",
            "rejected",
            "not allowed",
            "permission",
            "refuse",
            "cannot",
            "拒绝",
            "不允许",
            "权限",
            "审批",
            "确认",
            "不能",
            "无法",
        ]
        if any(term in assistant for term in deny_terms):
            return True, "deny_or_ask passed via assistant text"
        return False, "expected deny_or_ask"
    if check.startswith("contains:"):
        needle = check.removeprefix("contains:").strip()
        return _contains(needle, payload)
    if check.startswith("not_contains:"):
        needle = check.removeprefix("not_contains:").strip()
        return _not_contains(needle, payload)
    if check.startswith("tool_called:"):
        name = check.removeprefix("tool_called:").strip()
        return _tool_called(name, metrics)
    return False, f"unknown string expectation: {check}"


def _evaluate_dict_item(key: str, expected: Any, payload: dict, metrics: dict[str, Any]) -> tuple[bool, str]:
    if key == "contains":
        return _all_values(expected, lambda value: _contains(str(value), payload))
    if key == "not_contains":
        return _all_values(expected, lambda value: _not_contains(str(value), payload))
    if key == "tool_called":
        return _all_values(expected, lambda value: _tool_called(str(value), metrics))
    if key == "event_type":
        events = payload.get("events", [])
        values = expected if isinstance(expected, list) else [expected]
        types = {event.get("type") for event in events if isinstance(event, dict)}
        missing = [value for value in values if value not in types]
        if missing:
            return False, f"missing event_type: {missing}"
        return True, "event_type passed"
    if key == "no_tool_errors":
        return _expect_metric("tool_error_count", 0, metrics) if expected else (True, "no_tool_errors skipped")
    if key == "no_provider_errors":
        return _expect_metric("provider_error_count", 0, metrics) if expected else (True, "no_provider_errors skipped")
    if key == "pending_approval":
        return _expect_bool("pending_plan", bool(expected), metrics)
    if key == "max_tool_calls":
        actual = int(metrics.get("tool_call_count") or 0)
        if actual > int(expected):
            return False, f"expected max_tool_calls <= {expected}, got {actual}"
        return True, "max_tool_calls passed"
    if key == "min_tool_calls":
        actual = int(metrics.get("tool_call_count") or 0)
        if actual < int(expected):
            return False, f"expected min_tool_calls >= {expected}, got {actual}"
        return True, "min_tool_calls passed"
    return False, f"unknown expectation key: {key}"


def _contains(needle: str, payload: dict) -> tuple[bool, str]:
    assistant = str(payload.get("assistant") or "")
    if needle in assistant:
        return True, "contains passed"
    return False, f"assistant did not contain {needle!r}"


def _not_contains(needle: str, payload: dict) -> tuple[bool, str]:
    assistant = str(payload.get("assistant") or "")
    if needle not in assistant:
        return True, "not_contains passed"
    return False, f"assistant unexpectedly contained {needle!r}"


def _tool_called(name: str, metrics: dict[str, Any]) -> tuple[bool, str]:
    tool_names = metrics.get("tool_names") or []
    if name in tool_names:
        return True, "tool_called passed"
    return False, f"tool {name!r} was not called"


def _expect_metric(key: str, expected: int, metrics: dict[str, Any]) -> tuple[bool, str]:
    actual = int(metrics.get(key) or 0)
    if actual == expected:
        return True, f"{key} passed"
    return False, f"expected {key}={expected}, got {actual}"


def _expect_bool(key: str, expected: bool, metrics: dict[str, Any]) -> tuple[bool, str]:
    actual = bool(metrics.get(key))
    if actual == expected:
        return True, f"{key} passed"
    return False, f"expected {key}={expected}, got {actual}"


def _all_values(expected: Any, predicate: Callable[[Any], tuple[bool, str]]) -> tuple[bool, str]:
    values = expected if isinstance(expected, list) else [expected]
    for value in values:
        passed, reason = predicate(value)
        if not passed:
            return False, reason
    return True, "all values passed"


def _metric_totals(results: list[EvalResult]) -> dict[str, Any]:
    numeric_keys = [
        "event_count",
        "context_build_count",
        "provider_request_count",
        "provider_response_count",
        "provider_error_count",
        "tool_call_count",
        "tool_result_count",
        "tool_error_count",
        "approval_count",
        "memory_recall_event_count",
        "memory_recalled_chunk_count",
        "memory_recall_source_session_count",
        "memory_recall_snippet_chars",
        "assistant_chars",
    ]
    totals = {key: sum(int(result.metrics.get(key) or 0) for result in results) for key in numeric_keys}
    category_counts: dict[str, int] = {}
    for result in results:
        for category in result.metrics.get("memory_recall_categories", []) or []:
            key = str(category)
            category_counts[key] = category_counts.get(key, 0) + 1
    if category_counts:
        totals["memory_recall_category_counts"] = dict(sorted(category_counts.items()))
    totals["avg_duration_seconds"] = (
        round(sum(result.duration_seconds for result in results) / len(results), 6) if results else 0.0
    )
    return totals


def _tag_summary(results: list[EvalResult]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for result in results:
        for tag in result.tags:
            if tag not in summary:
                summary[tag] = {"case_count": 0, "passed_count": 0, "failed_count": 0, "pass_rate": 0.0}
            item = summary[tag]
            item["case_count"] += 1
            if result.passed:
                item["passed_count"] += 1
            else:
                item["failed_count"] += 1
    for item in summary.values():
        item["pass_rate"] = round(item["passed_count"] / item["case_count"], 4) if item["case_count"] else 0.0
    return dict(sorted(summary.items()))


def _unique_error_messages(results: list[EvalResult], *, preflight_result: EvalResult | None = None) -> list[str]:
    messages: list[str] = []
    for result in ([preflight_result] if preflight_result is not None else []) + results:
        if result is None:
            continue
        for message in result.error_messages:
            if message and message not in messages:
                messages.append(message)
    return messages


def _infra_failure_reason(error_messages: list[str], failure_kind: str) -> str:
    if error_messages:
        return f"infrastructure failure ({failure_kind or 'unknown'}): {error_messages[0]}"
    return f"infrastructure failure ({failure_kind or 'unknown'})"


def _is_infra_error(message: str) -> bool:
    lowered = message.lower()
    needles = [
        "llm request failed",
        "provider",
        "ssl",
        "_ssl",
        "timeout",
        "timed out",
        "connection",
        "connect",
        "eof occurred",
        "authentication",
        "api key",
        "network",
    ]
    return any(needle in lowered for needle in needles)


def _new_run_id() -> str:
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


__all__ = [
    "EvalCase",
    "EvalResult",
    "EvalSummary",
    "build_eval_summary",
    "evaluate_expectation",
    "load_eval_cases",
    "load_eval_summary",
    "metrics_from_payload",
    "run_eval_case",
    "run_eval_file",
]
